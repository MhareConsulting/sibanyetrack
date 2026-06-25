import json
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods

from mytrack.compliance.models import InspectionLog
from mytrack.mobile.scope import (
    get_depot_context,
    trips_queryset,
    vehicle_to_dict,
    vehicles_queryset,
)
from mytrack.tracking.models import Alert, DeliveryShare, TrackedTrip, TripClassification
from mytrack.tracking.views import trip_pings_api


def _json_error(message, status=400):
    return JsonResponse({"detail": message}, status=status)


def _alert_counts_by_vehicle(vehicle_ids):
    if not vehicle_ids:
        return {}
    rows = (
        Alert.objects.filter(vehicle_id__in=vehicle_ids, resolved_at__isnull=True)
        .values("vehicle_id")
        .annotate(c=Count("id"))
    )
    return {r["vehicle_id"]: r["c"] for r in rows}


@login_required
@require_GET
def bootstrap(request):
    user = request.user
    org = user.organisation
    active_depot, accessible, is_admin = get_depot_context(request)
    depots = [{"id": d.id, "name": d.name} for d in accessible]
    return JsonResponse({
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "email": user.email,
        },
        "org": {
            "id": org.id if org else None,
            "name": org.name if org else "",
            "slug": org.slug if org else "",
        },
        "active_depot": {"id": active_depot.id, "name": active_depot.name} if active_depot else None,
        "accessible_depots": depots,
        "is_admin": is_admin,
        "speed_limit_kmh": getattr(org, "speed_limit_kmh", 120) if org else 120,
        "csrf_token": _get_csrf_token(request),
    })


def _get_csrf_token(request):
    from django.middleware.csrf import get_token
    return get_token(request)


@login_required
@require_GET
def vehicle_list(request):
    qs = vehicles_queryset(request)
    ids = list(qs.values_list("pk", flat=True))
    alert_map = _alert_counts_by_vehicle(ids)
    rows = [vehicle_to_dict(v, alert_map.get(v.id, 0)) for v in qs]
    return JsonResponse({"vehicles": rows})


@login_required
@require_GET
def vehicle_detail(request, vehicle_id):
    vehicle = get_object_or_404(
        vehicles_queryset(request),
        pk=vehicle_id,
    )
    state = getattr(vehicle, "state", None)
    open_alerts = Alert.objects.filter(vehicle=vehicle, resolved_at__isnull=True)
    critical = open_alerts.filter(severity="critical").count()
    warning = open_alerts.filter(severity="warning").count()

    odometer_km = None
    latest_inspection = (
        InspectionLog.objects.filter(vehicle=vehicle, odometer_km__isnull=False)
        .order_by("-submitted_at")
        .first()
    )
    if latest_inspection:
        odometer_km = round(latest_inspection.odometer_km, 1)
    else:
        total = (
            TrackedTrip.objects.filter(vehicle=vehicle, distance_km__isnull=False)
            .aggregate(s=Sum("distance_km"))["s"]
        )
        if total:
            odometer_km = round(total, 1)

    speed = state.speed_kmh if state else None
    ignition_on = speed is not None and speed >= 3

    data = vehicle_to_dict(vehicle, open_alerts.count())
    data.update({
        "ignition_on": ignition_on,
        "health": {
            "critical_alerts": critical,
            "warning_alerts": warning,
            "status": "critical" if critical else ("warning" if warning else "ok"),
        },
        "odometer_km": odometer_km,
        "battery_v": None,
        "trip_id": state.myroutes_trip_id if state else None,
    })
    return JsonResponse(data)


@login_required
@require_GET
def vehicle_last_trip(request, vehicle_id):
    vehicle = get_object_or_404(vehicles_queryset(request), pk=vehicle_id)
    trip = (
        TrackedTrip.objects.filter(vehicle=vehicle, ended_at__isnull=False)
        .order_by("-ended_at")
        .first()
    )
    if not trip:
        return JsonResponse({"trip": None})
    return JsonResponse({
        "trip": {
            "id": trip.id,
            "started_at": trip.started_at.isoformat(),
            "ended_at": trip.ended_at.isoformat() if trip.ended_at else None,
            "distance_km": trip.distance_km,
        }
    })


