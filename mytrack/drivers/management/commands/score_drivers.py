"""
Management command: score_drivers
Scores all drivers for a given date (default: yesterday) based on their GPS trip data.

Run nightly:
    python manage.py score_drivers
    python manage.py score_drivers --date 2024-03-15

Scoring algorithm (0-100, higher = safer):
  Start at 100, apply deductions:
  - Speeding  : -3 per event (speed_kmh over per-ping limit + org grace; limit from
                road_speed_limit_kmh on GPSPing when set, else organisation.speed_limit_kmh)
  - Harsh accel: -4 per event (Δspeed > HARSH_DELTA_KMH between consecutive pings)
  - Idling    : -0.5 per minute (speed=0 and engine on, inferred from consecutive pings < 5 min apart)
  Floor at 0.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

HARSH_DELTA_KMH = 30  # Δspeed over consecutive pings considered harsh acceleration/braking
IDLING_MAX_GAP_MINUTES = 5  # pings further apart than this are not considered "idling"


class Command(BaseCommand):
    help = "Compute daily driver behaviour scores from GPS trip data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Date to score in YYYY-MM-DD format (default: yesterday)",
        )

    def handle(self, *args, **options):
        from mytrack.tracking.models import TrackedTrip
        from mytrack.drivers.models import Driver, DriverScore

        if options["date"]:
            score_date = date.fromisoformat(options["date"])
        else:
            score_date = timezone.now().date() - timedelta(days=1)

        self.stdout.write(f"Scoring drivers for {score_date}…")

        # Get all TrackedTrips for the date
        day_start = timezone.datetime(score_date.year, score_date.month, score_date.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        trips = TrackedTrip.objects.filter(started_at__gte=day_start, started_at__lt=day_end).select_related(
            "vehicle__organisation"
        )

        # Group trip pings by (vehicle_id, organisation_id) so trips without
        # driver_name (Traccar rarely sends it) are still captured.
        driver_data = {}
        for trip in trips:
            key = (trip.vehicle_id, trip.vehicle.organisation_id, trip.driver_name or "")
            if key not in driver_data:
                driver_data[key] = {
                    "trips": 0,
                    "distance_km": 0.0,
                    "speeding_events": 0,
                    "harsh_accel_events": 0,
                    "idling_minutes": 0.0,
                    "organisation_id": trip.vehicle.organisation_id,
                }
            d = driver_data[key]
            d["trips"] += 1
            d["distance_km"] += trip.distance_km or 0.0

            org = trip.vehicle.organisation
            grace = float(getattr(org, "speeding_grace_kmh", 0.0) or 0.0)
            fallback_limit = float(getattr(org, "speed_limit_kmh", 120) or 120)

            # Analyse pings for this trip
            pings = list(
                trip.pings.order_by("device_timestamp", "received_at").values(
                    "speed_kmh", "device_timestamp", "received_at", "road_speed_limit_kmh"
                )
            )
            prev_speed = None
            prev_time = None
            for ping in pings:
                spd = ping["speed_kmh"]
                t = ping["device_timestamp"] or ping["received_at"]

                if spd is not None:
                    raw_lim = ping["road_speed_limit_kmh"]
                    limit = float(raw_lim) if raw_lim is not None else fallback_limit
                    if spd > limit + grace:
                        d["speeding_events"] += 1

                    if prev_speed is not None and abs(spd - prev_speed) >= HARSH_DELTA_KMH:
                        d["harsh_accel_events"] += 1

                    if spd == 0 and prev_time is not None and t is not None:
                        gap_min = (t - prev_time).total_seconds() / 60
                        if 0 < gap_min <= IDLING_MAX_GAP_MINUTES:
                            d["idling_minutes"] += gap_min

                prev_speed = spd
                prev_time = t

        scored = 0
        for (vehicle_id, org_id, driver_name), stats in driver_data.items():
            # Prefer explicit driver name; fall back to whoever's default vehicle this is.
            if driver_name:
                driver = Driver.objects.filter(
                    organisation_id=org_id,
                    full_name__iexact=driver_name,
                ).first()
            else:
                driver = Driver.objects.filter(
                    organisation_id=org_id,
                    default_vehicle_id=vehicle_id,
                    is_active=True,
                ).first()
            if not driver:
                continue

            raw_score = 100
            raw_score -= stats["speeding_events"] * 3
            raw_score -= stats["harsh_accel_events"] * 4
            raw_score -= stats["idling_minutes"] * 0.5
            score = max(0, min(100, round(raw_score)))

            DriverScore.objects.update_or_create(
                driver=driver,
                scored_date=score_date,
                defaults={
                    "score": score,
                    "trips": stats["trips"],
                    "distance_km": round(stats["distance_km"], 1),
                    "speeding_events": stats["speeding_events"],
                    "harsh_accel_events": stats["harsh_accel_events"],
                    "idling_minutes": round(stats["idling_minutes"], 1),
                },
            )
            scored += 1

        self.stdout.write(self.style.SUCCESS(f"Done — {scored} driver(s) scored for {score_date}."))
