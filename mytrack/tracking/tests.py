import json

from django.test import TestCase, override_settings

from mytrack.tenancy.models import Organisation
from mytrack.tracking.models import Alert, AlertKind
from mytrack.vehicles.models import Vehicle


@override_settings(INGEST_API_TOKEN="dev-ingest-token", TRACCAR_DEFAULT_ORG_SLUG="test-org")
class TraccarEventMappingTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Test Org", slug="test-org")
        self.vehicle = Vehicle.objects.create(
            organisation=self.org,
            registration="ABC123GP",
            label="ABC123GP",
        )

    def _post_traccar(self, attributes):
        payload = {
            "lat": -26.2041,
            "lon": 28.0473,
            "deviceName": self.vehicle.registration,
            "speed": 0,
            "fixTime": "2026-05-11T10:00:00Z",
            "attributes": attributes,
        }
        return self.client.post(
            "/api/ingest/traccar/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer dev-ingest-token",
        )

    def test_maps_harsh_braking_alarm(self):
        res = self._post_traccar({"alarmType": "hard_brake"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            Alert.objects.filter(vehicle=self.vehicle, kind=AlertKind.HARSH_BRAKING).exists()
        )

    def test_unknown_alarm_maps_to_camera_event(self):
        res = self._post_traccar({"alarmType": "ignition_on"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            Alert.objects.filter(vehicle=self.vehicle, kind=AlertKind.CAMERA_EVENT).exists()
        )

    def test_deduplicates_open_traccar_event_alerts(self):
        self._post_traccar({"alarmType": "seatbelt"})
        self._post_traccar({"alarmType": "seatbelt"})
        self.assertEqual(
            Alert.objects.filter(vehicle=self.vehicle, kind=AlertKind.SEATBELT).count(),
            1,
        )


class RoadMaxspeedTests(TestCase):
    def test_numeric_kmh(self):
        from mytrack.tracking.road_maxspeed import maxspeed_tag_to_kmh

        self.assertEqual(maxspeed_tag_to_kmh("80"), 80.0)
        self.assertEqual(maxspeed_tag_to_kmh("80 km/h"), 80.0)

    def test_mph_tags_ignored_sa_kmh_only(self):
        from mytrack.tracking.road_maxspeed import maxspeed_tag_to_kmh

        self.assertIsNone(maxspeed_tag_to_kmh("50 mph"))
        self.assertIsNone(maxspeed_tag_to_kmh("30mph"))

    def test_za_tokens(self):
        from mytrack.tracking.road_maxspeed import maxspeed_tag_to_kmh

        self.assertEqual(maxspeed_tag_to_kmh("ZA:urban"), 60.0)
        self.assertEqual(maxspeed_tag_to_kmh("ZA:rural"), 100.0)
        self.assertEqual(maxspeed_tag_to_kmh("ZA:motorway"), 120.0)

    def test_range_uses_minimum(self):
        from mytrack.tracking.road_maxspeed import maxspeed_tag_to_kmh

        self.assertEqual(maxspeed_tag_to_kmh("100;120"), 100.0)

    def test_highway_defaults(self):
        from mytrack.tracking.road_maxspeed import default_kmh_for_highway

        self.assertEqual(default_kmh_for_highway("motorway"), 120.0)
        self.assertEqual(default_kmh_for_highway("residential"), 60.0)
        self.assertIsNone(default_kmh_for_highway("footway"))

    def test_resolve_segment_prefers_tag(self):
        from mytrack.tracking.road_maxspeed import resolve_segment_limit_kmh

        self.assertEqual(resolve_segment_limit_kmh("motorway", "100"), 100.0)
        self.assertEqual(resolve_segment_limit_kmh("motorway", None), 120.0)

