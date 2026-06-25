import math
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Max, Q, Sum
from django.utils import timezone

from mytrack.fuel.models import FuelEvent, FuelEventKind, FuelReading, FuelSource
from mytrack.geofences.models import GeofenceEvent
from mytrack.tenancy.models import Organisation
from mytrack.tracking.models import Alert, AlertKind, GPSPing, TrackedTrip
from mytrack.vehicles.models import Vehicle

from ...models import DailyFuelMetrics, DailyGeofenceMetrics, DailyVehicleMetrics


def _compute_co2(vehicle, distance_km: float) -> float:
    """Estimate CO₂ in kg for distance_km driven by vehicle."""
    consumption = vehicle.expected_fuel_lper100km
    if not consumption or consumption <= 0 or distance_km <= 0:
        return 0.0
    litres = distance_km / 100.0 * consumption
    co2_per_litre = float(getattr(vehicle, "co2_per_litre", 2.640) or 2.640)
    return round(litres * co2_per_litre, 3)


def _haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def _daterange(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


class Command(BaseCommand):
    help = "Aggregate daily speed/fuel/geofence metrics for reporting."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="Single date in YYYY-MM-DD.")
        parser.add_argument("--date-from", type=str, help="Start date in YYYY-MM-DD.")
        parser.add_argument("--date-to", type=str, help="End date in YYYY-MM-DD.")
        parser.add_argument("--org-slug", type=str, help="Optional organisation slug filter.")

    def handle(self, *args, **options):
        today = timezone.localtime(timezone.now()).date()
        if options.get("date"):
            start = end = date.fromisoformat(options["date"])
        else:
            start = date.fromisoformat(options["date_from"]) if options.get("date_from") else today - timedelta(days=1)
            end = date.fromisoformat(options["date_to"]) if options.get("date_to") else start
        if start > end:
            start, end = end, start

        org_qs = Organisation.objects.all()
        if options.get("org_slug"):
            org_qs = org_qs.filter(slug=options["org_slug"])

        for org in org_qs:
            for metric_date in _daterange(start, end):
                self._aggregate_org_day(org, metric_date)
                self.stdout.write(self.style.SUCCESS(f"{org.slug}: aggregated {metric_date.isoformat()}"))

    def _aggregate_org_day(self, org, metric_date):
        tz = timezone.get_current_timezone()
        day_start = timezone.make_aware(datetime.combine(metric_date, datetime.min.time()), tz)
        day_end = timezone.make_aware(datetime.combine(metric_date, datetime.max.time()), tz)

        vehicles = Vehicle.objects.filter(organisation=org, is_active=True).select_related("home_depot")
        for vehicle in vehicles:
            trip_qs = TrackedTrip.objects.filter(vehicle=vehicle, started_at__range=(day_start, day_end))
            ping_qs = GPSPing.objects.filter(vehicle=vehicle, device_timestamp__range=(day_start, day_end)).order_by("device_timestamp")
            speed_alert_qs = Alert.objects.filter(
                vehicle=vehicle,
                occurred_at__range=(day_start, day_end),
                kind=AlertKind.SPEEDING,
            )
            idle_alert_qs = Alert.objects.filter(
                vehicle=vehicle,
                occurred_at__range=(day_start, day_end),
                kind=AlertKind.IDLE,
            )

            cumulative_km = 0.0
            previous = None
            for ping in ping_qs.only("lat", "lon"):
                if previous:
                    cumulative_km += _haversine_km(previous.lat, previous.lon, ping.lat, ping.lon)
                previous = ping

            DailyVehicleMetrics.objects.update_or_create(
                vehicle=vehicle,
                metric_date=metric_date,
                defaults={
                    "organisation": org,
                    "depot": vehicle.home_depot,
                    "trip_count": trip_qs.count(),
                    "ping_count": ping_qs.count(),
                    "distance_km": round(cumulative_km or (trip_qs.aggregate(total=Sum("distance_km"))["total"] or 0.0), 3),
                    "avg_speed_kmh": round(ping_qs.aggregate(avg=Avg("speed_kmh"))["avg"] or 0.0, 2),
                    "max_speed_kmh": round(ping_qs.aggregate(top=Max("speed_kmh"))["top"] or 0.0, 2),
                    "idle_alert_count": idle_alert_qs.count(),
                    "speeding_alert_count": speed_alert_qs.count(),
                    "co2_kg": _compute_co2(vehicle, round(cumulative_km or (trip_qs.aggregate(total=Sum("distance_km"))["total"] or 0.0), 3)),
                },
            )

            fuel_qs = FuelReading.objects.filter(vehicle=vehicle, device_timestamp__range=(day_start, day_end)).order_by("device_timestamp")
            fuel_events = FuelEvent.objects.filter(vehicle=vehicle, occurred_at__range=(day_start, day_end))
            first_reading = fuel_qs.first()
            last_reading = fuel_qs.last()
            # When the ECU 'total fuel used' counter is available, the day's true burn is
            # counter[last] − counter[first]; otherwise fall back to the net level change.
            counter_vals = list(
                fuel_qs.filter(total_fuel_used_litres__isnull=False)
                .values_list("total_fuel_used_litres", flat=True)
            )
            if len(counter_vals) >= 2 and counter_vals[-1] >= counter_vals[0]:
                fuel_delta = -round(counter_vals[-1] - counter_vals[0], 2)  # negative = burned
            else:
                fuel_delta = round(
                    (last_reading.fuel_level_litres - first_reading.fuel_level_litres) if first_reading and last_reading else 0.0,
                    2,
                )
            inferred_data = bool(
                fuel_qs.filter(source=FuelSource.EST).exists()
                or fuel_qs.filter(source=FuelSource.PROBE)
                .filter(Q(raw_sensor_value__isnull=True) | Q(raw_sensor_value=0)).exists()
            )
            DailyFuelMetrics.objects.update_or_create(
                vehicle=vehicle,
                metric_date=metric_date,
                defaults={
                    "organisation": org,
                    "depot": vehicle.home_depot,
                    "reading_count": fuel_qs.count(),
                    "opening_fuel_litres": round(first_reading.fuel_level_litres, 2) if first_reading else 0.0,
                    "closing_fuel_litres": round(last_reading.fuel_level_litres, 2) if last_reading else 0.0,
                    "fuel_delta_litres": fuel_delta,
                    "total_refuel_litres": round(
                        fuel_events.filter(kind=FuelEventKind.REFUEL).aggregate(total=Sum("delta_litres"))["total"] or 0.0,
                        2,
                    ),
                    "total_drain_litres": round(
                        abs(
                            fuel_events.filter(kind__in=[FuelEventKind.DRAIN, FuelEventKind.THEFT]).aggregate(
                                total=Sum("delta_litres")
                            )["total"]
                            or 0.0
                        ),
                        2,
                    ),
                    "theft_event_count": fuel_events.filter(kind=FuelEventKind.THEFT).count(),
                    "drain_event_count": fuel_events.filter(kind=FuelEventKind.DRAIN).count(),
                    "excess_event_count": fuel_events.filter(kind=FuelEventKind.EXCESS_CONSUMPTION).count(),
                    "probe_fault_event_count": fuel_events.filter(kind=FuelEventKind.PROBE_FAULT).count(),
                    "inferred_data": inferred_data,
                },
            )

        geofence_events = GeofenceEvent.objects.filter(
            vehicle__organisation=org,
            occurred_at__range=(day_start, day_end),
        ).select_related("vehicle", "vehicle__home_depot", "geofence")

        grouped = {}
        open_enters = {}
        for event in geofence_events.order_by("vehicle_id", "geofence_id", "occurred_at"):
            key = (event.vehicle_id, event.geofence_id)
            group = grouped.setdefault(
                key,
                {
                    "vehicle": event.vehicle,
                    "geofence": event.geofence,
                    "enters": 0,
                    "exits": 0,
                    "durations": [],
                },
            )
            if event.kind == GeofenceEvent.ENTER:
                group["enters"] += 1
                open_enters[key] = event
            elif event.kind == GeofenceEvent.EXIT:
                group["exits"] += 1
                enter = open_enters.pop(key, None)
                if enter:
                    group["durations"].append((event.occurred_at - enter.occurred_at).total_seconds() / 60.0)

        for data in grouped.values():
            durations = [d for d in data["durations"] if d > 0]
            visit_count = len(durations)
            total_dwell = sum(durations) if durations else 0.0
            DailyGeofenceMetrics.objects.update_or_create(
                vehicle=data["vehicle"],
                geofence=data["geofence"],
                metric_date=metric_date,
                defaults={
                    "organisation": org,
                    "depot": data["vehicle"].home_depot,
                    "enter_count": data["enters"],
                    "exit_count": data["exits"],
                    "visit_count": visit_count,
                    "total_dwell_minutes": round(total_dwell, 2),
                    "avg_dwell_minutes": round((total_dwell / visit_count), 2) if visit_count else 0.0,
                    "max_dwell_minutes": round(max(durations), 2) if durations else 0.0,
                },
            )
