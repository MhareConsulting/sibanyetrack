from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from mytrack.tenancy.mixins import SESSION_KEY
from mytrack.tenancy.models import Depot, Organisation, Role, UserDepotAccess
from mytrack.tracking.models import TrackedTrip, TripClassification
from mytrack.vehicles.models import Vehicle, VehicleState

User = get_user_model()


class MobileScopeTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Test Org", slug="test-org")
        self.depot_a = Depot.objects.create(organisation=self.org, name="Depot A")
        self.depot_b = Depot.objects.create(organisation=self.org, name="Depot B")
        self.admin = User.objects.create_user(
            username="admin1",
            password="pass",
            organisation=self.org,
            role=Role.ADMIN,
        )
        self.dispatcher = User.objects.create_user(
            username="disp1",
            password="pass",
            organisation=self.org,
            role=Role.DISPATCHER,
        )
        UserDepotAccess.objects.create(user=self.dispatcher, depot=self.depot_a)
        self.v_a = Vehicle.objects.create(
            organisation=self.org,
            registration="AA11AA",
            home_depot=self.depot_a,
        )
        self.v_b = Vehicle.objects.create(
            organisation=self.org,
            registration="BB22BB",
            home_depot=self.depot_b,
        )
        VehicleState.objects.create(
            vehicle=self.v_a,
            lat=-26.1,
            lon=28.0,
            last_seen=timezone.now(),
        )
        VehicleState.objects.create(
            vehicle=self.v_b,
            lat=-26.2,
            lon=28.1,
            last_seen=timezone.now(),
        )

    def test_dispatcher_sees_only_depot_vehicles(self):
        self.client.login(username="disp1", password="pass")
        res = self.client.get("/api/mobile/vehicles/")
        self.assertEqual(res.status_code, 200)
        regs = {v["registration"] for v in res.json()["vehicles"]}
        self.assertIn("AA11AA", regs)
        self.assertNotIn("BB22BB", regs)

    def test_admin_sees_all_with_session_all(self):
        session = self.client.session
        session[SESSION_KEY] = "all"
        session.save()
        self.client.login(username="admin1", password="pass")
        res = self.client.get("/api/mobile/vehicles/")
        regs = {v["registration"] for v in res.json()["vehicles"]}
        self.assertIn("AA11AA", regs)
        self.assertIn("BB22BB", regs)


class MobileTripApiTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="T Org", slug="t-org")
        self.user = User.objects.create_user(
            username="u1",
            password="pass",
            organisation=self.org,
            role=Role.ADMIN,
        )
        self.vehicle = Vehicle.objects.create(organisation=self.org, registration="CC33CC")
        self.trip = TrackedTrip.objects.create(
            vehicle=self.vehicle,
            started_at=timezone.now() - timedelta(hours=1),
            ended_at=timezone.now(),
            start_lat=-26.0,
            start_lon=28.0,
            classification=TripClassification.BUSINESS,
        )

    def test_patch_classification(self):
        self.client.login(username="u1", password="pass")
        res = self.client.patch(
            f"/api/mobile/trips/{self.trip.id}/classification/",
            data='{"classification": "personal"}',
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.classification, TripClassification.PERSONAL)

    def test_trips_filter_by_classification(self):
        TrackedTrip.objects.create(
            vehicle=self.vehicle,
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1, minutes=30),
            start_lat=-26.0,
            start_lon=28.0,
            classification=TripClassification.PERSONAL,
        )
        self.client.login(username="u1", password="pass")
        res = self.client.get("/api/mobile/trips/?classification=personal")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(all(t["classification"] == "personal" for t in res.json()["trips"]))


class MobilePageTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="P Org", slug="p-org")
        self.dispatcher = User.objects.create_user(
            username="disp2",
            password="pass",
            organisation=self.org,
            role=Role.DISPATCHER,
        )

    def test_mobile_home_requires_login(self):
        res = self.client.get("/app/")
        self.assertEqual(res.status_code, 302)

    def test_dispatcher_login_redirects_to_app(self):
        res = self.client.post(
            "/accounts/login/",
            {"username": "disp2", "password": "pass"},
        )
        self.assertRedirects(res, "/app/", fetch_redirect_response=False)
