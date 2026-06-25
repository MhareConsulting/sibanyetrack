"""Playback URL generation: local files, S3 presigned GET, or external playback_url."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.http import FileResponse, HttpResponseRedirect

from mytrack.video_telematics.s3_utils import get_s3_client as _s3_client


def generate_s3_presigned_put(storage_key: str, content_type: str, expires_in: int | None = None) -> str:
    expires_in = expires_in or int(getattr(settings, "VIDEO_UPLOAD_URL_EXPIRY", 3600))
    bucket = getattr(settings, "VIDEO_S3_BUCKET", "")
    if not bucket:
        raise ValueError("VIDEO_S3_BUCKET is not configured.")
    client = _s3_client()
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": storage_key,
            "ContentType": content_type or "application/octet-stream",
        },
        ExpiresIn=expires_in,
    )


def generate_s3_presigned_get(storage_key: str, expires_in: int | None = None) -> str:
    expires_in = expires_in or int(getattr(settings, "VIDEO_PLAYBACK_URL_EXPIRY", 3600))
    bucket = getattr(settings, "VIDEO_S3_BUCKET", "")
    if not bucket:
        raise ValueError("VIDEO_S3_BUCKET is not configured.")
    client = _s3_client()
    params = {"Bucket": bucket, "Key": storage_key}
    ct = getattr(settings, "VIDEO_S3_RESPONSE_CONTENT_TYPE", "") or None
    if ct:
        params["ResponseContentType"] = ct
    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in,
    )


def is_safe_external_playback_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def playback_redirect(asset) -> HttpResponseRedirect | FileResponse:
    """
    Return a redirect to presigned/external URL, or a FileResponse for local storage_key.
    Caller must enforce organisation auth.
    """
    from mytrack.video_telematics.models import VideoAsset

    if not isinstance(asset, VideoAsset):
        raise TypeError("Expected VideoAsset")

    if asset.playback_url:
        if not is_safe_external_playback_url(asset.playback_url):
            from django.http import HttpResponseBadRequest

            return HttpResponseBadRequest("Invalid playback URL.")
        return HttpResponseRedirect(asset.playback_url)

    backend = getattr(settings, "VIDEO_STORAGE_BACKEND", "local")
    if backend == "s3" and asset.storage_key:
        url = generate_s3_presigned_get(asset.storage_key)
        return HttpResponseRedirect(url)

    # local
    if not asset.storage_key:
        from django.http import HttpResponseBadRequest

        return HttpResponseBadRequest("No media location.")

    path = Path(settings.MEDIA_ROOT) / asset.storage_key
    if not path.is_file():
        from django.http import Http404

        raise Http404("Video file missing.")

    ct = asset.content_type or "video/mp4"
    return FileResponse(path.open("rb"), content_type=ct)
