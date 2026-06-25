from datetime import timedelta

from django.db import models
from django.utils import timezone


CHECKLIST_ITEMS = [
    ('tyres',        'Tyres & Wheels'),
    ('lights',       'Lights & Indicators'),
    ('brakes',       'Brakes'),
    ('fuel',         'Fuel Level'),
    ('oil',          'Oil Level'),
    ('windscreen',   'Windscreen & Wipers'),
    ('mirrors',      'Mirrors'),
    ('fire_ext',     'Fire Extinguisher'),
    ('first_aid',    'First Aid Kit'),
    ('documents',    'Vehicle Documents'),
]


class InspectionLog(models.Model):
    class InspectionType(models.TextChoices):
        PRE_TRIP  = 'pre_trip',  'Pre-Trip'
        POST_TRIP = 'post_trip', 'Post-Trip'

    class Result(models.TextChoices):
        PASS   = 'pass',   'Pass'
        DEFECT = 'defect', 'Defect Noted'
        FAIL   = 'fail',   'Fail'

    vehicle         = models.ForeignKey('vehicles.Vehicle', on_delete=models.CASCADE, related_name='inspections')
    driver_name     = models.CharField(max_length=200, blank=True)
    inspection_type = models.CharField(max_length=10, choices=InspectionType.choices)
    result          = models.CharField(max_length=10, choices=Result.choices)
    checklist       = models.JSONField(default=dict)
    defects         = models.TextField(blank=True)
    odometer_km     = models.FloatField(null=True, blank=True)
    notes           = models.TextField(blank=True)
    submitted_at    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-submitted_at']
        indexes = [models.Index(fields=['vehicle', 'submitted_at'])]

    def __str__(self):
        return f"{self.vehicle} — {self.get_inspection_type_display()} — {self.submitted_at:%Y-%m-%d}"


class DocumentKind(models.TextChoices):
    COF          = 'cof',          'Certificate of Fitness'
    LICENCE_DISC = 'licence_disc', 'Licence Disc'
    INSURANCE    = 'insurance',    'Insurance'
    ROADWORTHY   = 'roadworthy',   'Roadworthy Certificate'
    OTHER        = 'other',        'Other'


class VehicleDocument(models.Model):
    vehicle      = models.ForeignKey('vehicles.Vehicle', on_delete=models.CASCADE, related_name='documents')
    kind         = models.CharField(max_length=20, choices=DocumentKind.choices)
    label        = models.CharField(max_length=100, blank=True, help_text="Optional custom label")
    file         = models.FileField(upload_to='vehicle_docs/%Y/%m/')
    expiry_date  = models.DateField(null=True, blank=True)
    warning_days = models.PositiveIntegerField(
        default=30,
        help_text="Days before expiry to start showing a warning for this document",
    )
    notes        = models.TextField(blank=True)
    uploaded_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.vehicle} — {self.get_kind_display()}"

    @property
    def days_remaining(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.now().date()).days

    @property
    def expiry_status(self):
        days = self.days_remaining
        if days is None:
            return 'unknown'
        if days < 0:
            return 'expired'
        if days <= self.warning_days:
            return 'warning'
        return 'ok'


class ServiceSchedule(models.Model):
    """Odometer-based or time-based (or both) service interval for a vehicle."""

    vehicle           = models.ForeignKey('vehicles.Vehicle', on_delete=models.CASCADE, related_name='service_schedules')
    name              = models.CharField(max_length=100, help_text="e.g. Oil Change, 15 000 km Service")
    interval_km       = models.PositiveIntegerField(help_text="Service repeat interval in km")
    last_service_km   = models.FloatField(null=True, blank=True, help_text="Odometer reading when last serviced")
    last_service_date = models.DateField(null=True, blank=True)
    interval_days     = models.PositiveIntegerField(null=True, blank=True, help_text="Days between services (optional)")
    last_serviced_at  = models.DateField(null=True, blank=True, help_text="Date of most recent service")
    notes             = models.TextField(blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['vehicle__registration', 'name']

    def __str__(self):
        return f"{self.vehicle} — {self.name}"

    @property
    def next_due_km(self):
        if self.last_service_km is None:
            return None
        return self.last_service_km + self.interval_km

    @property
    def next_due_date(self):
        if self.interval_days and self.last_serviced_at:
            return self.last_serviced_at + timedelta(days=self.interval_days)
        return None

    @property
    def is_due_soon(self):
        """Returns True if due by km (within 1 000 km) OR by date (within 14 days)."""
        km_due = False
        if self.next_due_km is not None:
            current_odo = getattr(self.vehicle, "current_odometer_km", None) or 0
            km_due = (self.next_due_km - current_odo) <= 1000
        date_due = False
        if self.next_due_date:
            date_due = (self.next_due_date - timezone.now().date()).days <= 14
        return km_due or date_due
