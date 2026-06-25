from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status

from mytrack.tenancy.models import Organisation
from mytrack.vehicles.models import Vehicle, VehicleState
from .models import GPSPing, TrackedTrip, Alert, AlertKind, AlertSeverity, default_severity_for_kind
from .road_speed import resolve_speed_limit_for_ping
from .traccar_events import normalize_traccar_alert_kind


import math
import threading
from datetime import timedelta


def _fire_critical_email(alert):
    """If the alert is CRITICAL and the org has instant notifications on, email in a daemon thread."""
    if alert.severity != AlertSeverity.CRITICAL:
        return
    org = alert.vehicle.organisation
    if getattr(org, "notify_critical_instant", True):
        from mytrack.notifications.emails import send_critical_alert_email
        threading.Thread(target=send_critical_alert_email, args=(alert,), daemon=True).start()
    from mytrack.notifications.whatsapp import notify_driver
    threading.Thread(
        target=notify_driver,
        args=(alert.driver_name, org, alert.get_kind_display(), alert.vehicle.registration, ""),
        kwargs={"vehicle": alert.vehicle},
        daemon=True,
    ).start()


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


_IDLE_RADIUS_KM = 0.05   # 50 m
_IDLE_MINUTES   = 10


def _check_speeding_alert(vehicle, speed_kmh, driver_name, ping_time, posted_limit_kmh):
    if speed_kmh is None:
        return
    grace = float(getattr(vehicle.organisation, "speeding_grace_kmh", 0.0) or 0.0)
    limit = float(posted_limit_kmh)
    if speed_kmh <= limit + grace:
        return
    recent_cutoff = ping_time - timedelta(minutes=5)
    already = Alert.objects.filter(
        vehicle=vehicle, kind=AlertKind.SPEEDING,
        resolved_at__isnull=True, occurred_at__gte=recent_cutoff,
    ).exists()
    if not already:
        Alert.objects.create(
            vehicle=vehicle, kind=AlertKind.SPEEDING,
            severity=default_severity_for_kind(AlertKind.SPEEDING),
            value=speed_kmh, threshold=posted_limit_kmh,
            occurred_at=ping_time, driver_name=driver_name,
        )
        _push_alert_to_outbox(vehicle, AlertKind.SPEEDING, speed_kmh, posted_limit_kmh, ping_time, driver_name)


def _check_idle_alert(vehicle, tracked_trip, lat, lon, driver_name, ping_time):
    if tracked_trip is None or tracked_trip.ended_at is not None:
        return
    if tracked_trip.end_lat is None or tracked_trip.end_lon is None:
        return
    dist_km = _haversine_km(tracked_trip.end_lat, tracked_trip.end_lon, lat, lon)
    if dist_km > _IDLE_RADIUS_KM:
        return
    idle_start = tracked_trip.started_at
    for p in GPSPing.objects.filter(tracked_trip=tracked_trip).exclude(lat__isnull=True).order_by("-received_at")[:50]:
        p_time = p.device_timestamp or p.received_at
        if _haversine_km(tracked_trip.end_lat, tracked_trip.end_lon, p.lat, p.lon) > _IDLE_RADIUS_KM:
            idle_start = p_time
            break
    if (ping_time - idle_start).total_seconds() < _IDLE_MINUTES * 60:
        return
    already = Alert.objects.filter(
        vehicle=vehicle, kind=AlertKind.IDLE,
        resolved_at__isnull=True, occurred_at__gte=tracked_trip.started_at,
    ).exists()
    if not already:
        idle_minutes = (ping_time - idle_start).total_seconds() / 60
        Alert.objects.create(
            vehicle=vehicle, kind=AlertKind.IDLE,
            severity=default_severity_for_kind(AlertKind.IDLE),
            value=round(idle_minutes, 1), threshold=_IDLE_MINUTES,
            occurred_at=ping_time, driver_name=driver_name,
        )
        _push_alert_to_outbox(vehicle, AlertKind.IDLE, round(idle_minutes, 1), _IDLE_MINUTES, ping_time, driver_name)


