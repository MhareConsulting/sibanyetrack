"""
Management command: simulate_gps

Simulates GPS pings for all active vehicles in an organisation, moving them
along a Sandton-area circuit. Each vehicle is staggered so they appear at
different positions on the live map.

Writes to BOTH:
  - myTrack (direct ORM) → shows on myTrack Live Map
  - MyRoutes /api/driver/sim/gps/ → shows on MyRoutes Live Ops

Usage:
    .venv/Scripts/python manage.py simulate_gps --tenant demo
    .venv/Scripts/python manage.py simulate_gps --tenant demo --speed 80 --interval 3
    .venv/Scripts/python manage.py simulate_gps --tenant demo --vehicles "GP 201-001,GP 201-002"
"""

import math
import signal
import time as time_mod
import urllib.request
import urllib.error
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mytrack.tenancy.models import Organisation
from mytrack.vehicles.models import Vehicle, VehicleState
from mytrack.tracking.models import GPSPing, TrackedTrip
from mytrack.tracking.ingest import _get_or_create_trip, _update_trip_end
from mytrack.geofences.models import check_geofences

# Sandton-area circuit: [lon, lat, label]
SANDTON_CIRCUIT = [
    (28.1016, -26.0560, "Woodmead DC"),
    (28.0820, -26.0750, "Sunninghill"),
    (28.0567, -26.1076, "Sandton City"),
    (28.0586, -26.1094, "Netcare Sandton"),
    (28.0582, -26.1116, "Clicks Sandton"),
    (28.0415, -26.1459, "Rosebank"),
    (28.0414, -26.1476, "Checkers Rosebank"),
    (28.0440, -26.1521, "Woolworths Rosebank"),
    (28.0382, -26.1757, "Parktown"),
    (28.0473, -26.1600, "Hyde Park"),
    (28.0560, -26.1300, "Illovo"),
    (28.0700, -26.0950, "Bryanston"),
    (28.0850, -26.0700, "Fourways approach"),
    (28.1016, -26.0560, "Woodmead DC"),  # return to depot
]


def _haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lon1, lat1, lon2, lat2):
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _build_route(circuit, step_km):
    """Expand circuit waypoints into evenly-spaced GPS steps."""
    points = []
    for i in range(len(circuit) - 1):
        lon1, lat1, _ = circuit[i]
        lon2, lat2, _ = circuit[i + 1]
        seg_km = _haversine_km(lon1, lat1, lon2, lat2)
        if seg_km < 0.001:
            continue
        n_steps = max(1, int(seg_km / step_km))
        bearing = _bearing(lon1, lat1, lon2, lat2)
        for s in range(n_steps):
            t = s / n_steps
            points.append((lon1 + t * (lon2 - lon1), lat1 + t * (lat2 - lat1), bearing))
    return points


