from django.conf import settings
from django.db import models

from mytrack.tenancy.models import Depot, Organisation
from mytrack.vehicles.models import Vehicle


class DailyVehicleMetrics(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="daily_vehicle_metrics")
    depot = models.ForeignKey(Depot, null=True, blank=True, on_delete=models.SET_NULL, related_name="daily_vehicle_metrics")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="daily_metrics")
    metric_date = models.DateField(db_index=True)
    trip_count = models.PositiveIntegerField(default=0)
    ping_count = models.PositiveIntegerField(default=0)
    distance_km = models.FloatField(default=0.0)
    avg_speed_kmh = models.FloatField(default=0.0)
    max_speed_kmh = models.FloatField(default=0.0)
    idle_alert_count = models.PositiveIntegerField(default=0)
    speeding_alert_count = models.PositiveIntegerField(default=0)
    co2_kg = models.FloatField(default=0.0, help_text="Estimated CO₂ emitted (kg)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("vehicle", "metric_date")]
        indexes = [
            models.Index(fields=["organisation", "metric_date"]),
            models.Index(fields=["vehicle", "metric_date"]),
            models.Index(fields=["depot", "metric_date"]),
        ]
        ordering = ["-metric_date", "vehicle_id"]


class DailyFuelMetrics(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="daily_fuel_metrics")
    depot = models.ForeignKey(Depot, null=True, blank=True, on_delete=models.SET_NULL, related_name="daily_fuel_metrics")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="daily_fuel_metrics")
    metric_date = models.DateField(db_index=True)
    reading_count = models.PositiveIntegerField(default=0)
    opening_fuel_litres = models.FloatField(default=0.0)
    closing_fuel_litres = models.FloatField(default=0.0)
    fuel_delta_litres = models.FloatField(default=0.0)
    total_refuel_litres = models.FloatField(default=0.0)
    total_drain_litres = models.FloatField(default=0.0)
    theft_event_count = models.PositiveIntegerField(default=0)
    drain_event_count = models.PositiveIntegerField(default=0)
    excess_event_count = models.PositiveIntegerField(default=0)
    probe_fault_event_count = models.PositiveIntegerField(default=0)
    inferred_data = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("vehicle", "metric_date")]
        indexes = [
            models.Index(fields=["organisation", "metric_date"]),
            models.Index(fields=["vehicle", "metric_date"]),
            models.Index(fields=["depot", "metric_date"]),
        ]
        ordering = ["-metric_date", "vehicle_id"]


class DailyGeofenceMetrics(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="daily_geofence_metrics")
    depot = models.ForeignKey(Depot, null=True, blank=True, on_delete=models.SET_NULL, related_name="daily_geofence_metrics")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="daily_geofence_metrics")
    geofence = models.ForeignKey("geofences.Geofence", on_delete=models.CASCADE, related_name="daily_metrics")
    metric_date = models.DateField(db_index=True)
    enter_count = models.PositiveIntegerField(default=0)
    exit_count = models.PositiveIntegerField(default=0)
    visit_count = models.PositiveIntegerField(default=0)
    total_dwell_minutes = models.FloatField(default=0.0)
    avg_dwell_minutes = models.FloatField(default=0.0)
    max_dwell_minutes = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("vehicle", "geofence", "metric_date")]
        indexes = [
            models.Index(fields=["organisation", "metric_date"]),
            models.Index(fields=["vehicle", "metric_date"]),
            models.Index(fields=["depot", "metric_date"]),
            models.Index(fields=["geofence", "metric_date"]),
        ]
        ordering = ["-metric_date", "vehicle_id"]


class CustomReportDomain(models.TextChoices):
    SPEED = "speed", "Speed"
    FUEL = "fuel", "Fuel"
    GEOFENCE = "geofence", "Geofence"
    ROUTE = "route", "Route"


class CustomReportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"


class CustomReportDefinition(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="custom_report_definitions")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="custom_reports")
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=20, choices=CustomReportDomain.choices)
    columns = models.JSONField(default=list)
    metrics = models.JSONField(default=list)
    group_by = models.JSONField(default=list)
    filters = models.JSONField(default=dict)
    sort_by = models.JSONField(default=list)
    schedule_config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("organisation", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class SavedReportTemplate(models.Model):
    """A named snapshot of a custom report builder configuration."""
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="saved_report_templates")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="saved_report_templates"
    )
    name = models.CharField(max_length=120)
    domain = models.CharField(max_length=20, choices=CustomReportDomain.choices)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("organisation", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class ReportScheduleFrequency(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class ReportSchedule(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="report_schedules")
    template = models.ForeignKey(SavedReportTemplate, on_delete=models.CASCADE, related_name="schedules")
    frequency = models.CharField(max_length=10, choices=ReportScheduleFrequency.choices)
    recipients = models.TextField(help_text="Comma-separated email addresses")
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["template__name"]

    def __str__(self):
        return f"{self.template.name} ({self.frequency})"

    def recipient_list(self):
        return [e.strip() for e in self.recipients.split(",") if e.strip()]


class DailyFleetHealthScore(models.Model):
    """Composite fleet health score computed nightly per org (and optionally per depot)."""
    organisation           = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="fleet_health_scores")
    depot                  = models.ForeignKey(Depot, null=True, blank=True, on_delete=models.SET_NULL, related_name="fleet_health_scores")
    score_date             = models.DateField(db_index=True)
    score                  = models.FloatField()
    driver_component       = models.FloatField()
    alert_component        = models.FloatField()
    compliance_component   = models.FloatField()
    utilisation_component  = models.FloatField()
    created_at             = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("organisation", "depot", "score_date")]
        ordering = ["-score_date"]

    def __str__(self):
        return f"Fleet health {self.score_date}: {self.score:.1f}"

    @property
    def grade(self):
        if self.score >= 90:
            return "A"
        if self.score >= 75:
            return "B"
        if self.score >= 60:
            return "C"
        if self.score >= 45:
            return "D"
        return "F"


class CustomReportRun(models.Model):
    definition = models.ForeignKey(CustomReportDefinition, on_delete=models.CASCADE, related_name="runs")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="custom_report_runs"
    )
    status = models.CharField(max_length=20, choices=CustomReportStatus.choices, default=CustomReportStatus.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    artifact_path = models.CharField(max_length=500, blank=True)
    format = models.CharField(max_length=10, default="csv")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