def _check_traccar_event_alert(vehicle, attributes, driver_name, ping_time):
    """Create safety alerts for non-idle, non-speeding Traccar events."""
    kind = normalize_traccar_alert_kind(attributes)
    if not kind or kind in (AlertKind.SPEEDING, AlertKind.IDLE):
        return

    recent_cutoff = ping_time - timedelta(minutes=3)
    already = Alert.objects.filter(
        vehicle=vehicle,
        kind=kind,
        resolved_at__isnull=True,
        occurred_at__gte=recent_cutoff,
    ).exists()
    if already:
        return

    alert = Alert.objects.create(
        vehicle=vehicle,
        kind=kind,
        severity=default_severity_for_kind(kind),
        value=1.0,
        threshold=0.0,
        occurred_at=ping_time,
        driver_name=driver_name,
    )
    _fire_critical_email(alert)
    if alert.severity == AlertSeverity.CRITICAL:
        try:
            from mytrack.webhooks.dispatch import fire_webhook
            fire_webhook(vehicle.organisation, "alert.critical", {
                "alert_id": alert.pk,
                "kind": kind,
                "vehicle_reg": vehicle.registration,
                "driver": driver_name,
                "occurred_at": str(ping_time),
            })
        except Exception:
            pass
    _push_alert_to_outbox(vehicle, kind, 1.0, 0.0, ping_time, driver_name)


def _push_alert_to_outbox(vehicle, kind, value, threshold, occurred_at, driver_name):
    from mytrack.tracking.models import SyncOutbox
    SyncOutbox.objects.create(
        destination=SyncOutbox.DEST_MYROUTES_SYNC,
        payload={
            "kind": "alert",
            "org_slug": vehicle.organisation.slug,
            "vehicle_reg": vehicle.registration,
            "alert_kind": kind if isinstance(kind, str) else kind.value,
            "value": value,
            "threshold": threshold,
            "occurred_at": occurred_at.isoformat(),
            "driver_name": driver_name or "",
        },
    )


def _end_trip(trip, end_time):
    """Close a trip and queue geocoded start/end labels."""
    if trip.ended_at:
        return
    trip.ended_at = end_time
    trip.save(update_fields=["ended_at"])
    from mytrack.tracking.trip_labels import finalize_trip_labels
    finalize_trip_labels(trip.pk)


def _get_or_create_trip(vehicle, ping_time, lat, lon, driver_name, myroutes_trip_id):
    """Return the open TrackedTrip for this vehicle, or open a new one.

    Closes ALL stale open trips so a vehicle can never accumulate multiple
    active trips (e.g. after a server restart or missed webhook).
    """
    gap = timedelta(minutes=TrackedTrip.GAP_MINUTES)

    def _aware(dt):
        if dt is not None and timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt

    open_trips = list(
        TrackedTrip.objects.filter(vehicle=vehicle, ended_at__isnull=True)
        .order_by("-started_at")
    )

    active_trip = None
    for trip in open_trips:
        if (ping_time - _aware(trip.started_at)) >= timedelta(hours=24):
            _end_trip(trip, _aware(trip.started_at))
            continue
        last_ping = (
            GPSPing.objects.filter(tracked_trip=trip)
            .order_by("-device_timestamp", "-received_at")
            .first()
        )
        last_time = _aware((last_ping.device_timestamp or last_ping.received_at) if last_ping else trip.started_at)
        if ping_time - last_time <= gap:
            if active_trip is None:
                active_trip = trip
            else:
                # Extra open trip — close it
                _end_trip(trip, last_time)
        else:
            _end_trip(trip, last_time)
            try:
                from mytrack.webhooks.dispatch import fire_webhook
                fire_webhook(vehicle.organisation, "trip.ended", {
                    "trip_id": trip.pk,
                    "vehicle_reg": vehicle.registration,
                    "started_at": str(trip.started_at),
                    "ended_at": str(trip.ended_at),
                })
            except Exception:
                pass

    if active_trip:
        return active_trip

    return TrackedTrip.objects.create(
        vehicle=vehicle,
        driver_name=driver_name,
        myroutes_trip_id=myroutes_trip_id,
        started_at=ping_time,
        start_lat=lat,
        start_lon=lon,
        ping_count=0,
    )


