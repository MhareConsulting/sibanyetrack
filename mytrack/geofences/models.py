from django.db import models

from mytrack.tenancy.models import Organisation
from mytrack.vehicles.models import Vehicle


class Geofence(models.Model):
    """Polygon geofence — boundary defined as a list of [lon, lat] pairs."""

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="geofences")
    name = models.CharField(max_length=200)
    polygon = models.JSONField(
        default=list,
        help_text="List of [lon, lat] coordinate pairs forming a closed polygon.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Business-hours restriction
    enforce_hours = models.BooleanField(
        default=False,
        help_text="Only alert on entry outside the defined hours / days.",
    )
    hours_start = models.TimeField(null=True, blank=True, help_text="Authorised entry start (local time)")
    hours_end = models.TimeField(null=True, blank=True, help_text="Authorised entry end (local time)")
    active_days = models.CharField(
        max_length=13, default="0,1,2,3,4",
        help_text="CSV of weekday integers (Mon=0) when entry is authorised.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def contains(self, lat, lon):
        """Point-in-polygon using ray casting. polygon is [[lon, lat], ...]."""
        poly = self.polygon
        if len(poly) < 3:
            return False
        x, y = lon, lat
        inside = False
        j = len(poly) - 1
        for i in range(len(poly)):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside


class GeofenceEvent(models.Model):
    ENTER = "enter"
    EXIT = "exit"
    KIND_CHOICES = [(ENTER, "Enter"), (EXIT, "Exit")]

    geofence = models.ForeignKey(Geofence, on_delete=models.CASCADE, related_name="events")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="geofence_events")
    kind = models.CharField(max_length=5, choices=KIND_CHOICES)
    driver_name = models.CharField(max_length=200, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    occurred_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["geofence", "vehicle", "occurred_at"]),
            models.Index(fields=["vehicle", "kind", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.vehicle} {self.kind} {self.geofence} @ {self.occurred_at}"


class VehicleGeofenceState(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    geofence = models.ForeignKey(Geofence, on_delete=models.CASCADE)
    inside = models.BooleanField(default=False)

    class Meta:
        unique_together = [("vehicle", "geofence")]


def _is_authorised_entry(fence, occurred_at):
    """Return True if the entry is within the geofence's defined business hours."""
    if not fence.enforce_hours:
        return True
    if not fence.hours_start or not fence.hours_end:
        return True
    try:
        from zoneinfo import ZoneInfo
        local = occurred_at.astimezone(ZoneInfo("Africa/Johannesburg"))
    except Exception:
        local = occurred_at
    weekday = str(local.weekday())
    allowed_days = [d.strip() for d in fence.active_days.split(",")]
    if weekday not in allowed_days:
        return False
    return fence.hours_start <= local.time() <= fence.hours_end


def check_geofences(vehicle, lat, lon, driver_name, occurred_at):
    """Called after every ingest ping. Fires enter/exit events on boundary crossings."""
    active_fences = Geofence.objects.filter(organisation=vehicle.organisation, is_active=True)

    for fence in active_fences:
        inside_now = fence.contains(lat, lon)
        state, _ = VehicleGeofenceState.objects.get_or_create(
            vehicle=vehicle, geofence=fence, defaults={"inside": False}
        )

        if inside_now and not state.inside:
            GeofenceEvent.objects.create(
                geofence=fence, vehicle=vehicle, kind=GeofenceEvent.ENTER,
                driver_name=driver_name, lat=lat, lon=lon, occurred_at=occurred_at,
            )
            state.inside = True
            state.save(update_fields=["inside"])
            try:
                from mytrack.webhooks.dispatch import fire_webhook
                fire_webhook(vehicle.organisation, "geofence.entry", {
                    "geofence_id": fence.pk,
                    "geofence_name": fence.name,
                    "vehicle_reg": vehicle.registration,
                    "driver": driver_name,
                    "occurred_at": str(occurred_at),
                    "lat": lat, "lon": lon,
                })
            except Exception:
                pass

            # After-hours alert when entry is outside authorised window
            if not _is_authorised_entry(fence, occurred_at):
                from mytrack.tracking.models import Alert, AlertKind, AlertSeverity, default_severity_for_kind
                Alert.objects.get_or_create(
                    vehicle=vehicle,
                    kind=AlertKind.GEOFENCE_AFTER_HOURS,
                    resolved_at__isnull=True,
                    occurred_at__gte=occurred_at.replace(hour=0, minute=0, second=0, microsecond=0),
                    defaults={
                        "severity": default_severity_for_kind(AlertKind.GEOFENCE_AFTER_HOURS),
                        "value": 1.0,
                        "threshold": 0.0,
                        "occurred_at": occurred_at,
                        "driver_name": driver_name,
                    },
                )

        elif not inside_now and state.inside:
            GeofenceEvent.objects.create(
                geofence=fence, vehicle=vehicle, kind=GeofenceEvent.EXIT,
                driver_name=driver_name, lat=lat, lon=lon, occurred_at=occurred_at,
            )
            state.inside = False
            state.save(update_fields=["inside"])
