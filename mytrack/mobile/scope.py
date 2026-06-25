"""Depot-scoped vehicle and trip query helpers for the mobile dispatcher app."""

from django.db.models import Q
from django.utils import timezone

from mytrack.tenancy.mixins import SESSION_KEY
from mytrack.tenancy.models import Depot, Role
from mytrack.tracking.models import TrackedTrip
from mytrack.vehicles.models import Vehicle


def get_depot_context(request):
    """
    Returns (active_depot, accessible_depots, is_admin).
    Mirrors intelligence.views._depot_context session rules.
    """
    user = request.user
    is_admin = user.role == Role.ADMIN or user.is_superuser
    accessible = user.accessible_depots()

    session_val = request.session.get(SESSION_KEY)
    if session_val is None or (session_val == "all" and not is_admin):
        active_depot = accessible.first() if not is_admin else None
    elif session_val == "all":
        active_depot = None
    else:
        try:
            active_depot = accessible.get(pk=session_val)
        except (Depot.DoesNotExist, ValueError, TypeError):
            active_depot = accessible.first()

    return active_depot, accessible, is_admin


def vehicles_queryset(request):
    """Vehicles visible to the current user (org + depot scope)."""
    org = request.user.organisation
    if not org:
        return Vehicle.objects.none()

    active_depot, accessible, is_admin = get_depot_context(request)
    qs = Vehicle.objects.filter(organisation=org, is_active=True)

    if is_admin and request.session.get(SESSION_KEY) == "all":
        pass
    else:
        qs = qs.filter(Q(home_depot__in=accessible) | Q(home_depot__isnull=True))

    if active_depot:
        qs = qs.filter(home_depot=active_depot)

    return qs.select_related("state", "home_depot", "device")


def trips_queryset(request):
    """Tracked trips for vehicles in scope."""
    org = request.user.organisation
    if not org:
        return TrackedTrip.objects.none()

    active_depot, _, _ = get_depot_context(request)
    vehicle_ids = vehicles_queryset(request).values_list("pk", flat=True)
    qs = (
        TrackedTrip.objects.filter(vehicle_id__in=vehicle_ids)
        .select_related("vehicle")
        .order_by("-started_at")
    )
    return qs


def is_parked(speed_kmh, last_seen):
    """True when vehicle appears stationary (P marker on map)."""
    if last_seen is None:
        return False
    if (timezone.now() - last_seen).total_seconds() > 900:
        return False
    return speed_kmh is None or speed_kmh < 3


def vehicle_to_dict(vehicle, open_alert_count=0):
    state = getattr(vehicle, "state", None)
    speed = state.speed_kmh if state else None
    last_seen = state.last_seen if state else None
    return {
        "id": vehicle.id,
        "registration": vehicle.registration,
        "label": vehicle.label or vehicle.registration,
        "lat": state.lat if state else None,
        "lon": state.lon if state else None,
        "speed_kmh": speed,
        "heading": state.heading if state else None,
        "driver": state.driver_name if state else "",
        "last_seen": last_seen.isoformat() if last_seen else None,
        "last_address": state.last_address if state else "",
        "parked": is_parked(speed, last_seen),
        "open_alert_count": open_alert_count,
        "home_depot_id": vehicle.home_depot_id,
        "home_depot_name": vehicle.home_depot.name if vehicle.home_depot else None,
    }
