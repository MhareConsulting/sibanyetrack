from datetime import date

from django.db import models

from mytrack.vehicles.models import Vehicle


class TankCalibration(models.Model):
    """
    Per-vehicle probe calibration profile. Stores the empirical strapping table
    produced by the Fuel Calibration tool (raw sensor output → measured litres)
    together with the physical blind areas at the bottom and top of the tank.
    """

    vehicle             = models.OneToOneField(
        Vehicle, on_delete=models.CASCADE, related_name='tank_calibration',
    )
    bottom_blind_litres = models.FloatField(
        default=0.0,
        help_text='Volume (L) in the unreadable dead-zone at the bottom of the tank',
    )
    top_blind_litres    = models.FloatField(
        default=0.0,
        help_text='Expansion space (L) at the top of the tank the probe cannot reach',
    )
    poly_coefficients   = models.JSONField(
        null=True, blank=True,
        help_text='Degree-N polynomial coefficients (highest power first) fitted from the strapping table',
    )
    poly_max_n          = models.FloatField(
        null=True, blank=True,
        help_text='Maximum raw sensor value used during polynomial fitting (for clamping)',
    )
    notes               = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Calibration — {self.vehicle} ({self.points.count()} pts)"


class CalibrationPoint(models.Model):
    """
    A single (raw_value, litres) coordinate in a tank's strapping table.
    raw_value is whatever unit the probe outputs — percentage, volts, or raw integer.
    """

    calibration = models.ForeignKey(TankCalibration, on_delete=models.CASCADE, related_name='points')
    raw_value   = models.FloatField(help_text='Sensor output at this calibration step')
    litres      = models.FloatField(help_text='Actual measured volume (L) at this step')

    class Meta:
        ordering = ['raw_value']
        unique_together = [('calibration', 'raw_value')]

    def __str__(self):
        return f"raw={self.raw_value} → {self.litres} L"


class FuelSource(models.TextChoices):
    CAN   = 'can',   'CAN bus (ECU)'
    OBD   = 'obd',   'OBD-II'
    PROBE = 'probe', 'Analog/LLS probe'
    EST   = 'est',   'Estimated (% × capacity)'


class FuelReading(models.Model):
    """Raw fuel level sample from a probe, recorded on every GPS ping that carries fuel data."""

    vehicle           = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='fuel_readings')
    fuel_level_litres = models.FloatField()
    source            = models.CharField(
        max_length=5, choices=FuelSource.choices, default=FuelSource.PROBE, db_index=True,
        help_text='Where this reading came from — CAN/OBD vehicles bypass the strapping table',
    )
    fuel_level_pct    = models.FloatField(
        null=True, blank=True,
        help_text='Raw OEM/OBD fuel level percentage — preserved for audit + UI',
    )
    total_fuel_used_litres = models.FloatField(
        null=True, blank=True,
        help_text='Monotonic ECU counter snapshot of litres burned since reset',
    )
    fuel_rate_lph     = models.FloatField(
        null=True, blank=True,
        help_text='Instantaneous burn rate (L/h) when the ECU provides it',
    )
    raw_sensor_value  = models.FloatField(
        null=True, blank=True,
        help_text='Pre-calibration sensor output — preserved for diagnostics',
    )
    speed_kmh         = models.FloatField(null=True, blank=True)
    lat               = models.FloatField(null=True, blank=True)
    lon               = models.FloatField(null=True, blank=True)
    driver_name       = models.CharField(max_length=200, blank=True)
    device_timestamp  = models.DateTimeField(db_index=True)
    received_at       = models.DateTimeField(auto_now_add=True)
    tracked_trip      = models.ForeignKey(
        'tracking.TrackedTrip', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='fuel_readings',
    )

    class Meta:
        ordering = ['-device_timestamp']
        indexes = [models.Index(fields=['vehicle', 'device_timestamp'])]

    def __str__(self):
        return f"{self.vehicle} — {self.fuel_level_litres:.1f} L @ {self.device_timestamp}"


class FuelEventKind(models.TextChoices):
    REFUEL            = 'refuel', 'Refuel'
    THEFT             = 'theft',  'Fuel Theft'
    DRAIN             = 'drain',  'Unexplained Drain'
    PROBE_FAULT       = 'probe',  'Probe Fault'
    EXCESS_CONSUMPTION = 'excess', 'Excess Consumption'


class FuelEvent(models.Model):
    """
    Detected fuel anomaly. Created automatically by the detection engine.
    Operators can acknowledge theft/drain events after investigation.
    """

    vehicle       = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='fuel_events')
    kind          = models.CharField(max_length=10, choices=FuelEventKind.choices, db_index=True)
    occurred_at   = models.DateTimeField(db_index=True)
    level_before  = models.FloatField(help_text='Fuel level (L) before event')
    level_after   = models.FloatField(help_text='Fuel level (L) after event')
    delta_litres  = models.FloatField(help_text='Change in litres (+refuel, −drain/theft)')
    driver_name   = models.CharField(max_length=200, blank=True)
    lat           = models.FloatField(null=True, blank=True)
    lon           = models.FloatField(null=True, blank=True)
    acknowledged  = models.BooleanField(default=False)
    notes         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [models.Index(fields=['vehicle', 'occurred_at'])]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.vehicle} {self.delta_litres:+.1f} L @ {self.occurred_at}"


class FuelPriceHistory(models.Model):
    """Monthly SA fuel prices per litre (ZAR), sourced from AA or entered manually."""

    organisation       = models.ForeignKey('tenancy.Organisation', on_delete=models.CASCADE, related_name='fuel_price_history')
    effective_from     = models.DateField(db_index=True)
    petrol_95_zar      = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    petrol_93_zar      = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    diesel_500ppm_zar  = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    diesel_50ppm_zar   = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    source             = models.CharField(max_length=60, default='manual')  # 'aa_scrape' or 'manual'
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('organisation', 'effective_from')]
        ordering = ['-effective_from']

    def __str__(self):
        return f"Fuel prices {self.effective_from} ({self.organisation})"

    @classmethod
    def current_for_org(cls, org, as_of=None):
        as_of = as_of or date.today()
        return cls.objects.filter(organisation=org, effective_from__lte=as_of).order_by('-effective_from').first()