@login_required
@require_GET
def trip_list(request):
    qs = trips_queryset(request)
    classification = request.GET.get("classification", "")
    if classification in (TripClassification.PERSONAL, TripClassification.BUSINESS):
        qs = qs.filter(classification=classification)
    vehicle_id = request.GET.get("vehicle", "")
    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
    date_str = request.GET.get("date", "")
    if date_str:
        parsed = parse_date(date_str)
        if parsed:
            day_start = timezone.make_aware(datetime.combine(parsed, datetime.min.time()))
            day_end = timezone.make_aware(datetime.combine(parsed, datetime.max.time()))
            qs = qs.filter(started_at__range=(day_start, day_end))

    page_num = int(request.GET.get("page", 1) or 1)
    paginator = Paginator(qs, 30)
    page = paginator.get_page(page_num)

    trips = []
    for t in page:
        trips.append({
            "id": t.id,
            "vehicle_id": t.vehicle_id,
            "vehicle_reg": t.vehicle.registration,
            "driver_name": t.driver_name or "",
            "started_at": t.started_at.isoformat(),
            "ended_at": t.ended_at.isoformat() if t.ended_at else None,
            "distance_km": round(t.distance_km, 1) if t.distance_km else None,
            "classification": t.classification,
            "start_label": t.start_label or _fallback_coord_label(t.start_lat, t.start_lon),
            "end_label": t.end_label or _fallback_coord_label(t.end_lat, t.end_lon) if t.end_lat else "",
            "active": t.ended_at is None,
        })

    return JsonResponse({
        "trips": trips,
        "page": page.number,
        "total_pages": paginator.num_pages,
        "has_next": page.has_next(),
    })


def _fallback_coord_label(lat, lon):
    if lat is None or lon is None:
        return ""
    return f"Near {lat:.4f}, {lon:.4f}"


@login_required
@require_http_methods(["GET", "PATCH"])
def trip_classification(request, trip_id):
    trip = get_object_or_404(
        trips_queryset(request),
        pk=trip_id,
    )
    if request.method == "GET":
        return JsonResponse({"classification": trip.classification})

    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_error("Invalid JSON")
    value = body.get("classification", "")
    if value not in (TripClassification.PERSONAL, TripClassification.BUSINESS):
        return _json_error("classification must be personal or business")
    trip.classification = value
    trip.save(update_fields=["classification"])
    return JsonResponse({"id": trip.id, "classification": trip.classification})


@login_required
@require_GET
def trip_replay(request, trip_id):
    return trip_pings_api(request, trip_id)


@login_required
@require_http_methods(["POST"])
def share_location(request):
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_error("Invalid JSON")

    vehicle_id = body.get("vehicle_id")
    if not vehicle_id:
        return _json_error("vehicle_id required")

    vehicle = get_object_or_404(vehicles_queryset(request), pk=vehicle_id)
    hours = int(body.get("expires_hours", 8))
    email = request.user.email or f"dispatcher+{request.user.username}@mytrack.local"

    share = DeliveryShare.objects.create(
        vehicle=vehicle,
        customer_name=body.get("customer_name", request.user.get_full_name() or request.user.username),
        customer_email=email,
        note=body.get("note", "Shared location"),
        expires_at=timezone.now() + timedelta(hours=hours),
        created_by=request.user,
        destination_address=body.get("destination_address", ""),
    )
    return JsonResponse({
        "url": share.get_public_url(),
        "token": str(share.token),
        "expires_at": share.expires_at.isoformat(),
    })


@login_required
@require_GET
def insights(request):
    org = request.user.organisation
    if not org:
        return JsonResponse({"insights": {}})

    today = timezone.localdate()
    day_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    vehicle_ids = list(vehicles_queryset(request).values_list("pk", flat=True))

    trips_today = TrackedTrip.objects.filter(
        vehicle_id__in=vehicle_ids,
        started_at__gte=day_start,
    ).count()

    open_alerts = Alert.objects.filter(
        vehicle_id__in=vehicle_ids,
        resolved_at__isnull=True,
    ).count()

    stale_threshold = timezone.now() - timedelta(minutes=15)
    offline = 0
    for v in vehicles_queryset(request).select_related("state"):
        s = getattr(v, "state", None)
        if not s or not s.last_seen or s.last_seen < stale_threshold:
            offline += 1

    return JsonResponse({
        "insights": {
            "trips_today": trips_today,
            "open_alerts": open_alerts,
            "vehicles_offline": offline,
            "vehicles_total": len(vehicle_ids),
        }
    })
