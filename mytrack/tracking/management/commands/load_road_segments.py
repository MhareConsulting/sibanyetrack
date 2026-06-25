"""
Download OSM highway ways for the fleet's operating area and load them
into the tracking_roadsegment PostGIS table used for dynamic speed limits.

Strategy: divides the GPS ping extent into 0.5° tiles, queries only tiles
that contain actual pings (via Overpass API), and bulk-inserts the results.
Deduplicates by osm_way_id so it is safe to re-run.

Usage:
  python manage.py load_road_segments            # auto from GPS pings
  python manage.py load_road_segments --tile-size 0.25   # finer tiles
  python manage.py load_road_segments --dry-run  # count tiles, no download
"""
from __future__ import annotations

import json
import math
import time
from typing import Iterator

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Road types we care about (ignore footways, tracks, etc.)
HIGHWAY_KEEP = {
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified", "residential",
    "living_street", "service",
}


class Command(BaseCommand):
    help = "Load OSM road segments for dynamic speed limit checks."

    def add_arguments(self, parser):
        parser.add_argument("--tile-size", type=float, default=0.5,
                            help="Tile size in degrees (default 0.5)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Show tiles that would be downloaded, then exit")
        parser.add_argument("--pause", type=float, default=1.5,
                            help="Seconds to wait between Overpass requests (default 1.5)")

    def handle(self, *args, **options):
        tile_size = options["tile_size"]
        dry_run   = options["dry_run"]
        pause     = options["pause"]

        tiles = list(self._tiles_with_pings(tile_size))
        if not tiles:
            raise CommandError("No GPS pings found. Ingest some vehicle data first.")

        self.stdout.write(f"Found {len(tiles)} tile(s) containing GPS pings.")
        if dry_run:
            for s, w, n, e in tiles:
                self.stdout.write(f"  tile S={s:.3f} W={w:.3f} N={n:.3f} E={e:.3f}")
            return

        total_inserted = 0
        total_skipped  = 0
        for i, (s, w, n, e) in enumerate(tiles, 1):
            self.stdout.write(
                f"[{i}/{len(tiles)}] Downloading tile ({s:.2f},{w:.2f})→({n:.2f},{e:.2f}) …",
                ending=" ",
            )
            self.stdout.flush()
            try:
                ways = self._fetch_ways(s, w, n, e)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"SKIP ({exc})"))
                continue

            inserted, skipped = self._upsert_ways(ways)
            total_inserted += inserted
            total_skipped  += skipped
            self.stdout.write(self.style.SUCCESS(f"{inserted} inserted, {skipped} already present"))

            if i < len(tiles):
                time.sleep(pause)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {total_inserted} new segments loaded, {total_skipped} duplicates skipped."
        ))
        if total_inserted:
            self.stdout.write(
                "Enable dynamic limits: set road_speed_limits_enabled=True on your organisation."
            )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _tiles_with_pings(self, tile_size: float) -> Iterator[tuple]:
        """Yield (south, west, north, east) for each 0.5° cell that has pings."""
        from mytrack.tracking.models import GPSPing

        # Pull distinct quantised cells — cheap aggregate in DB
        pings = (
            GPSPing.objects
            .filter(lat__lt=-5, lat__gt=-35, lon__gt=10, lon__lt=40)  # Africa sanity bounds
            .values_list("lat", "lon")
        )
        cells: set[tuple[float, float]] = set()
        for lat, lon in pings:
            cell = (
                math.floor(lat / tile_size) * tile_size,
                math.floor(lon / tile_size) * tile_size,
            )
            cells.add(cell)

        for s, w in sorted(cells):
            yield s, w, round(s + tile_size, 6), round(w + tile_size, 6)

    def _fetch_ways(self, s: float, w: float, n: float, e: float) -> list[dict]:
        """Query Overpass for highway ways in the tile bbox."""
        query = f"""
[out:json][timeout:60];
(
  way["highway"]({s},{w},{n},{e});
);
out geom;
"""
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=90,
            headers={"User-Agent": "myTrack/1.0 road-segment-loader (fleet management)"},
        )
        resp.raise_for_status()
        return resp.json().get("elements", [])

    def _upsert_ways(self, ways: list[dict]) -> tuple[int, int]:
        """Insert ways into tracking_roadsegment, skip duplicates. Returns (inserted, skipped)."""
        inserted = skipped = 0
        rows = []
        for way in ways:
            if way.get("type") != "way":
                continue
            tags     = way.get("tags", {})
            highway  = tags.get("highway", "")
            if highway not in HIGHWAY_KEEP:
                continue
            geometry = way.get("geometry", [])
            if len(geometry) < 2:
                continue
            osm_id   = way["id"]
            maxspeed = tags.get("maxspeed")  # may be None
            wkt      = "LINESTRING(" + ",".join(
                f"{p['lon']} {p['lat']}" for p in geometry
            ) + ")"
            rows.append((osm_id, highway, maxspeed, wkt))

        if not rows:
            return 0, 0

        with connection.cursor() as cur:
            for osm_id, highway, maxspeed, wkt in rows:
                cur.execute(
                    """
                    INSERT INTO tracking_roadsegment (osm_way_id, highway, maxspeed, geom)
                    VALUES (%s, %s, %s, ST_GeomFromText(%s, 4326))
                    ON CONFLICT (osm_way_id) DO NOTHING
                    """,
                    [osm_id, highway, maxspeed, wkt],
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1

        return inserted, skipped
