from django.db import models
from django.utils import timezone

from mytrack.tenancy.models import Organisation
from mytrack.vehicles.models import Vehicle


class LicenceClass(models.TextChoices):
    CODE_8 = "C8", "Code 8 (Motor vehicle)"
    CODE_10 = "C10", "Code 10 (Heavy motor vehicle)"
    CODE_14 = "C14", "Code 14 (Extra-heavy)"
    EB = "EB", "Code EB (Motor vehicle with trailer)"


class Driver(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="drivers")
    full_name = models.CharField(max_length=200)
    id_number = models.CharField(max_length=13, blank=True, help_text="SA ID number")
    phone_e164 = models.CharField(max_length=16, blank=True, help_text="E.164 e.g. +27821234567")
    licence_code = models.CharField(max_length=4, choices=LicenceClass.choices, blank=True)
    licence_expiry = models.DateField(null=True, blank=True)
    pdp_number = models.CharField(max_length=30, blank=True, help_text="Professional Driving Permit number")
    pdp_expiry = models.DateField(null=True, blank=True)
    default_vehicle = models.ForeignKey(
        Vehicle, null=True, blank=True, on_delete=models.SET_NULL, related_name="default_drivers"
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.full_name

    @property
    def licence_days_remaining(self):
        if not self.licence_expiry:
            return None
        return (self.licence_expiry - timezone.now().date()).days

    @property
    def pdp_days_remaining(self):
        if not self.pdp_expiry:
            return None
        return (self.pdp_expiry - timezone.now().date()).days

    @property
    def licence_status(self):
        days = self.licence_days_remaining
        if days is None:
            return "unknown"
        if days < 0:
            return "expired"
        if days <= 30:
            return "warning"
        return "ok"

    @property
    def pdp_status(self):
        days = self.pdp_days_remaining
        if days is None:
            return "unknown"
        if days < 0:
            return "expired"
        if days <= 30:
            return "warning"
        return "ok"

    @property
    def latest_score(self):
        return self.scores.order_by("-scored_date").first()


class DriverScore(models.Model):
    """Daily composite driving score (0–100, higher = safer) for a driver."""

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="scores")
    scored_date = models.DateField(db_index=True)
    score = models.PositiveSmallIntegerField()

    # Raw component counts used to build the score
    trips = models.PositiveSmallIntegerField(default=0)
    distance_km = models.FloatField(default=0.0)
    speeding_events = models.PositiveSmallIntegerField(default=0)
    harsh_accel_events = models.PositiveSmallIntegerField(default=0)
    idling_minutes = models.FloatField(default=0.0)

    class Meta:
        unique_together = [("driver", "scored_date")]
        ordering = ["-scored_date"]

    def __str__(self):
        return f"{self.driver} {self.scored_date} → {self.score}"
