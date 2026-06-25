"""
Management command: seed_trip

Seeds a historical, road-following trip for GP 123-456 (Mercedes-Benz Actros)
by fetching a real road route from the OSRM public API and writing GPSPings
at regular distance intervals with back-dated timestamps.

Produces data you can immediately view in the Live Map → Tracks panel.

Usage:
    python manage.py seed_trip --tenant <slug>
    python manage.py seed_trip --tenant <slug> --date 2026-05-03
    python manage.py seed_trip --tenant <slug> --date 2026-05-03 --start-time 14:00
    python manage.py seed_trip --tenant <slug> --return-trip
"""

import json
import math
import random
import urllib.request
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mytrack.tenancy.models import Organisation
from mytrack.tracking.models import GPSPing, TrackedTrip
from mytrack.vehicles.models import Vehicle, VehicleState

# ── Route: City Deep (JHB) → Allandale (Midrand) → Silverton (Pretoria)
# Classic N1 northbound heavy-truck corridor, ~78 km
OUTBOUND_WAYPOINTS = [
    (28.0490, -26.2122),   # City Deep Container Terminal, JHB
    (28.1244, -25.9934),   # Allandale interchange, Midrand
    (28.2015, -25.7560),   # Silverton / Pretoria East
]

VEHICLE_REG   = "GP 123-456"
VEHICLE_LABEL = "Mercedes-Benz Actros"
DRIVER_NAME   = "K. Dlamini"
AVG_SPEED_KMH = 78.0      # trucks limited to 80 km/h in SA
SAMPLE_DIST_KM = 0.12     # one ping every ~120 m  ≈ 5-6 s at 80 km/h


def _haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lon1, lat1, lon2, lat2):
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r)
         - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _fetch_osrm_route(waypoints):
    """Return list of (lon, lat) road-snapped coordinates via OSRM."""
    coord_str = ";".join(f"{lon},{lat}" for lon, lat in waypoints)
    url = (
        f"http://router.project-osrm.org/route/v1/driving/{coord_str}"
        f"?overview=full&geometries=geojson"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "myTrack-seeder/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')} — {data.get('message', '')}")
    return data["routes"][0]["geometry"]["coordinates"]   # [[lon, lat], ...]


def _sample_route(osrm_coords, sample_dist_km):
    """
    Walk along the OSRM polyline and emit one point every `sample_dist_km`.
    Returns list of (lon, lat, cumulative_km, heading).
    """
    samples = []
    cum = 0.0
    last_sample = 0.0
    prev_lon, prev_lat = osrm_coords[0]
    samples.append((prev_lon, prev_lat, 0.0, 0.0))

    for lon, lat in osrm_coords[1:]:
        seg = _haversine_km(prev_lon, prev_lat, lon, lat)
        if seg == 0:
            continue
        head = _bearing(prev_lon, prev_lat, lon, lat)
        cum += seg
        if cum - last_sample >= sample_dist_km:
            samples.append((lon, lat, cum, head))
            last_sample = cum
        prev_lon, prev_lat = lon, lat

    # always include the destination
    last_lon, last_lat = osrm_coords[-1]
    head = _bearing(prev_lon, prev_lat, last_lon, last_lat) if len(osrm_coords) > 1 else 0.0
    samples.append((last_lon, last_lat, cum, head))
    return samples


def _speed_for_position(idx, total, avg_kmh):
    """
    Simulate realistic truck speed profile:
    - Slow leaving depot (first 10% of route)
    - Cruise speed in the middle
    - Slow approaching destination (last 8%)
    - Small random jitter throughout
    """
    frac = idx / max(total - 1, 1)
    if frac < 0.10:
        factor = 0.60 + frac * 4.0      # ramp up from 60% to 100%
    elif frac > 0.92:
        factor = 0.60 + (1 - frac) * 5  # ramp down to ~60%
    else:
        factor = 1.0

    jitter = random.gauss(0, 0.07)      # ±7% std dev
    speed = avg_kmh * max(0.4, min(1.15, factor + jitter))
    return round(speed, 1)


def _build_and_store_trip(vehicle, samples, start_dt, avg_kmh, driver_name, stdout, style):
    """Create TrackedTrip + bulk GPSPings for one direction. Returns the trip."""
    if not samples:
        return None

    first_lon, first_lat, _, _ = samples[0]
    trip = TrackedTrip.objects.create(
        vehicle=vehicle,
        driver_name=driver_name,
        started_at=start_dt,
        start_lat=first_lat,
        start_lon=first_lon,
        ping_count=0,
    )

    pings = []
    time_offset_s = 0.0
    total = len(samples)

    for i, (lon, lat, cum_km, heading) in enumerate(samples):
        if i > 0:
            prev_cum = samples[i - 1][2]
            seg_km = cum_km - prev_cum
            seg_speed = _speed_for_position(i, total, avg_kmh)
            time_offset_s += (seg_km / seg_speed) * 3600
        else:
            seg_speed = avg_kmh * 0.6

        ping_time = start_dt + timedelta(seconds=time_offset_s)
        pings.append(GPSPing(
            vehicle=vehicle,
            lat=lat,
            lon=lon,
            speed_kmh=_speed_for_position(i, total, avg_kmh),
            heading=heading,
            driver_name=driver_name,
            device_timestamp=ping_time,
            tracked_trip=trip,
        ))

    GPSPing.objects.bulk_create(pings, batch_size=500)

    last_lon, last_lat, total_km, _ = samples[-1]
    end_dt = start_dt + timedelta(seconds=time_offset_s)
    max_speed = max(p.speed_kmh for p in pings)

    trip.ended_at = end_dt
    trip.end_lat = last_lat
    trip.end_lon = last_lon
    trip.distance_km = round(total_km, 2)
    trip.max_speed_kmh = round(max_speed, 1)
    trip.ping_count = len(pings)
    trip.save(update_fields=["ended_at", "end_lat", "end_lon", "distance_km", "max_speed_kmh", "ping_count"])

    duration_min = time_offset_s / 60
    stdout.write(style.SUCCESS(
        f"  OK  Trip {trip.pk}: {len(pings)} pings, {total_km:.1f} km, "
        f"{start_dt.strftime('%H:%M')} to {end_dt.strftime('%H:%M')} "
        f"({duration_min:.0f} min)"
    ))
    return trip, end_dt, last_lat, last_lon