def _push_myroutes(myroutes_url, token, org_slug, vehicle_reg, lat, lon):
    """Fire-and-forget POST to MyRoutes sim/gps/ endpoint. Swallows errors."""
    if not myroutes_url or not token:
        return
    payload = json.dumps({
        "org_slug": org_slug,
        "vehicle_reg": vehicle_reg,
        "lat": lat,
        "lon": lon,
    }).encode()
    req = urllib.request.Request(
        myroutes_url,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # never block the simulation loop on a network error


class Command(BaseCommand):
    help = "Simulate GPS pings for vehicles — writes to myTrack and MyRoutes Live Ops."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Organisation slug (e.g. demo)")
        parser.add_argument("--speed", type=float, default=60.0, help="Simulated speed km/h (default 60)")
        parser.add_argument("--interval", type=float, default=5.0, help="Seconds between pings (default 5)")
        parser.add_argument("--vehicles", help="Comma-separated vehicle registrations to simulate")
        parser.add_argument("--max-vehicles", type=int, default=10, help="Max concurrent vehicles (default 10)")

    def handle(self, *args, **options):
        slug = options["tenant"]
        speed_kmh = options["speed"]
        interval = options["interval"]
        max_v = options["max_vehicles"]

        try:
            org = Organisation.objects.get(slug=slug)
        except Organisation.DoesNotExist:
            raise CommandError(f"Organisation '{slug}' not found.")

        qs = Vehicle.objects.filter(organisation=org, is_active=True)
        if options["vehicles"]:
            regs = [r.strip().upper() for r in options["vehicles"].split(",")]
            qs = qs.filter(registration__in=regs)

        vehicles = list(qs[:max_v])
        if not vehicles:
            raise CommandError("No active vehicles found for this organisation.")

        step_km = speed_kmh * (interval / 3600)
        route = _build_route(SANDTON_CIRCUIT, step_km)
        total = len(route)
        if total == 0:
            raise CommandError("Route is empty — speed/interval combination too large.")

        # MyRoutes bridge settings — derive sim URL from the existing sync URL
        sync_url = getattr(settings, "MYROUTES_SYNC_URL", "")
        myroutes_token = getattr(settings, "MYROUTES_SYNC_TOKEN", "")
        if sync_url:
            # e.g. http://localhost:8000/api/driver/sync/mytrack/ → http://localhost:8000
            from urllib.parse import urlparse
            parsed = urlparse(sync_url)
            myroutes_base = f"{parsed.scheme}://{parsed.netloc}"
            myroutes_sim_url = myroutes_base + "/api/driver/sim/gps/"
        else:
            myroutes_sim_url = ""

        offsets = [int(i * total / len(vehicles)) for i in range(len(vehicles))]
        positions = {v.id: offsets[i] for i, v in enumerate(vehicles)}

        self.stdout.write(self.style.SUCCESS(
            f"Simulating {len(vehicles)} vehicles at {speed_kmh} km/h, "
            f"ping every {interval}s — {total} steps/circuit. Press Ctrl+C to stop."
        ))
        for v in vehicles:
            self.stdout.write(f"  {v.registration}")

        running = [True]
        def _stop(sig, frame):
            running[0] = False
            self.stdout.write("\nStopping simulation…")
        signal.signal(signal.SIGINT, _stop)

        tick = 0
        while running[0]:
            now = timezone.now()
            for vehicle in vehicles:
                idx = positions[vehicle.id] % total
                lon, lat, heading = route[idx]

                # ── myTrack (direct ORM) ──────────────────────────────────────
                tracked_trip = _get_or_create_trip(vehicle, now, lat, lon, "Simulated Driver", None)
                GPSPing.objects.create(
                    vehicle=vehicle,
                    lat=lat, lon=lon,
                    speed_kmh=speed_kmh,
                    heading=heading,
                    driver_name="Simulated Driver",
                    device_timestamp=now,
                    tracked_trip=tracked_trip,
                )
                _update_trip_end(tracked_trip, lat, lon, speed_kmh)
                check_geofences(vehicle, lat, lon, "Simulated Driver", now)
                VehicleState.objects.update_or_create(
                    vehicle=vehicle,
                    defaults={
                        "lat": lat, "lon": lon,
                        "speed_kmh": speed_kmh, "heading": heading,
                        "driver_name": "Simulated Driver",
                        "myroutes_trip_id": None,
                        "last_seen": now,
                    },
                )

                # ── MyRoutes (HTTP, fire-and-forget) ──────────────────────────
                _push_myroutes(myroutes_sim_url, myroutes_token, slug, vehicle.registration, lat, lon)

                positions[vehicle.id] = idx + 1

            tick += 1
            if tick % 10 == 0:
                self.stdout.write(
                    f"  tick {tick} @ {now.strftime('%H:%M:%S')} — {len(vehicles)} vehicles active"
                )

            time_mod.sleep(interval)

        self.stdout.write(self.style.SUCCESS("Simulation stopped."))
