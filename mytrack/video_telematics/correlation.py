"""Auto-correlate a newly-ingested VideoAsset to the nearest Alert by time proximity."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def _window_minutes() -> int:
    return int(getattr(settings, "VIDEO_ALERT_CORRELATION_WINDOW_MINUTES", 5))


def correlate_asset_to_alert(asset) -> bool:
    """
    Find the nearest Alert for asset.vehicle within ±VIDEO_ALERT_CORRELATION_WINDOW_MINUTES
    of asset.occurred_at. Sets asset.alert and saves (update_fields=["alert"]).
    Returns True if a match was made. Skips if asset.alert_id is already set.
    """
    if asset.alert_id is not None:
        return False

    t = asset.occurred_at
    if t is None:
        return False

    from mytrack.tracking.models import Alert

    window = timedelta(minutes=_window_minutes())
    qs = list(
        Alert.objects.filter(
            vehicle_id=asset.vehicle_id,
            occurred_at__gte=t - window,
            occurred_at__lte=t + window,
        )
    )
    if not qs:
        return False

    best = min(qs, key=lambda a: abs((a.occurred_at - t).total_seconds()))
    asset.alert = best
    asset.save(update_fields=["alert"])
    return True


def update_channel_last_seen(asset) -> None:
    """Update VideoChannel.camera_last_seen after a clip is ingested."""
    if not asset.channel_id:
        return
    from mytrack.video_telematics.models import VideoChannel

    VideoChannel.objects.filter(pk=asset.channel_id).update(
        camera_last_seen=asset.occurred_at or timezone.now()
    )
