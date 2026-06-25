import json
import math
import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from mytrack.vehicles.models import Vehicle, VehicleState
from .models import GPSPing, TrackedTrip, Alert, AlertKind


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _filter_outlier_pings(pings):
    """Remove pings that imply motion faster than any vehicle can achieve."""
    MAX_KMH = 300.0
    from datetime import datetime, timezone as dt_tz
    filtered = []
    prev = None
    for p in pings:
        if prev is None or not prev["ts"] or not p["ts"]:
            filtered.append(p)
            prev = p
            continue
        try:
            t0 = datetime.fromisoformat(prev["ts"]).replace(tzinfo=dt_tz.utc)
            t1 = datetime.fromisoformat(p["ts"]).replace(tzinfo=dt_tz.utc)
            dt_h = (t1 - t0).total_seconds() / 3600.0
            if dt_h > 0:
                dist = _haversine_km(float(prev["lat"]), float(prev["lon"]), float(p["lat"]), float(p["lon"]))
                if dist / dt_h > MAX_KMH:
                    continue
        except Exception:
            pass
        filtered.append(p)
        prev = p
    return filtered


def _downsample(pings, n):
    if len(pings) <= n:
        return pings
    step = len(pings) / n
    return [pings[int(i * step)] for i in range(n)]


def _snap_pings_to_roads(pings):
    """Call OSRM map-matching; return road-snapped [[lon, lat]] or None on failure."""
    import urllib.request
    if len(pings) < 2:
        return None
    sample = _downsample(pings, 100)
    coords = ";".join(f"{p['lon']},{p['lat']}" for p in sample)
    radiuses = ";".join("50" for _ in sample)
    base = getattr(settings, "OSRM_BASE_URL", "https://router.project-osrm.org")
    url = f"{base}/match/v1/driving/{coords}?overview=full&geometries=geojson&radiuses={radiuses}"
    req = urllib.request.Request(url, headers={"User-Agent": "myTrack/1.0 fleet-tracking"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        if data.get("code") == "Ok" and data.get("matchings"):
            return data["matchings"][0]["geometry"]["coordinates"]
    except Exception:
        pass
    return None


@login_required
def dashboard(request):
    speed_limit = getattr(request.user.organisation, "speed_limit_kmh", 120)
    return render(request, "tracking/dashboard.html", {"speed_limit_kmh": speed_limit})


@login_required
@require_GET
def live_stream(request):
    """SSE endpoint — pushes all vehicle positions every 3 seconds."""
    org = request.user.organisation

    def event_stream():
        from mytrack.drivers.models import Driver
        from mytrack.mobile.scope import vehicles_queryset
        cycle = 0
        while True:
            # Heartbeat every 15 s to prevent nginx proxy_read_timeout from closing the connection.
            cycle += 1
            if cycle % 5 == 0:
                yield ": heartbeat\n\n"

            try:
                vehicles = (
                    vehicles_queryset(request)
                    .prefetch_related("state")
                    .order_by("registration")
                )
                vehicle_ids = [v.id for v in vehicles]
                assigned = {
                    d.default_vehicle_id: d.full_name
                    for d in Driver.objects.filter(
                        organisation=org, default_vehicle_id__in=vehicle_ids, is_active=True
                    ).only("full_name", "default_vehicle_id")
                }
                rows = []
                from mytrack.mobile.scope import is_parked

                for v in vehicles:
                    s = getattr(v, "state", None)
                    driver = (s.driver_name if s else "") or assigned.get(v.id, "")
                    speed = s.speed_kmh if s else None
                    last_seen = s.last_seen if s else None
                    last_address = s.last_address if s else ""
                    reg = v.registration
                    rows.append({
                        "id": v.id,
                        "reg": reg,
                        "registration": reg,
                        "label": v.label or reg,
                        "lat": s.lat if s else None,
                        "lon": s.lon if s else None,
                        "speed_kmh": speed,
                        "heading": s.heading if s else None,
                        "driver": driver,
                        "trip_id": s.myroutes_trip_id if s else None,
                        "last_seen": last_seen.isoformat() if last_seen else None,
                        "address": last_address,
                        "last_address": last_address,
                        "parked": is_parked(speed, last_seen),
                    })
                payload = json.dumps(rows)
                yield f"data: {payload}\n\n"
            except Exception:
                yield ": error-retry\n\n"

            time.sleep(3)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
@require_GET
def alert_stream(request):
    """Lightweight SSE endpoint — pushes new alerts and unresolved count every 10 seconds."""
    org = request.user.organisation

    def event_stream():
        last_alert_id = (
            Alert.objects.filter(vehicle__organisation=org)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        ) or 0

        while True:
            time.sleep(10)
            new_qs = (
                Alert.objects.filter(vehicle__organisation=org, id__gt=last_alert_id)
                .select_related("vehicle")
                .order_by("id")
            )
            new_alerts = []
            for a in new_qs:
                new_alerts.append({
                    "id": a.id,
                    "kind": a.kind,
                    "severity": a.severity,
                    "vehicle_reg": a.vehicle.registration,
                    "driver_name": a.driver_name,
                    "value": a.value,
                    "threshold": a.threshold,
                    "occurred_at": a.occurred_at.isoformat(),
                })
                last_alert_id = a.id

            unresolved_count = Alert.objects.filter(
                vehicle__organisation=org, resolved_at__isnull=True
            ).count()

            payload = json.dumps({
                "new_alerts": new_alerts,
                "unresolved_count": unresolved_count,
            })
            yield f"event: alerts\ndata: {payload}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
@require_GET
def vehicle_trips_api(request, vehicle_id):
    """Return trips for a vehicle, optionally filtered by date range."""
    from mytrack.vehicles.models import Vehicle
    vehicle = get_object_or_404(Vehicle, pk=vehicle_id, organisation=request.user.organisation)
    qs = TrackedTrip.objects.filter(vehicle=vehicle)

    start = request.GET.get("start")
    end = request.GET.get("end")
    if start:
        qs = qs.filter(started_at__gte=start)
    if end:
        qs = qs.filter(started_at__lte=end)

    trips = qs.order_by("started_at")[:100]
    results = []
    for t in trips:
        results.append(
            {
                "id": t.id,
                "start": t.started_at.isoformat(),
                "stop": t.ended_at.isoformat() if t.ended_at else None,
                "dist_km": round(t.distance_km, 1) if t.distance_km else None,
                "driver": t.driver_name,
            }
        )
    return JsonResponse({"vehicle_id": vehicle_id, "trips": results})


@require_GET
def vehicle_trail_api(request):
    """
    GET /api/tracking/trail/?registration=<reg>&org_slug=<slug>&since=<iso>
    Returns the GPS trail for a vehicle since a given timestamp.
    Auth: Bearer INGEST_API_TOKEN  (server-to-server, no login required)
    """
    from django.conf import settings
    from mytrack.vehicles.models import Vehicle

    auth = request.META.get("HTTP_AUTHORIZATION", "")
    expected = getattr(settings, "INGEST_API_TOKEN", "")
    if not expected or auth != f"Bearer {expected}":
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    registration = request.GET.get("registration", "").strip().upper()
    org_slug = request.GET.get("org_slug", "").strip()
    since_str = request.GET.get("since", "")

    vehicle = Vehicle.objects.filter(
        registration=registration, organisation__slug=org_slug
    ).first()
    if not vehicle:
        return JsonResponse({"trail": []})

    from django.utils.dateparse import parse_datetime
    since = parse_datetime(since_str) if since_str else None

    qs = GPSPing.objects.filter(vehicle=vehicle).exclude(lat__isnull=True)
    if since:
        qs = qs.filter(received_at__gte=since)
    qs = qs.order_by("received_at")[:500]

    trail = []
    for p in qs.values("lat", "lon", "speed_kmh", "heading", "device_timestamp", "received_at"):
        ts = p["device_timestamp"] or p["received_at"]
        trail.append({
            "lat": p["lat"], "lon": p["lon"],
            "speed_kmh": p["speed_kmh"], "heading": p["heading"],
            "ts": ts.isoformat() if ts else None,
        })
    return JsonResponse({"trail": trail})


@login_required
@require_GET
def trip_pings_api(request, trip_id):
    trip = get_object_or_404(TrackedTrip, pk=trip_id, vehicle__organisation=request.user.organisation)
    pings = (
        GPSPing.objects
        .filter(tracked_trip=trip)
        .exclude(lat__isnull=True)
        .order_by("device_timestamp", "received_at")
        .values("lat", "lon", "speed_kmh", "heading", "device_timestamp", "received_at",
                "road_speed_limit_kmh")
    )
    results = []
    for p in pings:
        ts = p["device_timestamp"] or p["received_at"]
        results.append({
            "lat": p["lat"], "lon": p["lon"],
            "speed_kmh": p["speed_kmh"], "heading": p["heading"],
            "road_speed_limit_kmh": p["road_speed_limit_kmh"],
            "ts": ts.isoformat() if ts else None,
        })
    results = _filter_outlier_pings(results)
    snapped_coords = None
    if request.GET.get("snap") == "roads":
        snapped_coords = _snap_pings_to_roads(results)
    return JsonResponse({"trip_id": trip_id, "pings": results, "snapped_coords": snapped_coords})


@login_required
@require_GET
def trip_alerts_api(request, trip_id):
    trip = get_object_or_404(TrackedTrip, pk=trip_id, vehicle__organisation=request.user.organisation)
    qs = Alert.objects.filter(
        vehicle=trip.vehicle,
        occurred_at__gte=trip.started_at,
        occurred_at__lte=trip.ended_at or timezone.now(),
    ).values("kind", "severity", "value", "threshold", "occurred_at")
    alerts = [
        {**a, "occurred_at": a["occurred_at"].isoformat()}
        for a in qs
    ]
    return JsonResponse({"alerts": alerts})