_MAX_PLAUSIBLE_KMH = 300.0


def _update_trip_end(trip, lat, lon, speed_kmh):
    # Teleport guard: skip if position jump implies physically impossible speed.
    # Max legit distance between consecutive pings = 300 km/h × GAP_MINUTES.
    if trip.end_lat is not None and trip.end_lon is not None:
        max_dist_km = _MAX_PLAUSIBLE_KMH * TrackedTrip.GAP_MINUTES / 60.0
        if _haversine_km(float(trip.end_lat), float(trip.end_lon), float(lat), float(lon)) > max_dist_km:
            return
    trip.end_lat = lat
    trip.end_lon = lon
    trip.ping_count = (trip.ping_count or 0) + 1
    if speed_kmh is not None:
        trip.max_speed_kmh = max(trip.max_speed_kmh or 0, speed_kmh)
    if trip.start_lat and trip.start_lon:
        trip.distance_km = _haversine_km(trip.start_lat, trip.start_lon, lat, lon)
    trip.save(update_fields=["end_lat", "end_lon", "ping_count", "max_speed_kmh", "distance_km"])


def _check_ingest_token(request):
    expected = settings.INGEST_API_TOKEN
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if auth.startswith("Bearer ") and auth[7:] == expected:
        return True
    return request.GET.get("token", "") == expected


@csrf_exempt
@require_POST
def ingest_ping(request):
    """
    POST /api/ingest/ping/
    Server-to-server endpoint called by myRoutes after every TripLocationView PATCH.
    Auth: Bearer <INGEST_API_TOKEN>

    Body JSON:
        vehicle_reg   str   required
        org_slug      str   required  — maps to Organisation.slug
        lat           float required
        lon           float required
        trip_id       int   optional
        driver_name   str   optional
        speed_kmh     float optional
        heading       float optional
    """
    import json

    if not _check_ingest_token(request):
        from django.http import JsonResponse
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        from django.http import JsonResponse
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    vehicle_reg = data.get("vehicle_reg", "").strip().upper()
    org_slug = data.get("org_slug", "").strip()
    lat = data.get("lat")
    lon = data.get("lon")

    if not vehicle_reg or not org_slug or lat is None or lon is None:
        from django.http import JsonResponse
        return JsonResponse({"detail": "vehicle_reg, org_slug, lat, lon required."}, status=400)

    try:
        org = Organisation.objects.get(slug=org_slug)
    except Organisation.DoesNotExist:
        from django.http import JsonResponse
        return JsonResponse({"detail": "Unknown org_slug."}, status=400)

    vehicle, _ = Vehicle.objects.get_or_create(
        organisation=org,
        registration=vehicle_reg,
        defaults={"label": vehicle_reg},
    )

    now = timezone.now()
    driver_name = data.get("driver_name", "")
    trip_id = data.get("trip_id")
    speed = data.get("speed_kmh")
    heading = data.get("heading")

    device_ts = None
    raw_ts = data.get("timestamp")
    if raw_ts:
        try:
            from django.utils.dateparse import parse_datetime
            device_ts = parse_datetime(raw_ts)
        except (ValueError, TypeError):
            pass

    ping_time = device_ts or now
    tracked_trip = _get_or_create_trip(vehicle, ping_time, lat, lon, driver_name, trip_id)

    posted_limit, road_src = resolve_speed_limit_for_ping(
        vehicle=vehicle, lat=float(lat), lon=float(lon), traccar_attributes=None
    )

    GPSPing.objects.create(
        vehicle=vehicle,
        lat=lat,
        lon=lon,
        speed_kmh=speed,
        heading=heading,
        driver_name=driver_name,
        myroutes_trip_id=trip_id,
        device_timestamp=device_ts,
        tracked_trip=tracked_trip,
        road_speed_limit_kmh=posted_limit,
        road_speed_source=road_src,
    )

    # Update tracked trip end position and stats
    _update_trip_end(tracked_trip, lat, lon, speed)

    from mytrack.geofences.models import check_geofences
    check_geofences(vehicle, lat, lon, driver_name, ping_time)

    _check_speeding_alert(vehicle, speed, driver_name, ping_time, posted_limit)
    _check_idle_alert(vehicle, tracked_trip, lat, lon, driver_name, ping_time)

    # Fuel data (optional) — native myRoutes payload may carry CAN/OBD or probe fields.
    _raw = data.get("fuel_raw_value")
    resolved = _resolve_fuel(
        vehicle,
        level_litres=data.get("fuel_level_litres"),
        level_pct=data.get("fuel_level_pct"),
        raw_value=float(_raw) if _raw is not None else None,
        total_used=data.get("fuel_total_used_litres"),
        rate=data.get("fuel_rate_lph"),
    )
    if resolved is not None:
        _record_fuel(vehicle, resolved, speed, lat, lon, driver_name, ping_time, tracked_trip)

    VehicleState.objects.update_or_create(
        vehicle=vehicle,
        defaults={
            "lat": lat,
            "lon": lon,
            "speed_kmh": speed,
            "heading": heading,
            "driver_name": driver_name,
            "myroutes_trip_id": trip_id,
            "last_seen": now,
        },
    )

    imei = data.get("imei", "").strip()
    if imei:
        _upsert_device(org, imei, vehicle, now)

    _maybe_geocode(vehicle, lat, lon, now)
    _push_to_myroutes(vehicle_reg, org_slug, lat, lon, speed_kmh=speed, heading=heading, timestamp=device_ts)

    from django.http import JsonResponse
    return JsonResponse({"ok": True})


