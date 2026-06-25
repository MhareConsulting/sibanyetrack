from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class Organisation(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    speed_limit_kmh = models.PositiveSmallIntegerField(
        default=120,
        help_text="Fallback fleet speeding threshold (km/h) when road-specific data is unavailable, or when road limits are disabled.",
    )
    road_speed_limits_enabled = models.BooleanField(
        default=False,
        help_text="Use OSM-backed road speeds (plus cache) when data is loaded; otherwise only speed_limit_kmh applies.",
    )
    speeding_grace_kmh = models.FloatField(
        default=0.0,
        help_text="Extra km/h over the limit before a speeding alert is raised.",
    )
    fuel_price_zar = models.DecimalField(max_digits=6, decimal_places=2, default="22.00", help_text="Fuel price per litre (ZAR).")
    idle_burn_rate_lph = models.DecimalField(max_digits=5, decimal_places=2, default="3.50", help_text="Fuel burn rate while idling (litres per hour).")
    seat_limit = models.PositiveSmallIntegerField(default=10, help_text="Maximum licensed users.")
    # Fuel detection thresholds — override per organisation
    fuel_refuel_threshold_litres = models.FloatField(default=8.0, help_text="Fuel rise (L) required to classify as a refuel.")
    fuel_theft_threshold_litres  = models.FloatField(default=5.0, help_text="Fuel drop (L) required to trigger theft/drain detection.")
    fuel_theft_speed_max_kmh     = models.FloatField(default=5.0, help_text="Speed (km/h) at or below which a drop is classified as theft rather than drain.")

    notify_critical_instant = models.BooleanField(
        default=True,
        help_text="Send an immediate email when a CRITICAL-severity alert is created (fuel theft, harsh events, fatigue, etc.).",
    )
    email_daily_digest_enabled = models.BooleanField(
        default=True,
        help_text="Send daily unresolved-alert digest (scheduled job).",
    )
    email_weekly_summary_enabled = models.BooleanField(
        default=True,
        help_text="Send weekly fleet and safety summary (scheduled job).",
    )
    email_monthly_summary_enabled = models.BooleanField(
        default=True,
        help_text="Send monthly fleet and safety summary (scheduled job).",
    )
    email_expiry_warnings_enabled = models.BooleanField(
        default=True,
        help_text="Send licence/PDP/document expiry warning emails (scheduled job).",
    )
    notification_cc_emails = models.TextField(
        blank=True,
        help_text="Optional comma-separated addresses copied on scheduled org notification emails.",
    )
    whatsapp_driver_notify_enabled = models.BooleanField(
        default=False,
        help_text="Send WhatsApp messages directly to drivers when alerts are triggered (requires META_WHATSAPP_* env vars).",
    )
    require_2fa = models.BooleanField(
        default=False,
        help_text="Require all users in this organisation to use two-factor authentication (TOTP).",
    )

    def __str__(self):
        return self.name


class Depot(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="depots")
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=255, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("organisation", "name")]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    DISPATCHER = "dispatcher", "Dispatcher"
    VIEWER = "viewer", "Viewer"
    DRIVER = "driver", "Driver"


class User(AbstractUser):
    organisation = models.ForeignKey(
        Organisation, null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DISPATCHER)
    consumes_license = models.BooleanField(default=True, help_text="Counts toward the organisation's seat limit.")
    linked_driver = models.ForeignKey(
        "drivers.Driver", null=True, blank=True, on_delete=models.SET_NULL, related_name="user_accounts"
    )

    def __str__(self):
        return self.username

    def accessible_depots(self):
        """Return QS of depots this user can see. Admins see all org depots."""
        if self.role == Role.ADMIN or self.is_superuser:
            return Depot.objects.filter(organisation=self.organisation)
        return Depot.objects.filter(access_grants__user=self)


class UserDepotAccess(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="depot_access")
    depot = models.ForeignKey(Depot, on_delete=models.CASCADE, related_name="access_grants")

    class Meta:
        unique_together = [("user", "depot")]

    def __str__(self):
        return f"{self.user} → {self.depot}"


class AuditEvent(models.Model):
    """Immutable audit trail of fleet management actions."""
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="audit_events", db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events")
    action = models.CharField(max_length=20)        # create, update, delete, resolve, login
    target_model = models.CharField(max_length=60)
    target_id = models.CharField(max_length=40)
    target_repr = models.CharField(max_length=200)
    delta = models.JSONField(default=dict)           # {field: [old, new]}
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.user} {self.action} {self.target_model}:{self.target_id}"
