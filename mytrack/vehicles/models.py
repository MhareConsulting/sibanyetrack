from django.db import models
from django.utils import timezone

from mytrack.tenancy.models import Depot, Organisation


class VehicleFuelType(models.TextChoices):
    PETROL  = "petrol",   "Petrol"
    DIESEL  = "diesel",   "Diesel"
    ELECTRIC = "electric", "Electric"
    HYBRID  = "hybrid",   "Hybrid"


class Vehicle(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="vehicles")
    registration = models.CharField(max_length=20)
    label = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    fuel_tank_capacity_litres = models.FloatField(
        null=True, blank=True,
        help_text="Full tank capacity — used to convert % probe readings to litres",
    )
    fuel_source_pref = models.CharField(
        max_length=5,
        choices=[("auto", "Auto (best available)"), ("can", "CAN bus"), ("obd", "OBD-II"), ("probe", "Analog/LLS probe")],
        default="auto",
        help_text="Pin the fuel data source, or Auto to pick the best available per ping",
    )
    expected_fuel_lper100km = models.FloatField(
        null=True, blank=True,
        help_text="Expected fuel consumption (L/100 km). Used to flag excessive consumption.",
    )
    fuel_type = models.CharField(
        max_length=10, choices=VehicleFuelType.choices, default=VehicleFuelType.DIESEL,
        help_text="Fuel type — used for CO₂ calculations",
    )
    co2_per_litre = models.DecimalField(
        max_digits=6, decimal_places=3, default="2.640",
        help_text="kg CO₂ per litre (Diesel: 2.640, Petrol 95: 2.310)",
    )
    home_depot = models.ForeignKey(
        Depot, null=True, blank=True, on_delete=models.SET_NULL, related_name="vehicles"
    )

    class Meta:
        unique_together = [("organisation", "registration")]

    def __str__(self):
        return self.label or self.registration

    @property
    def current_depot(self):
        """Active borrow assignment takes priority; otherwise home depot."""
        active = (
            self.depot_assignments
            .filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=timezone.now().date()))
            .order_by("-start_date")
            .first()
        )
        return active.depot if active else self.home_depot


class VehicleState(models.Model):
    """Latest known position — one row per vehicle, upserted on every ping."""

    vehicle = models.OneToOneField(Vehicle, on_delete=models.CASCADE, related_name="state")
    lat = models.FloatField()
    lon = models.FloatField()
    speed_kmh = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    driver_name = models.CharField(max_length=200, blank=True)
    myroutes_trip_id = models.IntegerField(null=True, blank=True)
    last_seen = models.DateTimeField()
    last_address = models.TextField(blank=True, default="")
    address_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.vehicle} @ {self.last_seen}"


class AssignmentKind(models.TextChoices):
    BORROW = "borrow", "Borrow"
    TRANSFER = "transfer", "Transfer"


class Device(models.Model):
    """GPS hardware unit linked to an organisation and optionally to a vehicle."""

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="devices")
    imei = models.CharField(max_length=30, unique=True)
    model_name = models.CharField(max_length=60, blank=True, help_text="e.g. Teltonika FM3622")
    phone_number = models.CharField(max_length=20, blank=True)
    vehicle = models.OneToOneField(
        Vehicle, null=True, blank=True, on_delete=models.SET_NULL, related_name="device"
    )
    last_activity = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_activity"]

    def __str__(self):
        return f"{self.imei} ({self.model_name or 'Unknown model'})"

    @property
    def status(self):
        if not self.last_activity:
            return "offline"
        from django.utils import timezone
        secs = (timezone.now() - self.last_activity).total_seconds()
        if secs < 120:
            return "online"
        if secs < 600:
            return "stale"
        return "offline"


class VehicleDepotAssignment(models.Model):
    """Records a vehicle being borrowed to or permanently transferred to another depot."""

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="depot_assignments")
    depot = models.ForeignKey(Depot, on_delete=models.CASCADE, related_name="vehicle_assignments")
    kind = models.CharField(max_length=10, choices=AssignmentKind.choices)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True, help_text="Leave blank for open-ended borrow or transfer.")
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        end = self.end_date or "open"
        return f"{self.vehicle} → {self.depot} ({self.kind}, {self.start_date}–{end})"
