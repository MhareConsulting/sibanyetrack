"""
Streamax AD Plus 2.0 HTTP event-push adapter.

Configure the camera's "alarm push" to POST to:
  POST /api/video/streamax/event/
with the push password set to the value of STREAMAX_WEBHOOK_TOKEN in settings.

The device sends one JSON body per event. Each element of fileList becomes a
separate VideoAsset so that front-cam and in-cab clips are stored individually.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from mytrack.vehicles.models import Device, Vehicle
from mytrack.video_telematics.ingest_api import _create_asset
from mytrack.video_telematics.models import IngestSource, VideoTrigger

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Streamax alarm-type → VideoTrigger mapping                                 #
# --------------------------------------------------------------------------- #

# Streamax sends alarmType as a string (name) or integer code depending on
# firmware version. Both are handled below.
_ALARM_TYPE_MAP: dict[str, str] = {
    # String names (AD Plus 2.0 HTTP push)
    "HARSH_BRAKING":       VideoTrigger.HARSH_BRAKING,
    "HARD_BRAKING":        VideoTrigger.HARSH_BRAKING,
    "HARSH_ACCELERATION":  VideoTrigger.HARSH_ACCEL,
    "HARD_ACCELERATION":   VideoTrigger.HARSH_ACCEL,
    "HARSH_ACCEL":         VideoTrigger.HARSH_ACCEL,
    "SPEEDING":            VideoTrigger.SPEEDING,
    "OVERSPEED":           VideoTrigger.SPEEDING,
    "LANE_DEPARTURE":      VideoTrigger.LANE_DEPARTURE,
    "LDWS":                VideoTrigger.LANE_DEPARTURE,
    "FATIGUE":             VideoTrigger.FATIGUE,
    "DROWSY":              VideoTrigger.FATIGUE,
    "DRIVER_FATIGUE":      VideoTrigger.FATIGUE,
    "PHONE":               VideoTrigger.PHONE_USE,
    "PHONE_USE":           VideoTrigger.PHONE_USE,
    "PHONE_DISTRACTION":   VideoTrigger.PHONE_USE,
    "SEATBELT":            VideoTrigger.SEATBELT,
    "NO_SEATBELT":         VideoTrigger.SEATBELT,
    # Numeric codes (older firmware)
    "1":  VideoTrigger.HARSH_BRAKING,
    "2":  VideoTrigger.HARSH_ACCEL,
    "3":  VideoTrigger.SPEEDING,
    "4":  VideoTrigger.LANE_DEPARTURE,
    "5":  VideoTrigger.FATIGUE,
    "6":  VideoTrigger.PHONE_USE,
    "7":  VideoTrigger.SEATBELT,
}


def _map_trigger(alarm_type) -> str:
    if alarm_type is None:
        return VideoTrigger.HARSH_EVENT
    key = str(alarm_type).upper().strip()
    return _ALARM_TYPE_MAP.get(key, VideoTrigger.HARSH_EVENT)


# --------------------------------------------------------------------------- #
#  Auth                                                                        #
# --------------------------------------------------------------------------- #

def _check_streamax_token(request, body: dict) -> bool:
    expected = getattr(settings, "STREAMAX_WEBHOOK_TOKEN", "") or ""
    if not expected:
        # No token configured → open (dev / local only). Warn loudly.
        log.warning("STREAMAX_WEBHOOK_TOKEN not set; accepting all Streamax pushes.")
        return True
    # Accept token from Authorization header OR from body field "token"
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == expected:
        return True
    if str(body.get("token") or "").strip() == expected:
        return True
    return False


# --------------------------------------------------------------------------- #
#  Vehicle resolution                                                          #
# --------------------------------------------------------------------------- #

def _find_vehicle(body: dict) -> Vehicle | None:
    # 1. Look up by IMEI via Device → Vehicle link
    device_id = str(body.get("deviceId") or body.get("device_id") or "").strip()
    if device_id:
        device = (
            Device.objects.filter(imei=device_id)
            .select_related("vehicle__organisation")
            .first()
        )
        if device and device.vehicle_id:
            return device.vehicle

    # 2. Fall back to vehicleNo as registration (org-ambiguous; use first match)
    vehicle_no = str(body.get("vehicleNo") or body.get("vehicle_no") or "").strip().upper()
    if vehicle_no:
        return (
            Vehicle.objects.filter(registration__iexact=vehicle_no)
            .select_related("organisation")
            .first()
        )

    return None


# --------------------------------------------------------------------------- #
#  Datetime parsing                                                            #
# --------------------------------------------------------------------------- #

_DT_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
]


def _parse_streamax_dt(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        # Unix timestamp (seconds)
        try:
            return datetime.fromtimestamp(raw, tz=dt_timezone.utc)
        except (OSError, ValueError):
            return None
    s = str(raw).strip()
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=dt_timezone.utc)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
#  Endpoint                                                                    #
# --------------------------------------------------------------------------- #

@csrf_exempt
@require_POST
def streamax_event_push(request):
    """
    Receive Streamax AD Plus 2.0 alarm-push events.

    Creates one VideoAsset per file in the event's fileList, storing the
    Streamax-hosted clip URL as playback_url (Phase 1).
    """
    try:
        body = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    if not _check_streamax_token(request, body):
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    vehicle = _find_vehicle(body)
    if not vehicle:
        device_id = body.get("deviceId") or body.get("device_id")
        log.warning("Streamax push: unknown vehicle (deviceId=%s)", device_id)
        return JsonResponse({"detail": "Unknown vehicle."}, status=400)

    trigger = _map_trigger(body.get("alarmType") or body.get("alarm_type"))
    occurred_at = _parse_streamax_dt(body.get("alarmTime") or body.get("alarm_time"))

    file_list = body.get("fileList") or body.get("file_list") or []
    if not file_list:
        # Event with no clip yet — acknowledge but create nothing
        log.info("Streamax push for %s: no files, acknowledging.", vehicle)
        return JsonResponse({"ok": True, "assets_created": 0})

    created_ids = []
    for idx, file_entry in enumerate(file_list):
        playback_url = str(file_entry.get("fileUrl") or file_entry.get("file_url") or "").strip()
        if not playback_url:
            continue

        channel_num = file_entry.get("channel", idx)
        duration = file_entry.get("duration") or file_entry.get("fileDuration")
        size = file_entry.get("fileSize") or file_entry.get("file_size")

        # external_id: deviceId + alarmTime + channel — deduplicates re-deliveries
        device_id = str(body.get("deviceId") or body.get("device_id") or "")
        alarm_time_raw = str(body.get("alarmTime") or body.get("alarm_time") or "")
        external_id = f"streamax:{device_id}:{alarm_time_raw}:ch{channel_num}"

        try:
            asset, created = _create_asset(
                vehicle=vehicle,
                occurred_at=occurred_at,
                trigger_type=trigger,
                ingest_source=IngestSource.STREAMAX,
                external_id=external_id,
                playback_url=playback_url,
                duration_seconds=int(duration) if duration is not None else None,
                size_bytes=int(size) if size is not None else None,
                provider_payload={
                    "source": "streamax",
                    "raw_event": body,
                    "file_entry": file_entry,
                },
            )
            if created:
                created_ids.append(asset.pk)
        except Exception:
            log.exception("Streamax push: failed to create asset for %s ch%s", vehicle, channel_num)

    return JsonResponse({"ok": True, "assets_created": len(created_ids), "ids": created_ids})
