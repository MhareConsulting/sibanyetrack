"""
Push driver/vehicle/depot changes from myTrack to the myRoutes sync endpoint.
Uses SyncOutbox for reliable, retryable delivery — no longer fire-and-forget.
"""

from django.conf import settings


def _push_to_myroutes(payload: dict) -> None:
    """Write a sync payload to the outbox. The cron flush endpoint delivers it."""
    if not getattr(settings, "MYROUTES_SYNC_URL", ""):
        return
    from mytrack.tracking.models import SyncOutbox
    SyncOutbox.objects.create(
        destination=SyncOutbox.DEST_MYROUTES_SYNC,
        payload=payload,
    )


def push_vehicle(vehicle) -> None:
    _push_to_myroutes({
        "kind": "vehicle",
        "action": "upsert",
        "mytrack_id": vehicle.pk,
        "org_slug": vehicle.organisation.slug,
        "registration": vehicle.registration,
        "is_active": vehicle.is_active,
    })


def delete_vehicle(mytrack_id: int, org_slug: str) -> None:
    _push_to_myroutes({
        "kind": "vehicle",
        "action": "delete",
        "mytrack_id": mytrack_id,
        "org_slug": org_slug,
    })


def push_driver(driver) -> None:
    _push_to_myroutes({
        "kind": "driver",
        "action": "upsert",
        "mytrack_id": driver.pk,
        "org_slug": driver.organisation.slug,
        "full_name": driver.full_name,
        "phone_e164": driver.phone_e164 or "",
        "licence_code": driver.licence_code or "",
        "is_active": driver.is_active,
    })


def push_depot(depot) -> None:
    _push_to_myroutes({
        "kind": "depot",
        "action": "upsert",
        "mytrack_id": depot.pk,
        "org_slug": depot.organisation.slug,
        "name": depot.name,
        "address": depot.address,
        "lat": depot.lat,
        "lon": depot.lon,
        "open_time": depot.open_time.strftime("%H:%M") if depot.open_time else None,
        "close_time": depot.close_time.strftime("%H:%M") if depot.close_time else None,
        "is_active": depot.is_active,
    })


def delete_depot(mytrack_id: int, org_slug: str) -> None:
    _push_to_myroutes({
        "kind": "depot",
        "action": "delete",
        "mytrack_id": mytrack_id,
        "org_slug": org_slug,
    })
