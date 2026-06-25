import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from mytrack.tenancy.models import Organisation
from mytrack.vehicles.models import Vehicle


class ChannelSource(models.TextChoices):
    TRACCAR = "traccar", "Traccar"
    VENDOR = "vendor", "Vendor"
    MANUAL_UPLOAD = "manual_upload", "Manual upload"


class VideoTrigger(models.TextChoices):
    HARSH_EVENT    = "harsh_event",    "Harsh event"
    SPEEDING       = "speeding",       "Speeding"
    MANUAL         = "manual",         "Manual"
    SCHEDULED      = "scheduled",      "Scheduled"
    UNKNOWN        = "unknown",        "Unknown"
    HARSH_BRAKING  = "harsh_braking",  "Harsh braking"
    HARSH_ACCEL    = "harsh_accel",    "Harsh acceleration"
    LANE_DEPARTURE = "lane_departure", "Lane departure"
    FATIGUE        = "fatigue",        "Driver fatigue"
    PHONE_USE      = "phone_use",      "Phone use"
    SEATBELT       = "seatbelt",       "Seatbelt violation"


class IngestSource(models.TextChoices):
    TRACCAR = "traccar", "Traccar"
    WEBHOOK = "webhook", "Webhook"
    DIRECT_UPLOAD = "direct_upload", "Direct upload"
    VENDOR = "vendor", "Vendor"
    STREAMAX = "streamax", "Streamax"


class VideoChannel(models.Model):
    """Logical camera / channel on a vehicle."""

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="video_channels")
    name = models.CharField(max_length=80)
    source = models.CharField(max_length=20, choices=ChannelSource.choices, default=ChannelSource.VENDOR)
    external_channel_id = models.CharField(max_length=120, blank=True)

    stream_url = models.URLField(max_length=2048, blank=True, help_text="Live stream URL (MJPEG, HLS, etc.) served to the browser.")
    camera_last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["vehicle_id", "name"]
        indexes = [models.Index(fields=["vehicle", "source"])]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle", "name", "source"],
                name="video_channel_unique_vehicle_name_source",
            ),
        ]

    def __str__(self):
        return f"{self.vehicle} — {self.name}"


class VideoAsset(models.Model):
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="video_assets"
    )
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="video_assets")
    channel = models.ForeignKey(
        VideoChannel, null=True, blank=True, on_delete=models.SET_NULL, related_name="assets"
    )
    occurred_at = models.DateTimeField(db_index=True)
    recorded_start = models.DateTimeField(null=True, blank=True)
    recorded_end = models.DateTimeField(null=True, blank=True)
    trigger_type = models.CharField(max_length=20, choices=VideoTrigger.choices, default=VideoTrigger.UNKNOWN)
    ingest_source = models.CharField(max_length=20, choices=IngestSource.choices)
    external_id = models.CharField(max_length=120, blank=True, db_index=True)

    # Stored object key under MEDIA_ROOT (local) or S3 key; empty when only playback_url is used.
    storage_key = models.CharField(max_length=512, blank=True)
    playback_url = models.URLField(max_length=2048, blank=True)

    content_type = models.CharField(max_length=120, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True)

    alert = models.ForeignKey(
        "tracking.Alert",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="video_assets",
    )
    tracked_trip = models.ForeignKey(
        "tracking.TrackedTrip",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="video_assets",
    )
    delete_after = models.DateTimeField(null=True, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["organisation", "-occurred_at"]),
            models.Index(fields=["vehicle", "-occurred_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ingest_source", "external_id"],
                condition=models.Q(external_id__gt=""),
                name="video_asset_unique_ingest_external_id",
            ),
        ]

    def __str__(self):
        return f"{self.vehicle} @ {self.occurred_at}"

    def save(self, *args, **kwargs):
        if self.vehicle_id and not self.organisation_id:
            self.organisation_id = Vehicle.objects.filter(pk=self.vehicle_id).values_list(
                "organisation_id", flat=True
            ).first()
        super().save(*args, **kwargs)


class VideoUploadIntent(models.Model):
    """One-time upload slot for direct PUT (local) or metadata for S3 multipart flows."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="video_upload_intents")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="video_upload_intents")
    storage_key = models.CharField(max_length=512)
    content_type = models.CharField(max_length=120, blank=True)
    trigger_type = models.CharField(max_length=20, choices=VideoTrigger.choices, default=VideoTrigger.UNKNOWN)
    expires_at = models.DateTimeField(db_index=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["expires_at"])]

    def is_expired(self):
        return timezone.now() >= self.expires_at


def video_relative_upload_path(org_slug: str, filename_hint: str) -> str:
    safe_ext = ""
    if "." in filename_hint:
        safe_ext = "." + filename_hint.rsplit(".", 1)[-1].lower()[:12]
    return f"video/{org_slug}/{uuid.uuid4().hex}{safe_ext}"


class ClipRequestStatus(models.TextChoices):
    PENDING   = "pending",   "Pending"
    FULFILLED = "fulfilled", "Fulfilled"
    FAILED    = "failed",    "Failed"


class ClipRequest(models.Model):
    """
    Records a proactive request for a video clip triggered by an Alert.
    Created synchronously when a safety alert fires; vendor HTTP call is fire-and-forget.
    """

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="clip_requests"
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="clip_requests"
    )
    alert = models.ForeignKey(
        "tracking.Alert",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="clip_requests",
    )
    channel = models.ForeignKey(
        VideoChannel,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="clip_requests",
    )
    status = models.CharField(
        max_length=12,
        choices=ClipRequestStatus.choices,
        default=ClipRequestStatus.PENDING,
        db_index=True,
    )
    vendor_request_id = models.CharField(max_length=200, blank=True, db_index=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    video_asset = models.ForeignKey(
        VideoAsset,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="clip_requests",
    )
    provider_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["organisation", "requested_at"]),
            models.Index(fields=["status", "requested_at"]),
        ]

    def __str__(self):
        return f"ClipRequest {self.pk} — {self.vehicle} [{self.status}]"