# Teltonika CAN/OBD fuel attributes vary by adapter/firmware. Map the logical fuel
# signals to the candidate attribute keys Traccar surfaces (named or raw ioNN), in
# priority order. Override per-deployment via settings.TELTONIKA_FUEL_IO_MAP.
_DEFAULT_FUEL_IO_MAP = {
    "level_litres": ["fuel1", "fuel_level_litres"],          # already-calibrated litres (CAN/FMS)
    "level_pct":    ["fuel", "fuel1Percent", "fuel_level_pct", "io84", "io89"],
    "total_used_l": ["fuelUsed", "fuel_total_used_litres", "io270"],
    "rate_lph":     ["fuelConsumption", "fuel_rate_lph"],
}


def _fuel_io_map():
    return getattr(settings, "TELTONIKA_FUEL_IO_MAP", None) or _DEFAULT_FUEL_IO_MAP


def _first_attr(attributes, keys):
    """Return the first present, numeric-coercible value among `keys`, else None."""
    for key in keys:
        if key in attributes and attributes[key] is not None:
            try:
                return float(attributes[key])
            except (ValueError, TypeError):
                continue
    return None


def extract_fuel_signals(attributes):
    """Pull the logical fuel signals out of a Traccar/Teltonika attributes dict."""
    io = _fuel_io_map()
    return {
        "level_litres": _first_attr(attributes, io["level_litres"]),
        "level_pct":    _first_attr(attributes, io["level_pct"]),
        "total_used_l": _first_attr(attributes, io["total_used_l"]),
        "rate_lph":     _first_attr(attributes, io["rate_lph"]),
    }


class ResolvedFuel:
    """Outcome of fuel-source resolution for a single ping."""
    __slots__ = ("litres", "source", "pct", "total_used", "rate", "raw")

    def __init__(self, litres, source, pct=None, total_used=None, rate=None, raw=None):
        self.litres = litres
        self.source = source
        self.pct = pct
        self.total_used = total_used
        self.rate = rate
        self.raw = raw


