"""Register video clips when Traccar position payloads carry media URLs."""

from __future__ import annotations

from mytrack.video_telematics.ingest_api import _create_asset
from mytrack.video_telematics.models import IngestSource, VideoTrigger
from mytrack.tracking.models import AlertKind
from mytrack.tracking.traccar_events import normalize_traccar_alert_kind


def register_clip_from_traccar_attributes(attributes, vehicle, occurred_at, tracked_trip, position_id):
    """
    If attributes contain a vendor-neutral media URL, upsert a VideoAsset.

    Checked keys (common vendor / forward variants): videoUrl, mediaUrl, fileUrl.
    """
    if not attributes or not isinstance(attributes, dict):
        return None

    candidates = (
        attributes.get("videoUrl"),
        attributes.get("mediaUrl"),
        attributes.get("fileUrl"),
    )
    media_url = None
    for u in candidates:
        if isinstance(u, str):
            u = u.strip()
            if u.startswith(("http://", "https://")):
                media_url = u
                break

    if not media_url:
        return None

    ext_id = ""
    if position_id is not None:
        ext_id = str(position_id).strip()[:120]
    if not ext_id:
        ts = int(occurred_at.timestamp()) if hasattr(occurred_at, "timestamp") else 0
        ext_id = f"traccar-{vehicle.pk}-{ts}"[:120]

    kind = normalize_traccar_alert_kind(attributes)
    trigger_map = {
        AlertKind.SPEEDING: VideoTrigger.SPEEDING,
        AlertKind.HARSH_BRAKING: VideoTrigger.HARSH_BRAKING,
        AlertKind.HARSH_ACCEL: VideoTrigger.HARSH_ACCEL,
        AlertKind.LANE_DEPARTURE: VideoTrigger.LANE_DEPARTURE,
        AlertKind.FATIGUE: VideoTrigger.FATIGUE,
        AlertKind.PHONE_USE: VideoTrigger.PHONE_USE,
        AlertKind.SEATBELT: VideoTrigger.SEATBELT,
    }
    trigger_type = trigger_map.get(kind, VideoTrigger.UNKNOWN)

    asset, created = _create_asset(
        vehicle=vehicle,
        occurred_at=occurred_at,
        trigger_type=trigger_type,
        ingest_source=IngestSource.TRACCAR,
        external_id=ext_id,
        storage_key="",
        playback_url=media_url,
        content_type=(attributes.get("videoContentType") or attributes.get("contentType") or "").strip(),
        duration_seconds=attributes.get("videoDuration") or attributes.get("duration"),
        size_bytes=attributes.get("videoSize") or attributes.get("size"),
        tracked_trip_id=tracked_trip.pk if tracked_trip else None,
        provider_payload={"source": "traccar_forward", "attributes_keys": list(attributes.keys())[:40]},
    )
    # _create_asset() handles correlation and email internally; nothing extra needed here.
    return asset, created
