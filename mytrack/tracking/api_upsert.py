"""
REST upsert endpoints called by myRoutes to push existing vehicle/driver/depot data into myTrack.
POST /api/vehicles/upsert/
POST /api/drivers/upsert/
POST /api/depots/upsert/
Auth: Bearer <INGEST_API_TOKEN>
"""
import json
from datetime import time as time_type

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from mytrack.tenancy.models import Depot, Organisation
from mytrack.vehicles.models import Vehicle
from mytrack.drivers.models import Driver
from .ingest import _check_ingest_token


@csrf_exempt
@require_POST
def upsert_vehicle(request):
    if not _check_ingest_token(request):
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    org_slug = (data.get("org_slug") or "").strip()
    registration = (data.get("registration") or "").strip().upper()
    if not org_slug or not registration:
        return JsonResponse({"detail": "org_slug and registration required."}, status=400)

    org_name = (data.get("org_name") or org_slug).strip()
    org, _ = Organisation.objects.get_or_create(slug=org_slug, defaults={"name": org_name})

    vehicle, created = Vehicle.objects.update_or_create(
        organisation=org,
        registration=registration,
        defaults={
            "label": data.get("label") or registration,
            "is_active": data.get("is_active", True),
        },
    )
    return JsonResponse({"id": vehicle.pk, "created": created})


@csrf_exempt
@require_POST
def upsert_driver(request):
    if not _check_ingest_token(request):
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    org_slug = (data.get("org_slug") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    if not org_slug or not full_name:
        return JsonResponse({"detail": "org_slug and full_name required."}, status=400)

    org_name = (data.get("org_name") or org_slug).strip()
    org, _ = Organisation.objects.get_or_create(slug=org_slug, defaults={"name": org_name})

    phone = (data.get("phone_e164") or "").strip()

    # Match on phone if provided (more reliable than name), else name
    lookup = {"organisation": org, "phone_e164": phone} if phone else {"organisation": org, "full_name": full_name}

    driver, created = Driver.objects.update_or_create(
        **lookup,
        defaults={
            "full_name": full_name,
            "phone_e164": phone,
            "licence_code": data.get("licence_code") or "",
            "is_active": data.get("is_active", True),
        },
    )
    return JsonResponse({"id": driver.pk, "created": created})


@csrf_exempt
@require_POST
def upsert_depot(request):
    """Receive a depot upsert pushed by MyRoutes so myTrack mirrors it."""
    if not _check_ingest_token(request):
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    org_slug = (data.get("org_slug") or "").strip()
    name = (data.get("name") or "").strip()
    if not org_slug or not name:
        return JsonResponse({"detail": "org_slug and name required."}, status=400)

    org, _ = Organisation.objects.get_or_create(slug=org_slug, defaults={"name": org_slug})

    def _parse_time(val):
        if not val:
            return None
        try:
            h, m = val.split(":")
            return time_type(int(h), int(m))
        except (ValueError, AttributeError):
            return None

    depot, created = Depot.objects.update_or_create(
        organisation=org,
        name=name,
        defaults={
            "address": data.get("address") or "",
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "open_time": _parse_time(data.get("open_time")),
            "close_time": _parse_time(data.get("close_time")),
            "is_active": data.get("is_active", True),
        },
    )

    # If MyRoutes sent its own PK, write it back via the existing sync endpoint
    # so MyRoutes.Depot.mytrack_id gets populated.
    myroutes_id = data.get("myroutes_id")
    if myroutes_id and created:
        from mytrack.tracking.sync import push_depot
        push_depot(depot)

    return JsonResponse({"id": depot.pk, "created": created})
