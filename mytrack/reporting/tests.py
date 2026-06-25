from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from mytrack.fuel.models import FuelReading
from mytrack.geofences.models import Geofence, GeofenceEvent
from mytrack.tenancy.models import Organisation, Role
from mytrack.tracking.models import GPSPing, TrackedTrip
from mytrack.vehicles.models import Vehicle

from .management.commands.aggregate_daily_reports import Command as AggregateCommand
from .models import CustomReportDefinition, CustomReportRun, DailyFuelMetrics, DailyGeofenceMetrics, DailyVehicleMetrics

User = get_user_model()


class ReportingViewsTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Org", slug="org")
        self.user = User.objects.create_user(
            username="report-admin",
            password="pass12345",
            organisation=self.org,
            role=Role.ADMIN,
        )
        self.vehicle = Vehicle.objects.create(
            organisation=self.org,
            registration="REP123GP",
            label="REP123GP",
        )
        self.geofence = Geofence.objects.create(
            organisation=self.org,
            name="Main Depot",
            polygon=[[28.0, -26.0], [28.1, -26.0], [28.1, -26.1], [28.0, -26.1]],
        )
        now = timezone.now()
        trip = TrackedTrip.objects.create(
            vehicle=self.vehicle,
            driver_name="Driver A",
            started_at=now - timedelta(minutes=35),
            ended_at=now - timedelta(minutes=5),
            start_lat=-26.0,
            start_lon=28.0,
            end_lat=-26.05,
            end_lon=28.05,
            distance_km=12.3,
            max_speed_kmh=104,
            ping_count=8,
        )
        GPSPing.objects.create(
            vehicle=self.vehicle,
            lat=-26.0,
            lon=28.0,
            speed_kmh=65.0,
            device_timestamp=now - timedelta(minutes=35),
            tracked_trip=trip,
        )
        GPSPing.objects.create(
            vehicle=self.vehicle,
            lat=-26.05,
            lon=28.05,
            speed_kmh=72.0,
            device_timestamp=now - timedelta(minutes=5),
            tracked_trip=trip,
        )
        FuelReading.objects.create(
            vehicle=self.vehicle,
            fuel_level_litres=120.0,
            raw_sensor_value=420.0,
            device_timestamp=now - timedelta(minutes=30),
            tracked_trip=trip,
        )
        FuelReading.objects.create(
            vehicle=self.vehicle,
            fuel_level_litres=110.0,
            raw_sensor_value=401.0,
            device_timestamp=now - timedelta(minutes=2),
            tracked_trip=trip,
        )
        GeofenceEvent.objects.create(
            geofence=self.geofence,
            vehicle=self.vehicle,
            kind=GeofenceEvent.ENTER,
            driver_name="Driver A",
            lat=-26.01,
            lon=28.01,
            occurred_at=now - timedelta(minutes=25),
        )
        GeofenceEvent.objects.create(
            geofence=self.geofence,
            vehicle=self.vehicle,
            kind=GeofenceEvent.EXIT,
            driver_name="Driver A",
            lat=-26.02,
            lon=28.02,
            occurred_at=now - timedelta(minutes=10),
        )

    def test_common_report_view_and_csv_export(self):
        self.client.login(username="report-admin", password="pass12345")
        res = self.client.get(reverse("reporting-common", kwargs={"domain": "speed"}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Speed Report")

        today = timezone.localtime(timezone.now()).date().isoformat()
        csv_res = self.client.get(
            reverse("reporting-common", kwargs={"domain": "speed"})
            + f"?preview=1&date_from={today}&date_to={today}&vehicle={self.vehicle.id}&export=csv"
        )
        self.assertEqual(csv_res.status_code, 200)
        self.assertEqual(csv_res["Content-Type"], "text/csv")

    def test_export_requires_vehicle_when_range_exceeds_limit(self):
        self.client.login(username="report-admin", password="pass12345")
        start = (timezone.localtime(timezone.now()).date() - timedelta(days=10)).isoformat()
        end = timezone.localtime(timezone.now()).date().isoformat()
        res = self.client.get(
            reverse("reporting-common", kwargs={"domain": "speed"})
            + f"?preview=1&date_from={start}&date_to={end}&export=csv"
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Vehicle selection is required for exports longer than")
        self.assertEqual(res["Content-Type"], "text/html; charset=utf-8")

    def test_custom_builder_create_and_run(self):
        self.client.login(username="report-admin", password="pass12345")
        definition = CustomReportDefinition.objects.create(
            organisation=self.org,
            owner=self.user,
            name="Ops Speed",
            domain="speed",
            columns=["vehicle__registration", "distance_km", "max_speed_kmh"],
            metrics=[],
            group_by=[],
            filters={
                "date_from": timezone.localtime(timezone.now()).date().isoformat(),
                "date_to": timezone.localtime(timezone.now()).date().isoformat(),
                "vehicle": self.vehicle.id,
            },
            sort_by=["-max_speed_kmh"],
            schedule_config={"frequency": "daily", "hour": 6, "emails": []},
        )

        run_res = self.client.post(reverse("reporting-run-custom", kwargs={"report_id": definition.id}))
        self.assertEqual(run_res.status_code, 302)
        run = CustomReportRun.objects.filter(definition=definition).latest("id")
        self.assertEqual(run.status, "success")

    def test_custom_run_blocked_when_long_range_without_vehicle(self):
        self.client.login(username="report-admin", password="pass12345")
        definition = CustomReportDefinition.objects.create(
            organisation=self.org,
            owner=self.user,
            name="Long Range No Vehicle",
            domain="speed",
            columns=["vehicle__registration", "distance_km"],
            metrics=[],
            group_by=[],
            filters={"date_from": "2026-01-01", "date_to": "2026-01-20"},
            sort_by=[],
            schedule_config={"frequency": "daily", "hour": 6, "emails": []},
        )
        run_res = self.client.post(reverse("reporting-run-custom", kwargs={"report_id": definition.id}), follow=True)
        self.assertEqual(run_res.status_code, 200)
        self.assertContains(run_res, "Vehicle selection is required for custom report exports/runs longer than")
        self.assertFalse(CustomReportRun.objects.filter(definition=definition).exists())

    def test_custom_export_blocked_when_long_range_without_vehicle(self):
        self.client.login(username="report-admin", password="pass12345")
        definition = CustomReportDefinition.objects.create(
            organisation=self.org,
            owner=self.user,
            name="Long Export No Vehicle",
            domain="speed",
            columns=["vehicle__registration", "distance_km"],
            metrics=[],
            group_by=[],
            filters={"date_from": "2026-01-01", "date_to": "2026-01-20"},
            sort_by=[],
            schedule_config={"frequency": "daily", "hour": 6, "emails": []},
        )
        run = CustomReportRun.objects.create(definition=definition, requested_by=self.user)
        export_res = self.client.get(
            reverse("reporting-export-custom", kwargs={"run_id": run.id}) + "?format=csv",
            follow=True,
        )
        self.assertEqual(export_res.status_code, 200)
        self.assertContains(export_res, "Vehicle selection is required for custom report exports/runs longer than")

    def test_custom_builder_page_loads_with_legacy_string_json_fields(self):
        self.client.login(username="report-admin", password="pass12345")
        CustomReportDefinition.objects.create(
            organisation=self.org,
            owner=self.user,
            name="Legacy Def",
            domain="speed",
            columns="vehicle__registration",
            metrics="",
            group_by="",
            filters="",
            sort_by="",
            schedule_config="",
        )
        res = self.client.get(reverse("reporting-custom-builder"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Custom Report Builder")

    @override_settings(REPORTING_FEATURE_ENABLED=False)
    def test_feature_flag_disables_reporting(self):
        self.client.login(username="report-admin", password="pass12345")
        res = self.client.get(reverse("reporting-home"))
        self.assertEqual(res.status_code, 404)

    def test_aggregate_daily_command_populates_summary_tables(self):
        command = AggregateCommand()
        today = timezone.localtime(timezone.now()).date().isoformat()
        command.handle(date=today, date_from=None, date_to=None, org_slug=self.org.slug)

        self.assertTrue(DailyVehicleMetrics.objects.filter(vehicle=self.vehicle).exists())
        self.assertTrue(DailyFuelMetrics.objects.filter(vehicle=self.vehicle).exists())
        self.assertTrue(DailyGeofenceMetrics.objects.filter(vehicle=self.vehicle, geofence=self.geofence).exists())
