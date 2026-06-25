"""
Proactive clip request pipeline: when a safety Alert fires, ask the vehicle's
camera vendor to upload a clip covering the event time.

Fire-and-forget via ThreadPoolExecutor — never blocks the request/signal.
No-ops if VIDEO_CLIP_REQUEST_URL is not configured.
"""

from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings


def _vendor_post(payload: dict) -> tuple[bool, str, str]:
    """
    POST to VIDEO_CLIP_REQUEST_URL with Bearer VIDEO_CLIP_REQUEST_TOKEN.
    Returns (success, vendor_request_id, error_message).
    """
    url = getattr(settings, "VIDEO_CLIP_REQUEST_URL", "") or ""
    token = getattr(settings, "VIDEO_CLIP_REQUEST_TOKEN", "") or ""

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        vendor_id = str(data.get("request_id") or data.get("id") or "")
        return True, vendor_id, ""
    except Exception as exc:
        return False, "", str(exc)


def _update_clip_request(cr_pk: int, success: bool, vendor_id: str, error: str) -> None:
    from django.utils import timezone
    from mytrack.video_telematics.models import ClipRequest, ClipRequestStatus

    try:
        cr = ClipRequest.objects.get(pk=cr_pk)
    except ClipRequest.DoesNotExist:
        return

    if success:
        cr.status = ClipRequestStatus.PENDING  # pending until vendor confirms clip is ready
        cr.vendor_request_id = vendor_id[:200] if vendor_id else ""
        cr.fulfilled_at = timezone.now() if vendor_id else None
    else:
        cr.status = ClipRequestStatus.FAILED
        cr.error_message = error[:500]
    cr.save(update_fields=["status", "vendor_request_id", "fulfilled_at", "error_message"])


def request_clip_for_alert(alert) -> None:
    """
    Create a ClipRequest row synchronously, then fire a vendor HTTP POST
    in a background thread. Safe to call from a Django signal — never raises.
    """
    url = getattr(settings, "VIDEO_CLIP_REQUEST_URL", "") or ""
    if not url:
        return

    try:
        from mytrack.video_telematics.models import ClipRequest, VideoChannel

        channel = VideoChannel.objects.filter(vehicle=alert.vehicle, is_active=True).first()

        cr = ClipRequest.objects.create(
            organisation=alert.vehicle.organisation,
            vehicle=alert.vehicle,
            alert=alert,
            channel=channel,
        )
        cr_pk = cr.pk
    except Exception:
        return

    payload = {
        "vehicle_registration": alert.vehicle.registration,
        "org_slug": alert.vehicle.organisation.slug,
        "alert_kind": alert.kind,
        "occurred_at": alert.occurred_at.isoformat() if alert.occurred_at else "",
        "clip_request_id": cr_pk,
        "pre_event_seconds": int(getattr(settings, "VIDEO_CLIP_PRE_EVENT_SECONDS", 30)),
        "post_event_seconds": int(getattr(settings, "VIDEO_CLIP_POST_EVENT_SECONDS", 30)),
        "channel": channel.external_channel_id if channel else "",
    }

    def _run():
        success, vendor_id, error = _vendor_post(payload)
        try:
            _update_clip_request(cr_pk, success, vendor_id, error)
        except Exception:
            pass

    ThreadPoolExecutor(max_workers=1).submit(_run)
