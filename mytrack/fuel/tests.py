from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from mytrack.tenancy.models import Organisation
from mytrack.vehicles.models import Vehicle

from .detection import check_fuel_events
from .models import (
    CalibrationPoint,
    FuelEvent,
    FuelEventKind,
    FuelReading,
    FuelSource,
    TankCalibration,
)


class FuelResolverTests(TestCase):
    """ingest._resolve_fuel + extract_fuel_signals source resolution."""

    def setUp(self):
        self.org = Organisation.objects.create(name="Org", slug="org")
        self.vehicle = Vehicle.objects.create(
            organisation=self.org, registration="CAN001GP", fuel_tank_capacity_litres=100.0,
        )

    def test_extract_signals_from_traccar_attributes(self):
        from mytrack.tracking.ingest import extract_fuel_signals
        sig = extract_fuel_signals({"fuel": 50.0, "fuelUsed": 1234.0, "fuelConsumption": 7.2})
        self.assertEqual(sig["level_pct"], 50.0)
        self.assertEqual(sig["total_used_l"], 1234.0)
        self.assertEqual(sig["rate_lph"], 7.2)

    def test_can_pct_resolves_to_litres_without_calibration(self):
        from mytrack.tracking.ingest import _resolve_fuel
        r = _resolve_fuel(self.vehicle, level_pct=50.0, total_used=10.0)
        self.assertEqual(r.source, FuelSource.CAN)
        self.assertEqual(r.litres, 50.0)          # 50% × 100 L
        self.assertEqual(r.total_used, 10.0)

    def test_obd_pct_without_counter_is_obd_source(self):
        from mytrack.tracking.ingest import _resolve_fuel
        r = _resolve_fuel(self.vehicle, level_pct=25.0)
        self.assertEqual(r.source, FuelSource.OBD)
        self.assertEqual(r.litres, 25.0)

    def test_probe_raw_uses_calibration(self):
        cal = TankCalibration.objects.create(vehicle=self.vehicle)
        CalibrationPoint.objects.create(calibration=cal, raw_value=0, litres=0)
        CalibrationPoint.objects.create(calibration=cal, raw_value=100, litres=100)
        from mytrack.tracking.ingest import _resolve_fuel
        r = _resolve_fuel(self.vehicle, raw_value=40.0)
        self.assertEqual(r.source, FuelSource.PROBE)
        self.assertEqual(r.litres, 40.0)
        self.assertEqual(r.raw, 40.0)


class CanDetectionTests(TestCase):
    """CAN/OBD cross-check detection in _detect_can_path."""

    def setUp(self):
        self.org = Organisation.objects.create(name="Org", slug="org")
        self.vehicle = Vehicle.objects.create(
            organisation=self.org, registration="CAN002GP", fuel_tank_capacity_litres=100.0,
        )
        self.now = timezone.now()

    def _can_reading(self, minutes_ago, litres, counter, speed=0.0, save_only=False):
        r = FuelReading.objects.create(
            vehicle=self.vehicle,
            fuel_level_litres=litres,
            source=FuelSource.CAN,
            total_fuel_used_litres=counter,
            speed_kmh=speed,
            device_timestamp=self.now - timedelta(minutes=minutes_ago),
        )
        if not save_only:
            check_fuel_events(self.vehicle, r)
        return r

    def _seed_baseline(self, litres, counter):
        for m in (9, 8, 7, 6, 5):
            self._can_reading(m, litres, counter, save_only=True)

    def test_theft_when_level_drop_exceeds_ecu_burn(self):
        self._seed_baseline(100.0, 1000.0)
        # Level falls 30 L but the ECU only burned 2 L → 28 L unaccounted.
        self._can_reading(0, 70.0, 1002.0, speed=0.0)
        self.assertEqual(FuelEvent.objects.filter(kind=FuelEventKind.THEFT).count(), 1)

    def test_no_event_when_drop_matches_ecu_burn(self):
        self._seed_baseline(100.0, 1000.0)
        # Level falls 28 L and the ECU burned ~28 L → normal consumption, no alert.
        self._can_reading(0, 72.0, 1028.0, speed=80.0)
        self.assertFalse(FuelEvent.objects.filter(kind__in=[FuelEventKind.THEFT, FuelEventKind.DRAIN]).exists())

    def test_refuel_when_level_rises_without_burn(self):
        self._seed_baseline(20.0, 500.0)
        self._can_reading(0, 60.0, 500.0, speed=0.0)
        self.assertEqual(FuelEvent.objects.filter(kind=FuelEventKind.REFUEL).count(), 1)

    def test_can_zero_reading_does_not_raise_probe_fault(self):
        self._seed_baseline(100.0, 1000.0)
        self._can_reading(0, 0.0, 1002.0, speed=0.0)
        self.assertFalse(FuelEvent.objects.filter(kind=FuelEventKind.PROBE_FAULT).exists())


class ProbeRegressionTests(TestCase):
    """Existing analog-probe behaviour must still fire for probe-sourced readings."""

    def setUp(self):
        self.org = Organisation.objects.create(name="Org", slug="org")
        self.vehicle = Vehicle.objects.create(organisation=self.org, registration="PRB001GP")
        self.now = timezone.now()

    def test_probe_zero_after_nonempty_raises_probe_fault(self):
        FuelReading.objects.create(
            vehicle=self.vehicle, fuel_level_litres=60.0, source=FuelSource.PROBE,
            raw_sensor_value=300.0, device_timestamp=self.now - timedelta(minutes=5),
        )
        zero = FuelReading.objects.create(
            vehicle=self.vehicle, fuel_level_litres=0.0, source=FuelSource.PROBE,
            raw_sensor_value=0.0, device_timestamp=self.now,
        )
        check_fuel_events(self.vehicle, zero)
        self.assertEqual(FuelEvent.objects.filter(kind=FuelEventKind.PROBE_FAULT).count(), 1)
