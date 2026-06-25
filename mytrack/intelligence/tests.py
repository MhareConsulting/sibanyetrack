from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mytrack.geofences.models import Geofence, GeofenceEvent
from mytrack.tenancy.models import Organisation, Role
from mytrack.tracking.models import Alert, AlertKind
from mytrack.vehicles.models import Vehicle


User = get_user_model()


class UnifiedEventsViewTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Org", slug="org")
        self.user = User.objects.create_user(
            username="dispatcher",
            password="pass12345",
            organisation=self.org,
            role=Role.ADMIN,
        )
        self.vehicle = Vehicle.objects.create(
            organisation=self.org,
            registration="XYZ789GP",
            label="XYZ789GP",
        )
        self.geofence = Geofence.objects.create(
            organisation=self.org,
            name="Depot A",
            polygon=[[28.0, -26.0], [28.1, -26.0], [28.1, -26.1], [28.0, -26.1]],
        )

    def test_unified_events_page_renders_mixed_sources(self):
        now = timezone.now()
        Alert.objects.create(
            vehicle=self.vehicle,
            kind=AlertKind.SPEEDING,
            value=130,
            threshold=120,
            occurred_at=now,
            driver_name="Driver A",
        )
        GeofenceEvent.objects.create(
            geofence=self.geofence,
            vehicle=self.vehicle,
            kind=GeofenceEvent.ENTER,
            driver_name="Driver A",
            lat=-26.05,
            lon=28.05,
            occurred_at=now - timedelta(minutes=1),
        )
        self.client.login(username="dispatcher", password="pass12345")
        res = self.client.get("/intelligence/events/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Speeding")
        self.assertContains(res, "Geofence")

    def test_filters_by_source(self):
        now = timezone.now()
        Alert.objects.create(
            vehicle=self.vehicle,
            kind=AlertKind.IDLE,
            value=15,
            threshold=10,
            occurred_at=now,
            driver_name="Driver B",
        )
        GeofenceEvent.objects.create(
            geofence=self.geofence,
            vehicle=self.vehicle,
            kind=GeofenceEvent.EXIT,
            driver_name="Driver B",
            lat=-26.05,
            lon=28.05,
            occurred_at=now,
        )
        self.client.login(username="dispatcher", password="pass12345")
        res = self.client.get("/intelligence/events/?source=alert")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Idle")
        self.assertNotContains(res, "Depot A")

