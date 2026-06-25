"""Bearer-authenticated ingest APIs for video clips."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from mytrack.tenancy.models import Organisation
from mytrack.tracking.models import Alert, TrackedTrip
from mytrack.vehicles.models import Vehicle
from mytrack.video_telematics.models import (
    IngestSource,
    VideoAsset,
    VideoTrigger,
    VideoUploadIntent,
    video_relative_upload_path,
)
from mytrack.video_telematics.storage import generate_s3_presigned_put


def _json_error(message: str, status: int = 400):
    return JsonResponse({"detail": message}, status=status)


def _check_video_ingest_token(request) -> bool:
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    dedicated = getattr(settings, "VIDEO_INGEST_TOKEN", "") or ""
    ingest = getattr(settings, "INGEST_API_TOKEN", "")
    return token == (dedicated or ingest)


def _parse_dt(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        return parse_datetime(raw)
    return None


def _resolve_vehicle(org_slug: str | None, vehicle_id=None, vehicle_registration=None) -> Vehicle | None:
    org = None
    if org_slug:
        org = Organisation.objects.filter(slug=org_slug.strip()).first()
    params = {}
    if vehicle_id is not None:
        params["pk"] = vehicle_id
    elif vehicle_registration:
        params["registration__iexact"] = str(vehicle_registration).strip().upper()
    else:
        return None
    qs = Vehicle.objects.filter(**params)
    if org:
        qs = qs.filter(organisation=org)
    return qs.select_related("organisation").first()


def _create_asset(
    *,
    vehicle: Vehicle,
    occurred_at,
    trigger_type: str,
    ingest_source: str,
    external_id: str = "",
    storage_key: str = "",
    playback_url: str = "",
    content_type: str = "",
    duration_seconds=None,
    size_bytes=None,
    checksum_sha256: str = "",
    alert_id=None,
    tracked_trip_id=None,
    provider_payload=None,
):
    alert = None
    if alert_id is not None:
        alert = Alert.objects.filter(pk=alert_id, vehicle=vehicle).first()
    tracked_trip = None
    if tracked_trip_id is not None:
        tracked_trip = TrackedTrip.objects.filter(pk=tracked_trip_id, vehicle=vehicle).first()

    defaults = {
        "organisation_id": vehicle.organisation_id,
        "occurred_at": occurred_at,
        "trigger_type": trigger_type,
        "ingest_source": ingest_source,
        "external_id": external_id[:120] if external_id else "",
        "storage_key": storage_key[:512] if storage_key else "",
        "playback_url": playback_url[:2048] if playback_url else "",
        "content_type": content_type[:120] if content_type else "",
        "duration_seconds": duration_seconds,
        "size_bytes": size_bytes,
        "checksum_sha256": checksum_sha256[:64] if checksum_sha256 else "",
        "alert": alert,
        "tracked_trip": tracked_trip,
        "provider_payload": provider_payload if isinstance(provider_payload, dict) else {},
    }

    if external_id:
        asset, created = VideoAsset.objects.update_or_create(
            ingest_source=ingest_source,
            external_id=external_id[:120],
            defaults={**defaults, "vehicle": vehicle},
        )
    else:
        asset = VideoAsset.objects.create(vehicle=vehicle, **defaults)
        created = True

    if created and asset.alert_id is None:
        try:
            from mytrack.video_telematics.correlation import (
                correlate_asset_to_alert,
                update_channel_last_seen,
            )
            matched = correlate_asset_to_alert(asset)
            update_channel_last_seen(asset)
            if matched:
                from mytrack.notifications.emails import send_video_safety_alert
                send_video_safety_alert(asset)
        except Exception:
            pass

    return asset, created


@csrf_exempt
@require_POST
def video_webhook(request):
    """
    Register a clip hosted by a vendor (playback_url) or reference stored objects (storage_key after direct upload).
    POST JSON body: org_slug, vehicle_registration or vehicle_id, occurred_at, trigger_type,
    playback_url or storage_key, optional external_id, ingest_source, alert_id, tracked_trip_id, ...
    """
    if not _check_video_ingest_token(request):
        return _json_error("Unauthorized.", 401)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return _json_error("Invalid JSON.")

    org_slug = (data.get("org_slug") or "").strip() or getattr(settings, "TRACCAR_DEFAULT_ORG_SLUG", "")
    vehicle = _resolve_vehicle(
        org_slug,
        vehicle_id=data.get("vehicle_id"),
        vehicle_registration=data.get("vehicle_registration"),
    )
    if not vehicle:
        return _json_error("Unknown vehicle.", 400)

    playback_url = (data.get("playback_url") or "").strip()
    storage_key = (data.get("storage_key") or "").strip()
    if not playback_url and not storage_key:
        return _json_error("playback_url or storage_key required.")

    occurred_at = _parse_dt(data.get("occurred_at")) or timezone.now()
    trigger_type = data.get("trigger_type") or VideoTrigger.UNKNOWN
    trigger_values = tuple(v for v, _ in VideoTrigger.choices)
    if trigger_type not in trigger_values:
        trigger_type = VideoTrigger.UNKNOWN

    ingest_src = data.get("ingest_source") or IngestSource.WEBHOOK
    ingest_values = tuple(v for v, _ in IngestSource.choices)
    if ingest_src not in ingest_values:
        ingest_src = IngestSource.WEBHOOK

    external_id = (data.get("external_id") or "").strip()

    try:
        asset, created = _create_asset(
            vehicle=vehicle,
            occurred_at=occurred_at,
            trigger_type=trigger_type,
            ingest_source=ingest_src,
            external_id=external_id,
            storage_key=storage_key,
            playback_url=playback_url,
            content_type=(data.get("content_type") or "").strip(),
            duration_seconds=data.get("duration_seconds"),
            size_bytes=data.get("size_bytes"),
            checksum_sha256=(data.get("checksum_sha256") or "").strip(),
            alert_id=data.get("alert_id"),
            tracked_trip_id=data.get("tracked_trip_id"),
            provider_payload=data.get("provider_payload"),
        )
    except Exception as exc:
        return _json_error(str(exc), 400)

    return JsonResponse({"ok": True, "id": asset.pk, "created": created})


@csrf_exempt
@require_POST
def video_presign_upload(request):
    """Return upload URL (S3 presigned PUT or local intent URL)."""
    if not _check_video_ingest_token(request):
        return _json_error("Unauthorized.", 401)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return _json_error("Invalid JSON.")

    org_slug = (data.get("org_slug") or "").strip() or getattr(settings, "TRACCAR_DEFAULT_ORG_SLUG", "")
    vehicle = _resolve_vehicle(
        org_slug,
        vehicle_id=data.get("vehicle_id"),
        vehicle_registration=data.get("vehicle_registration"),
    )
    if not vehicle:
        return _json_error("Unknown vehicle.", 400)

    filename = (data.get("filename") or "clip.bin").strip()
    content_type = (data.get("content_type") or "application/octet-stream").strip()
    trigger_type = data.get("trigger_type") or VideoTrigger.UNKNOWN
    trigger_values = tuple(v for v, _ in VideoTrigger.choices)
    if trigger_type not in trigger_values:
        trigger_type = VideoTrigger.UNKNOWN

    storage_key = video_relative_upload_path(vehicle.organisation.slug, filename)
    expires_s = int(getattr(settings, "VIDEO_UPLOAD_URL_EXPIRY", 3600))
    expires_at = timezone.now() + timedelta(seconds=expires_s)
    backend = getattr(settings, "VIDEO_STORAGE_BACKEND", "local")

    intent = VideoUploadIntent.objects.create(
        organisation_id=vehicle.organisation_id,
        vehicle_id=vehicle.pk,
        storage_key=storage_key,
        content_type=content_type,
        trigger_type=trigger_type,
        expires_at=expires_at,
    )

    if backend == "s3":
        try:
            upload_url = generate_s3_presigned_put(storage_key, content_type, expires_s)
        except Exception as exc:
            intent.delete()
            return _json_error(f"S3 presign failed: {exc}", 500)
        return JsonResponse(
            {
                "storage_backend": "s3",
                "upload_url": upload_url,
                "method": "PUT",
                "storage_key": storage_key,
                "intent_id": str(intent.pk),
                "expires_at": expires_at.isoformat(),
                "headers": {"Content-Type": content_type},
            }
        )

    upload_url = request.build_absolute_uri(f"/api/video/upload/intent/{intent.pk}/")
    return JsonResponse(
        {
            "storage_backend": "local",
            "upload_url": upload_url,
            "method": "PUT",
            "storage_key": storage_key,
            "intent_id": str(intent.pk),
            "expires_at": expires_at.isoformat(),
            "headers": {"Content-Type": content_type},
        }
    )


@csrf_exempt
@require_http_methods(["PUT"])
def video_upload_intent_put(request, intent_id):
    """Write raw body to MEDIA_ROOT for a pending intent."""
    if not _check_video_ingest_token(request):
        return _json_error("Unauthorized.", 401)

    intent = VideoUploadIntent.objects.filter(pk=intent_id).select_related("vehicle").first()
    if not intent or intent.is_expired():
        return _json_error("Invalid or expired intent.", 400)
    if intent.uploaded_at:
        return _json_error("Already uploaded.", 400)

    root = Path(settings.MEDIA_ROOT)
    dest = root / intent.storage_key
    dest.parent.mkdir(parents=True, exist_ok=True)

    max_bytes = int(getattr(settings, "VIDEO_UPLOAD_MAX_BYTES", 524288000))
    written = 0
    chunk_size = 1024 * 512
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = request.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    dest.unlink(missing_ok=True)
                    return _json_error("File too large.", 413)
                fh.write(chunk)
    except OSError as exc:
        dest.unlink(missing_ok=True)
        return _json_error(str(exc), 500)

    intent.uploaded_at = timezone.now()
    intent.save(update_fields=["uploaded_at"])
    return JsonResponse({"ok": True, "storage_key": intent.storage_key, "bytes": written})


@csrf_exempt
@require_POST
def video_upload_complete(request):
    """Finalize DB row after bytes are stored (local intent PUT or S3 PUT)."""
    if not _check_video_ingest_token(request):
        return _json_error("Unauthorized.", 401)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return _json_error("Invalid JSON.")

    backend = getattr(settings, "VIDEO_STORAGE_BACKEND", "local")
    intent_id = data.get("intent_id")

    vehicle = None
    storage_key = (data.get("storage_key") or "").strip()
    trigger_type = data.get("trigger_type") or VideoTrigger.UNKNOWN
    trigger_values = tuple(v for v, _ in VideoTrigger.choices)
    if trigger_type not in trigger_values:
        trigger_type = VideoTrigger.UNKNOWN

    intent_content_type = ""
    intent_pk_to_clear = None
    if intent_id:
        intent = VideoUploadIntent.objects.filter(pk=intent_id).select_related("vehicle").first()
        if not intent:
            return _json_error("Unknown intent.", 400)
        vehicle = intent.vehicle
        storage_key = intent.storage_key
        trigger_type = intent.trigger_type
        intent_content_type = intent.content_type or ""
        intent_pk_to_clear = intent.pk
        if backend == "local":
            if not intent.uploaded_at:
                return _json_error("Upload not finished.", 400)
    else:
        org_slug = (data.get("org_slug") or "").strip() or getattr(settings, "TRACCAR_DEFAULT_ORG_SLUG", "")
        vehicle = _resolve_vehicle(
            org_slug,
            vehicle_id=data.get("vehicle_id"),
            vehicle_registration=data.get("vehicle_registration"),
        )
        if not vehicle:
            return _json_error("Unknown vehicle.", 400)
        if not storage_key:
            return _json_error("storage_key or intent_id required.", 400)

    occurred_at = _parse_dt(data.get("occurred_at")) or timezone.now()

    if backend == "local":
        path = Path(settings.MEDIA_ROOT) / storage_key
        if not path.is_file():
            return _json_error("Object not found on disk.", 400)

    external_id = (data.get("external_id") or "").strip()

    try:
        asset, created = _create_asset(
            vehicle=vehicle,
            occurred_at=occurred_at,
            trigger_type=trigger_type,
            ingest_source=IngestSource.DIRECT_UPLOAD,
            external_id=external_id,
            storage_key=storage_key,
            playback_url="",
            content_type=(data.get("content_type") or "").strip() or intent_content_type or "video/mp4",
            duration_seconds=data.get("duration_seconds"),
            size_bytes=data.get("size_bytes"),
            checksum_sha256=(data.get("checksum_sha256") or "").strip(),
            alert_id=data.get("alert_id"),
            tracked_trip_id=data.get("tracked_trip_id"),
            provider_payload=data.get("provider_payload"),
        )
    except Exception as exc:
        return _json_error(str(exc), 400)

    if intent_pk_to_clear:
        VideoUploadIntent.objects.filter(pk=intent_pk_to_clear).delete()

    return JsonResponse({"ok": True, "id": asset.pk, "created": created})
