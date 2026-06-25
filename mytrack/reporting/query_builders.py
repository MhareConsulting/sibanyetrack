from datetime import datetime, timedelta

from django.db.models import Avg, Count, Max, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from mytrack.fuel.models import FuelEvent, FuelEventKind, FuelReading
from mytrack.geofences.models import GeofenceEvent
from mytrack.tracking.models import Alert, AlertKind, GPSPing, TrackedTrip


def parse_date_window(params, default_days=7):
    today = timezone.localtime(timezone.now()).date()
    date_from = parse_date(params.get("date_from", "")) or (today - timedelta(days=default_days))
    date_to = parse_date(params.get("date_to", "")) or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    day_start = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(date_to, datetime.max.time()))
    return date_from, date_to, day_start, day_end


def speed_queryset(org, depot=None, params=None):
    params = params or {}
    _, _, day_start, day_end = parse_date_window(params)
    qs = TrackedTrip.objects.filter(
        vehicle__organisation=org,
        started_at__range=(day_start, day_end),
    ).select_related("vehicle")
    if depot:
        qs = qs.filter(vehicle__home_depot=depot)
    vehicle_id = params.get("vehicle")
    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
    return qs


def speed_summary(org, depot=None, params=None):
    params = params or {}
    _, _, day_start, day_end = parse_date_window(params)
    alert_qs = Alert.objects.filter(
        vehicle__organisation=org,
        occurred_at__range=(day_start, day_end),
        kind=AlertKind.SPEEDING,
    )
    if depot:
        alert_qs = alert_qs.filter(vehicle__home_depot=depot)
    trip_qs = speed_queryset(org, depot=depot, params=params)
    return {
        "trip_count": trip_qs.count(),
        "distance_km": round(trip_qs.aggregate(total=Sum("distance_km"))["total"] or 0.0, 2),
        "avg_speed": round(trip_qs.aggregate(avg=Avg("max_speed_kmh"))["avg"] or 0.0, 2),
        "top_speed": round(trip_qs.aggregate(top=Max("max_speed_kmh"))["top"] or 0.0, 2),
        "overspeed_events": alert_qs.count(),
    }


def fuel_queryset(org, depot=None, params=None):
    params = params or {}
    _, _, day_start, day_end = parse_date_window(params)
    qs = FuelReading.objects.filter(vehicle__organisation=org, device_timestamp__range=(day_start, day_end)).select_related("vehicle")
    if depot:
        qs = qs.filter(vehicle__home_depot=depot)
    vehicle_id = params.get("vehicle")
    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
    return qs


def fuel_event_summary(org, depot=None, params=None):
    params = params or {}
    _, _, day_start, day_end = parse_date_window(params)
    qs = FuelEvent.objects.filter(vehicle__organisation=org, occurred_at__range=(day_start, day_end))
    if depot:
        qs = qs.filter(vehicle__home_depot=depot)
    vehicle_id = params.get("vehicle")
    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
    return {
        "refuels": qs.filter(kind=FuelEventKind.REFUEL).count(),
        "theft": qs.filter(kind=FuelEventKind.THEFT).count(),
        "drain": qs.filter(kind=FuelEventKind.DRAIN).count(),
        "excess": qs.filter(kind=FuelEventKind.EXCESS_CONSUMPTION).count(),
        "probe_fault": qs.filter(kind=FuelEventKind.PROBE_FAULT).count(),
        "refuel_litres": round(qs.filter(kind=FuelEventKind.REFUEL).aggregate(total=Sum("delta_litres"))["total"] or 0.0, 2),
    }


def geofence_queryset(org, depot=None, params=None):
    params = params or {}
    _, _, day_start, day_end = parse_date_window(params)
    qs = GeofenceEvent.objects.filter(
        vehicle__organisation=org,
        occurred_at__range=(day_start, day_end),
    ).select_related("vehicle", "geofence")
    if depot:
        qs = qs.filter(vehicle__home_depot=depot)
    if params.get("vehicle"):
        qs = qs.filter(vehicle_id=params["vehicle"])
    if params.get("geofence"):
        qs = qs.filter(geofence_id=params["geofence"])
    return qs


def geofence_summary(org, depot=None, params=None):
    qs = geofence_queryset(org, depot=depot, params=params)
    grouped = qs.values("geofence__name").annotate(
        events=Count("id"),
        enters=Count("id", filter=Q(kind=GeofenceEvent.ENTER)),
        exits=Count("id", filter=Q(kind=GeofenceEvent.EXIT)),
    )
    return {"event_count": qs.count(), "top_sites": list(grouped[:10])}


def route_queryset(org, depot=None, params=None):
    params = params or {}
    _, _, day_start, day_end = parse_date_window(params)
    qs = TrackedTrip.objects.filter(vehicle__organisation=org, started_at__range=(day_start, day_end)).select_related("vehicle")
    if depot:
        qs = qs.filter(vehicle__home_depot=depot)
    if params.get("vehicle"):
        qs = qs.filter(vehicle_id=params["vehicle"])
    return qs


def route_detail_rows(trip):
    return list(
        GPSPing.objects.filter(tracked_trip=trip)
        .order_by("device_timestamp")
        .values("device_timestamp", "lat", "lon", "speed_kmh")
    )
