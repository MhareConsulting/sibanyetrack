import json
import os
import urllib.request
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def poll_traccar_alarms() -> dict:
    """Poll Traccar REST API for recent alarm events and create myTrack Alerts."""
    traccar_url = (os.environ.get("TRACCAR_INTERNAL_URL") or "http://mytrack-traccar:8082").rstrip("/")
    traccar_user = os.environ.get("TRACCAR_ADMIN_USER", "")
    traccar_pass = os.environ.get("TRACCAR_ADMIN_PASSWORD", "")

    if not traccar_user or not traccar_pass:
        return {"error": "TRACCAR_ADMIN_USER/PASSWORD not configured"}

    now = timezone.now()
    since = now - timedelta(minutes=3)

    # Traccar 6 uses session cookies — POST to /api/session to authenticate
    try:
        login_data = urllib.parse.urlencode({"email": traccar_user, "password": traccar_pass}).encode()
        login_req = urllib.request.Request(f"{traccar_url}/api/session", data=login_data)
        login_req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(login_req, timeout=10) as resp:
            session_cookie = resp.headers.get("Set-Cookie", "").split(";")[0]
    except Exception as exc:
        return {"error": f"Failed to authenticate with Traccar: {exc}"}

    headers = {"Cookie": session_cookie, "Accept": "application/json"}

    # Fetch devices first — needed as deviceId params in the events query
    try:
        req_dev = urllib.request.Request(f"{traccar_url}/api/devices", headers=headers)
        with urllib.request.urlopen(req_dev, timeout=10) as resp:
            devices = {d["id"]: d for d in json.loads(resp.read())}
    except Exception as exc:
        return {"error": f"Failed to fetch devices: {exc}"}

    if not devices:
        return {"events_checked": 0, "alerts_created": 0}

    # Traccar requires at least one deviceId in the events query
    device_params = "&".join(f"deviceId={did}" for did in devices)
    params = urllib.parse.urlencode({
        "from": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "alarm",
    })
    try:
        req = urllib.request.Request(f"{traccar_url}/api/reports/events?{device_params}&{params}", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            events = json.loads(resp.read())
    except Exception as exc:
        return {"error": f"Failed to fetch events: {exc}"}

    if not events:
        return {"events_checked": 0, "alerts_created": 0}

    from mytrack.tenancy.models import Organisation
    from mytrack.vehicles.models import Vehicle
    from mytrack.tracking.models import Alert, AlertKind, default_severity_for_kind
    from mytrack.tracking.traccar_events import normalize_traccar_alert_kind

    default_slug = (os.environ.get("TRACCAR_DEFAULT_ORG_SLUG") or getattr(settings, "TRACCAR_DEFAULT_ORG_SLUG", "") or "").strip()
    try:
        org = Organisation.objects.get(slug=default_slug)
    except Organisation.DoesNotExist:
        return {"error": f"Organisation '{default_slug}' not found"}

    created = 0
    for event in events:
        attributes = event.get("attributes") or {}
        alarm_kind = normalize_traccar_alert_kind(attributes)
        if not alarm_kind or alarm_kind in (AlertKind.SPEEDING, AlertKind.IDLE):
            continue

        device = devices.get(event.get("deviceId"))
        if not device:
            continue

        vehicle_name = (device.get("name") or "").strip().upper()
        try:
            vehicle = Vehicle.objects.get(organisation=org, registration=vehicle_name)
        except Vehicle.DoesNotExist:
            continue

        event_time_str = event.get("eventTime") or event.get("serverTime")
        occurred_at = parse_datetime(event_time_str) if event_time_str else None
        if occurred_at is None:
            occurred_at = now
        if timezone.is_naive(occurred_at):
            occurred_at = timezone.make_aware(occurred_at)

        # Deduplicate: skip if same vehicle+kind exists within ±3 min of this event
        if Alert.objects.filter(
            vehicle=vehicle,
            kind=alarm_kind,
            occurred_at__gte=occurred_at - timedelta(minutes=3),
            occurred_at__lte=occurred_at + timedelta(minutes=3),
        ).exists():
            continue

        Alert.objects.create(
            vehicle=vehicle,
            kind=alarm_kind,
            severity=default_severity_for_kind(alarm_kind),
            value=0,
            threshold=0,
            occurred_at=occurred_at,
        )
        created += 1

    return {"events_checked": len(events), "alerts_created": created}
