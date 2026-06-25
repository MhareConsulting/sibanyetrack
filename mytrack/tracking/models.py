import uuid

from django.db import models
from django.utils import timezone

from mytrack.vehicles.models import Vehicle


class GPSPing(models.Model):
    """Immutable record of every GPS position received from the field."""

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="pings")
    lat = models.FloatField()
    lon = models.FloatField()
    speed_kmh = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    driver_name = models.CharField(max_length=200, blank=True)
    myroutes_trip_id = models.IntegerField(null=True, blank=True, db_index=True)
    device_timestamp = models.DateTimeField(null=True, blank=True, db_index=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    tracked_trip = models.ForeignKey(
        "TrackedTrip", null=True, blank=True, on_delete=models.SET_NULL, related_name="pings"
    )
    road_speed_limit_kmh = models.FloatField(
        null=True,
        blank=True,
        help_text="Posted or fallback speed limit (km/h) used for this ping when road limits are enabled.",
    )
    road_speed_source = models.CharField(
        max_length=16,
        blank=True,
        help_text="traccar, cache, postgis, or fallback",
    )

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["vehicle", "device_timestamp"]),
            models.Index(fields=["vehicle", "received_at"]),
        ]

    def __str__(self):
        return f"{self.vehicle} {self.lat},{self.lon} @ {self.received_at}"


class RoadSpeedCache(models.Model):
    """Spatial cache for resolved road speed limits (grid cell → km/h)."""

    cell_key = models.CharField(max_length=40, primary_key=True, help_text="Quantized lat|lon cell key.")
    limit_kmh = models.FloatField()
    osm_way_id = models.BigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tracking_roadspeedcache"

    def __str__(self):
        return f"{self.cell_key} → {self.limit_kmh} km/h"


class TripClassification(models.TextChoices):
    PERSONAL = "personal", "Personal"
    BUSINESS = "business", "Business"


class TrackedTrip(models.Model):
    """
    A contiguous movement segment auto-reconstructed from GPSPings.
    A new trip is opened when a ping arrives more than GAP_MINUTES after the previous one.
    """

    GAP_MINUTES = 15  # silence gap that closes the current trip and opens a new one

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="tracked_trips")
    driver_name = models.CharField(max_length=200, blank=True)
    myroutes_trip_id = models.IntegerField(null=True, blank=True, db_index=True)

    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    start_lat = models.FloatField()
    start_lon = models.FloatField()
    end_lat = models.FloatField(null=True, blank=True)
    end_lon = models.FloatField(null=True, blank=True)

    distance_km = models.FloatField(null=True, blank=True)
    max_speed_kmh = models.FloatField(null=True, blank=True)
    ping_count = models.PositiveIntegerField(default=0)
    business_purpose = models.CharField(max_length=200, blank=True)
    destination_name = models.CharField(max_length=200, blank=True)
    classification = models.CharField(
        max_length=10,
        choices=TripClassification.choices,
        default=TripClassification.BUSINESS,
        db_index=True,
    )
    start_label = models.CharField(max_length=300, blank=True, default="")
    end_label = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["vehicle", "started_at"])]

    def __str__(self):
        return f"{self.vehicle} trip @ {self.started_at}"

    @property
    def duration_minutes(self):
        if self.ended_at:
            return round((self.ended_at - self.started_at).total_seconds() / 60, 1)
        return None


class AlertKind(models.TextChoices):
    SPEEDING              = "speeding",              "Speeding"
    IDLE                  = "idle",                  "Idle"
    FUEL_THEFT            = "fuel_theft",            "Fuel Theft"
    FUEL_DRAIN            = "fuel_drain",            "Fuel Drain"
    PROBE_FAULT           = "probe_fault",           "Probe Fault"
    EXCESS_CONSUMPTION    = "excess_consumption",    "Excess Consumption"
    HARSH_BRAKING         = "harsh_braking",         "Harsh Braking"
    HARSH_ACCEL           = "harsh_accel",           "Harsh Acceleration"
    HARSH_CORNERING       = "harsh_cornering",       "Harsh Cornering"
    LANE_DEPARTURE        = "lane_departure",        "Lane Departure"
    FATIGUE               = "fatigue",               "Driver Fatigue"
    PHONE_USE             = "phone_use",             "Phone Use"
    SEATBELT              = "seatbelt",              "Seatbelt Violation"
    CAMERA_EVENT          = "camera_event",          "Camera Event"
    GEOFENCE_AFTER_HOURS  = "geofence_after_hours",  "Geofence After-Hours"