def _resolve_fuel(vehicle, *, level_litres=None, level_pct=None, raw_value=None,
                  total_used=None, rate=None):
    """
    Resolve the best fuel reading for a ping, honouring vehicle.fuel_source_pref.

    Priority (auto):
      1. CAN  — explicit litres, or level_pct × capacity when a CAN counter/rate is present.
      2. OBD  — level_pct × capacity (OEM-linearised), no counter.
      3. PROBE — raw_value run through the TankCalibration strapping table.
      4. EST  — level_pct × capacity legacy fallback.

    Returns a ResolvedFuel, or None when no usable source exists.
    """
    from mytrack.fuel.models import FuelSource
    from mytrack.fuel.calibration import calibrate

    pref = getattr(vehicle, "fuel_source_pref", "auto")
    tank = vehicle.fuel_tank_capacity_litres
    has_ecu = total_used is not None or rate is not None

    def from_pct(source):
        if level_pct is None or not tank:
            return None
        return ResolvedFuel(round(level_pct / 100.0 * tank, 2), source,
                            pct=level_pct, total_used=total_used, rate=rate)

    def from_probe():
        if raw_value is None:
            return None
        calibrated = calibrate(vehicle, raw_value)
        if calibrated is None:
            return None
        return ResolvedFuel(round(calibrated, 2), FuelSource.PROBE, raw=raw_value)

    # Pinned source overrides
    if pref == "can":
        if level_litres is not None:
            return ResolvedFuel(round(float(level_litres), 2), FuelSource.CAN,
                                pct=level_pct, total_used=total_used, rate=rate)
        return from_pct(FuelSource.CAN)
    if pref == "obd":
        return from_pct(FuelSource.OBD)
    if pref == "probe":
        return from_probe()

    # Auto
    if level_litres is not None:
        return ResolvedFuel(round(float(level_litres), 2),
                            FuelSource.CAN if has_ecu else FuelSource.OBD,
                            pct=level_pct, total_used=total_used, rate=rate)
    if has_ecu:
        can = from_pct(FuelSource.CAN)
        if can is not None:
            return can
    probe = from_probe()
    if probe is not None:
        return probe
    obd = from_pct(FuelSource.OBD if level_pct is not None and total_used is None else FuelSource.EST)
    return obd


def _record_fuel(vehicle, resolved, speed_kmh, lat, lon, driver_name, ping_time, tracked_trip):
    from mytrack.fuel.models import FuelReading
    from mytrack.fuel.detection import check_fuel_events
    reading = FuelReading.objects.create(
        vehicle=vehicle,
        fuel_level_litres=resolved.litres,
        source=resolved.source,
        fuel_level_pct=resolved.pct,
        total_fuel_used_litres=resolved.total_used,
        fuel_rate_lph=resolved.rate,
        raw_sensor_value=resolved.raw,
        speed_kmh=speed_kmh,
        lat=lat,
        lon=lon,
        driver_name=driver_name,
        device_timestamp=ping_time,
        tracked_trip=tracked_trip,
    )
    check_fuel_events(vehicle, reading)