class Command(BaseCommand):
    help = "Seed a historical road-following trip for GP 123-456 (Mercedes-Benz Actros)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant", required=True,
            help="Organisation slug (e.g. demo)",
        )
        parser.add_argument(
            "--date", default=None,
            help="Trip date YYYY-MM-DD (default: yesterday)",
        )
        parser.add_argument(
            "--start-time", default="08:00",
            help="Outbound departure time HH:MM (default: 08:00)",
        )
        parser.add_argument(
            "--return-trip", action="store_true",
            help="Also create a return trip departing 3 h after outbound arrival",
        )
        parser.add_argument(
            "--speed", type=float, default=AVG_SPEED_KMH,
            help=f"Average cruise speed km/h (default: {AVG_SPEED_KMH})",
        )

    def handle(self, *args, **options):
        random.seed(42)   # reproducible jitter

        # ── Resolve org ────────────────────────────────────────────────
        try:
            org = Organisation.objects.get(slug=options["tenant"])
        except Organisation.DoesNotExist:
            raise CommandError(f"Organisation '{options['tenant']}' not found.")

        # ── Resolve date ───────────────────────────────────────────────
        if options["date"]:
            try:
                trip_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--date must be YYYY-MM-DD")
        else:
            trip_date = (timezone.now() - timedelta(days=1)).date()

        # ── Parse start time ───────────────────────────────────────────
        try:
            h, m = map(int, options["start_time"].split(":"))
        except (ValueError, AttributeError):
            raise CommandError("--start-time must be HH:MM")

        naive_start = datetime(trip_date.year, trip_date.month, trip_date.day, h, m, 0)
        start_dt = timezone.make_aware(naive_start) if timezone.is_naive(naive_start) else naive_start

        avg_speed = options["speed"]

        # ── Get or create vehicle ──────────────────────────────────────
        vehicle, created = Vehicle.objects.get_or_create(
            organisation=org,
            registration=VEHICLE_REG,
            defaults={"label": VEHICLE_LABEL},
        )
        if created:
            self.stdout.write(f"Created vehicle {VEHICLE_REG} — {VEHICLE_LABEL}")
        else:
            self.stdout.write(f"Using existing vehicle {VEHICLE_REG}")
            if not vehicle.label:
                vehicle.label = VEHICLE_LABEL
                vehicle.save(update_fields=["label"])

        # ── Fetch outbound route from OSRM ─────────────────────────────
        self.stdout.write("Fetching outbound route from OSRM (router.project-osrm.org)…")
        try:
            osrm_coords = _fetch_osrm_route(OUTBOUND_WAYPOINTS)
        except Exception as exc:
            raise CommandError(f"OSRM request failed: {exc}")
        self.stdout.write(f"  Route geometry: {len(osrm_coords)} nodes")

        outbound_samples = _sample_route(osrm_coords, SAMPLE_DIST_KM)
        self.stdout.write(f"  Sampled to {len(outbound_samples)} pings ({SAMPLE_DIST_KM*1000:.0f} m spacing)")

        # ── Build outbound trip ────────────────────────────────────────
        self.stdout.write(f"\nOutbound  {trip_date}  dep {start_dt.strftime('%H:%M')} —")
        result = _build_and_store_trip(
            vehicle, outbound_samples, start_dt, avg_speed, DRIVER_NAME,
            self.stdout, self.style,
        )
        if not result:
            raise CommandError("No pings generated — check route.")
        _, arrival_dt, last_lat, last_lon = result

        # ── Optional return trip ───────────────────────────────────────
        if options["return_trip"]:
            return_start = arrival_dt + timedelta(hours=3)
            return_waypoints = list(reversed(OUTBOUND_WAYPOINTS))

            self.stdout.write(f"\nReturn    {trip_date}  dep {return_start.strftime('%H:%M')} —")
            self.stdout.write("Fetching return route from OSRM…")
            try:
                return_coords = _fetch_osrm_route(return_waypoints)
            except Exception as exc:
                self.stderr.write(f"Return route failed: {exc} — skipping.")
                return_coords = None

            if return_coords:
                return_samples = _sample_route(return_coords, SAMPLE_DIST_KM)
                result2 = _build_and_store_trip(
                    vehicle, return_samples, return_start, avg_speed, DRIVER_NAME,
                    self.stdout, self.style,
                )
                if result2:
                    _, _, last_lat, last_lon = result2

        # ── Update VehicleState to final position ──────────────────────
        VehicleState.objects.update_or_create(
            vehicle=vehicle,
            defaults={
                "lat": last_lat,
                "lon": last_lon,
                "speed_kmh": 0,
                "heading": 0,
                "driver_name": DRIVER_NAME,
                "last_seen": arrival_dt,
            },
        )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Open Live Map, select {VEHICLE_REG}, open Tracks, "
            f"set date to {trip_date}, click Draw tracks."
        ))