class AlertSeverity(models.TextChoices):
    INFO     = "info",     "Info"
    WARNING  = "warning",  "Warning"
    CRITICAL = "critical", "Critical"


# Maps each AlertKind to its default severity.
ALERT_KIND_SEVERITY: dict[str, str] = {
    AlertKind.FUEL_THEFT:         AlertSeverity.CRITICAL,
    AlertKind.HARSH_BRAKING:      AlertSeverity.CRITICAL,
    AlertKind.HARSH_ACCEL:        AlertSeverity.CRITICAL,
    AlertKind.HARSH_CORNERING:    AlertSeverity.CRITICAL,
    AlertKind.FATIGUE:            AlertSeverity.CRITICAL,
    AlertKind.LANE_DEPARTURE:     AlertSeverity.CRITICAL,
    AlertKind.PHONE_USE:          AlertSeverity.CRITICAL,
    AlertKind.IDLE:               AlertSeverity.INFO,
}


def default_severity_for_kind(kind: str) -> str:
    return ALERT_KIND_SEVERITY.get(kind, AlertSeverity.WARNING)


class Alert(models.Model):
    vehicle     = models.ForeignKey("vehicles.Vehicle", on_delete=models.CASCADE, related_name="alerts")
    kind        = models.CharField(max_length=20, choices=AlertKind.choices, db_index=True)
    severity    = models.CharField(max_length=10, choices=AlertSeverity.choices, default=AlertSeverity.WARNING, db_index=True)
    value       = models.FloatField(help_text="Observed value (km/h or minutes idle)")
    threshold   = models.FloatField(help_text="Threshold that was breached")
    occurred_at = models.DateTimeField(db_index=True)
    resolved_at   = models.DateTimeField(null=True, blank=True)
    resolved_by   = models.ForeignKey(
        "tenancy.User", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="resolved_alerts",
    )
    resolution_note = models.CharField(max_length=200, blank=True)
    driver_name = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["vehicle", "occurred_at"]),
            models.Index(fields=["kind", "resolved_at"]),
            models.Index(fields=["vehicle", "kind", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.vehicle} @ {self.occurred_at}"

    @property
    def is_open(self):
        return self.resolved_at is None


class SyncOutbox(models.Model):
    """Pending HTTP push to an external system. Retried by the cron flush endpoint."""

    DEST_MYROUTES_POSITION = "myroutes_position"
    DEST_MYROUTES_SYNC = "myroutes_sync"
    DEST_MYROUTES_FUEL = "myroutes_fuel"

    destination = models.CharField(max_length=32, db_index=True)
    payload = models.JSONField()
    attempts = models.PositiveSmallIntegerField(default=0)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    succeeded_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["destination", "succeeded_at", "attempts"]),
        ]

    def __str__(self):
        return f"{self.destination} attempt={self.attempts} ok={self.succeeded_at is not None}"


class DeliveryShare(models.Model):
    """Shareable tracking link sent to a customer for a specific vehicle/delivery."""

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="delivery_shares")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer_name = models.CharField(max_length=200, blank=True)
    customer_email = models.EmailField()
    note = models.CharField(max_length=500, blank=True, help_text="e.g. 'Order #1234 delivery'")
    created_by = models.ForeignKey(
        "tenancy.User", on_delete=models.SET_NULL, null=True, related_name="delivery_shares"
    )
    stop_number = models.PositiveSmallIntegerField(null=True, blank=True, help_text="This customer's position in the delivery run (e.g. 3).")
    total_stops = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Total stops in the run (e.g. 5).")
    destination_lat = models.FloatField(null=True, blank=True)
    destination_lon = models.FloatField(null=True, blank=True)
    destination_address = models.CharField(max_length=300, blank=True, help_text="Human-readable destination shown on tracking page.")
    completed_at = models.DateTimeField(null=True, blank=True, help_text="Set when dispatcher marks delivery as complete.")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vehicle} → {self.customer_email}"

    @property
    def is_active(self):
        return self.completed_at is None and timezone.now() < self.expires_at

    @property
    def status(self):
        if self.completed_at:
            return "delivered"
        if timezone.now() >= self.expires_at:
            return "expired"
        return "active"

    def get_public_url(self):
        from django.conf import settings
        return f"{settings.SITE_URL}/track/{self.token}/"