def _geocode_address(lat, lon):
    """Return a short street address from Nominatim, or '' on failure."""
    import json
    import urllib.request

    url = (
        f"https://nominatim.openstreetmap.org/reverse"
        f"?lat={lat}&lon={lon}&format=json&zoom=16&addressdetails=1"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "myTrack/1.0 fleet-tracking"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        addr = data.get("address", {})
        road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or ""
        area = (
            addr.get("suburb")
            or addr.get("neighbourhood")
            or addr.get("quarter")
            or addr.get("city")
            or addr.get("town")
            or ""
        )
        parts = [p for p in [road, area] if p]
        return ", ".join(parts) if parts else data.get("display_name", "")[:80]
    except Exception:
        return ""


def _maybe_geocode(vehicle, lat, lon, now):
    """Update VehicleState.last_address if enough time has passed since last geocode."""
    import threading
    from mytrack.vehicles.models import VehicleState

    try:
        state = VehicleState.objects.only("address_updated_at").get(vehicle=vehicle)
    except VehicleState.DoesNotExist:
        return

    if state.address_updated_at:
        if (now - state.address_updated_at).total_seconds() < 60:
            return

    # Mark address_updated_at immediately so concurrent pings don't all fire geocode calls.
    VehicleState.objects.filter(vehicle=vehicle).update(address_updated_at=now)

    vehicle_id = vehicle.pk

    def _do_geocode():
        from django.db import connection as db_conn
        try:
            address = _geocode_address(lat, lon)
            if address:
                VehicleState.objects.filter(vehicle_id=vehicle_id).update(last_address=address)
        finally:
            db_conn.close()

    threading.Thread(target=_do_geocode, daemon=True).start()


def _upsert_device(org, imei, vehicle, now, model_name=""):
    from mytrack.vehicles.models import Device
    from django.db import IntegrityError
    try:
        device, created = Device.objects.get_or_create(
            imei=imei,
            defaults={"organisation": org, "vehicle": vehicle, "model_name": model_name},
        )
    except IntegrityError:
        # Another device already owns this vehicle_id (different IMEI). Just update last_activity.
        Device.objects.filter(vehicle=vehicle).update(last_activity=now)
        return
    update_fields = ["last_activity"]
    device.last_activity = now
    if not created:
        if device.vehicle_id is None and vehicle is not None:
            device.vehicle = vehicle
            update_fields.append("vehicle")
        if model_name and not device.model_name:
            device.model_name = model_name
            update_fields.append("model_name")
    device.save(update_fields=update_fields)


def _push_to_myroutes(vehicle_reg, org_slug, lat, lon, speed_kmh=None, heading=None, timestamp=None):
    """Write a GPS ping to the SyncOutbox for reliable delivery to MyRoutes."""
    from mytrack.tracking.models import SyncOutbox

    sync_url = getattr(__import__("django.conf", fromlist=["settings"]).settings, "MYROUTES_SYNC_URL", "")
    if not sync_url:
        return

    payload = {"org_slug": org_slug, "vehicle_reg": vehicle_reg, "lat": lat, "lon": lon}
    if speed_kmh is not None:
        payload["speed_kmh"] = speed_kmh
    if heading is not None:
        payload["heading"] = heading
    if timestamp is not None:
        payload["timestamp"] = timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp

    SyncOutbox.objects.create(
        destination=SyncOutbox.DEST_MYROUTES_POSITION,
        payload=payload,
    )


@csrf_exempt
def ingest_traccar(request):
    """
    GET or POST /api/ingest/traccar/
    Receives position payloads forwarded by Traccar.
    - POST with forward.json=true: JSON body (Traccar 5 / flat or nested)
    - GET: URL query parameters (Traccar 6 default behaviour)
    Auth: Bearer <INGEST_API_TOKEN> or ?token= query param
    """
    import json
    from django.http import JsonResponse
    from django.utils.dateparse import parse_datetime

    if request.method not in ("GET", "POST"):
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    if not _check_ingest_token(request):
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    # Traccar with forward.json=true sends JSON body regardless of HTTP method.
    # Try JSON body first; fall back to URL query params for plain GET forwarding.
    body_data = None
    if request.body:
        try:
            body_data = json.loads(request.body)
        except (ValueError, TypeError):
            pass

    traccar_position_id = None
    if body_data is not None:
        data = body_data
        if "position" in data and "device" in data:
            pos = data["position"]
            dev = data["device"]
            lat = pos.get("latitude")
            lon = pos.get("longitude")
            vehicle_reg = (dev.get("name") or "").strip().upper()
            speed_knots = pos.get("speed")
            heading = pos.get("course")
            attributes = pos.get("attributes") or {}
            raw_ts = pos.get("fixTime")
            unique_id = (dev.get("uniqueId") or "").strip()
            device_model = ""
            traccar_position_id = data.get("id")
        else:
            lat = data.get("lat") if data.get("lat") is not None else data.get("latitude")
            lon = data.get("lon") if data.get("lon") is not None else data.get("longitude")
            vehicle_reg = (data.get("deviceName") or "").strip().upper()
            speed_knots = data.get("speed")
            heading = data.get("course")
            attributes = data.get("attributes") or {}
            raw_ts = data.get("fixTime")
            unique_id = (data.get("uniqueId") or "").strip()
            device_model = data.get("deviceModel", "")
            traccar_position_id = data.get("id")
    elif request.method == "GET":
        # Plain GET forwarding: position fields arrive as URL query parameters.
        # Traccar template URL must include {latitude}, {longitude}, etc.
        p = request.GET
        try:
            lat = float(p["lat"]) if "lat" in p else float(p["latitude"])
            lon = float(p["lon"]) if "lon" in p else float(p["longitude"])
        except (KeyError, ValueError, TypeError):
            return JsonResponse({"detail": "lat/lon required. Add {latitude}&{longitude} template vars to forward.url in traccar.xml"}, status=400)

        vehicle_reg = (p.get("deviceName") or p.get("name") or "").strip().upper()
        speed_knots_raw = p.get("speed")
        speed_knots = float(speed_knots_raw) if speed_knots_raw else None
        heading_raw = p.get("course")
        heading = float(heading_raw) if heading_raw else None
        raw_ts = p.get("fixTime")
        unique_id = (p.get("uniqueId") or "").strip()
        device_model = p.get("deviceModel", "")
        try:
            attributes = json.loads(p.get("attributes") or "{}")
        except (ValueError, TypeError):
            attributes = {}
        # Allow org_slug as a plain query param (set in traccar.xml forward URL)
        if not attributes.get("org_slug") and p.get("org_slug"):
            attributes["org_slug"] = p["org_slug"]
        # Allow alarm type as a direct query param (add &alarm={alarm} to traccar.xml forward URL)
        if not attributes.get("alarm") and p.get("alarm"):
            attributes["alarm"] = p["alarm"]
    else:
        try:
            data = json.loads(request.body)
        except (ValueError, TypeError):
            return JsonResponse({"detail": "Invalid JSON."}, status=400)

        # Traccar 6 sends nested {"position": {...}, "device": {...}}.
        # Older versions sent flat fields.
        traccar_position_id = data.get("id")
        if "position" in data and "device" in data:
            pos = data["position"]
            dev = data["device"]
            lat = pos.get("latitude")
            lon = pos.get("longitude")
            vehicle_reg = (dev.get("name") or "").strip().upper()
            speed_knots = pos.get("speed")
            heading = pos.get("course")
            attributes = pos.get("attributes") or {}
            raw_ts = pos.get("fixTime")
            unique_id = (dev.get("uniqueId") or "").strip()
            device_model = ""
        else:
            lat = data.get("lat") if data.get("lat") is not None else data.get("latitude")
            lon = data.get("lon") if data.get("lon") is not None else data.get("longitude")
            vehicle_reg = (data.get("deviceName") or "").strip().upper()
            speed_knots = data.get("speed")
            heading = data.get("course")
            attributes = data.get("attributes") or {}
            raw_ts = data.get("fixTime")
            unique_id = (data.get("uniqueId") or "").strip()
            device_model = data.get("deviceModel", "")

    # Traccar 6 POSTs JSON body but also substitutes template vars in the URL.
    # Fall back to URL params for fields the JSON body doesn't include.
    p = request.GET
    if not vehicle_reg:
        vehicle_reg = (p.get("deviceName") or p.get("name") or "").strip().upper()
    if not unique_id:
        unique_id = (p.get("uniqueId") or "").strip()
    if lat is None and p.get("latitude"):
        try:
            lat = float(p["latitude"])
        except (ValueError, TypeError):
            pass
    if lon is None and p.get("longitude"):
        try:
            lon = float(p["longitude"])
        except (ValueError, TypeError):
            pass

    if not vehicle_reg or lat is None or lon is None:
        return JsonResponse({"detail": "deviceName, lat, lon required."}, status=400)

    default_slug = getattr(settings, "TRACCAR_DEFAULT_ORG_SLUG", "")
    org_slug = (attributes.get("org_slug") or p.get("org_slug") or default_slug).strip()
    if not org_slug:
        return JsonResponse({"detail": "Cannot determine org_slug."}, status=400)

    try:
        org = Organisation.objects.get(slug=org_slug)
    except Organisation.DoesNotExist:
        return JsonResponse({"detail": "Unknown org_slug."}, status=400)

    vehicle, _ = Vehicle.objects.get_or_create(
        organisation=org, registration=vehicle_reg, defaults={"label": vehicle_reg}
    )

    now = timezone.now()
    speed_kmh = round(speed_knots * 1.852, 1) if speed_knots is not None else None
    driver_name = attributes.get("driver_name", "")

    device_ts = None
    if raw_ts:
        try:
            device_ts = parse_datetime(str(raw_ts))
        except (ValueError, TypeError):
            pass
        if device_ts is None:
            # Traccar 6 sends fixTime as Unix milliseconds
            try:
                from datetime import datetime, timezone as dt_tz
                device_ts = datetime.fromtimestamp(int(raw_ts) / 1000, tz=dt_tz.utc)
            except (ValueError, TypeError, OSError):
                pass

    ping_time = device_ts or now
    if timezone.is_naive(ping_time):
        ping_time = timezone.make_aware(ping_time)
    tracked_trip = _get_or_create_trip(vehicle, ping_time, lat, lon, driver_name, None)

    posted_limit, road_src = resolve_speed_limit_for_ping(
        vehicle=vehicle, lat=float(lat), lon=float(lon), traccar_attributes=attributes
    )

    GPSPing.objects.create(
        vehicle=vehicle,
        lat=lat,
        lon=lon,
        speed_kmh=speed_kmh,
        heading=heading,
        driver_name=driver_name,
        device_timestamp=device_ts,
        tracked_trip=tracked_trip,
        road_speed_limit_kmh=posted_limit,
        road_speed_source=road_src,
    )

    _update_trip_end(tracked_trip, lat, lon, speed_kmh)

    from mytrack.geofences.models import check_geofences
    check_geofences(vehicle, lat, lon, driver_name, ping_time)

    _check_speeding_alert(vehicle, speed_kmh, driver_name, ping_time, posted_limit)
    _check_idle_alert(vehicle, tracked_trip, lat, lon, driver_name, ping_time)
    _check_traccar_event_alert(vehicle, attributes, driver_name, ping_time)

    # Fuel data — Teltonika CAN/OBD via Traccar attributes, or an analog probe raw value.
    sig = extract_fuel_signals(attributes)
    _raw = attributes.get("fuel_raw_value")
    resolved = _resolve_fuel(
        vehicle,
        level_litres=sig["level_litres"],
        level_pct=sig["level_pct"],
        raw_value=float(_raw) if _raw is not None else None,
        total_used=sig["total_used_l"],
        rate=sig["rate_lph"],
    )
    if resolved is not None:
        _record_fuel(vehicle, resolved, speed_kmh, lat, lon, driver_name, ping_time, tracked_trip)

    VehicleState.objects.update_or_create(
        vehicle=vehicle,
        defaults={
            "lat": lat,
            "lon": lon,
            "speed_kmh": speed_kmh,
            "heading": heading,
            "driver_name": driver_name,
            "myroutes_trip_id": None,
            "last_seen": now,
        },
    )

    if unique_id:
        _upsert_device(org, unique_id, vehicle, now, model_name=device_model)

    _maybe_geocode(vehicle, lat, lon, now)

    try:
        from mytrack.video_telematics.traccar_media import register_clip_from_traccar_attributes

        register_clip_from_traccar_attributes(
            attributes, vehicle, ping_time, tracked_trip, traccar_position_id
        )
    except Exception:
        pass

    _push_to_myroutes(vehicle_reg, org_slug, lat, lon, speed_kmh=speed_kmh, heading=heading, timestamp=device_ts)

    return JsonResponse({"ok": True})
