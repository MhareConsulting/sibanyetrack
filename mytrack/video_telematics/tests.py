import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from mytrack.tenancy.models import Depot, Organisation, Role
from mytrack.tracking.models import Alert, AlertKind
from mytrack.video_telematics.correlation import correlate_asset_to_alert
from mytrack.video_telematics.models import (
    ClipRequest,
    ClipRequestStatus,
    IngestSource,
    VideoAsset,
    VideoChannel,
    VideoTrigger,
)
from mytrack.video_telematics.traccar_media import register_clip_from_traccar_attributes
from mytrack.vehicles.models import Vehicle


User = get_user_model()


def _make_org_vehicle(slug="test-org", reg="CAM001"):
    org = Organisation.objects.create(name=slug, slug=slug)
    vehicle = Vehicle.objects.create(organisation=org, registration=reg)
    return org, vehicle


def _make_alert(vehicle, kind=AlertKind.HARSH_BRAKING, delta=0):
    return Alert.objects.create(
        vehicle=vehicle,
        kind=kind,
        value=120,
        threshold=100,
        occurred_at=timezone.now() + timedelta(seconds=delta),
        driver_name="Test Driver",
    )


def _make_asset(vehicle, org, delta=0, alert=None):
    return VideoAsset.objects.create(
        organisation=org,
        vehicle=vehicle,
        occurred_at=timezone.now() + timedelta(seconds=delta),
        trigger_type=VideoTrigger.UNKNOWN,
        ingest_source=IngestSource.WEBHOOK,
        playback_url="https://example.invalid/clip.mp4",
        alert=alert,
    )


# ── Existing webhook tests ────────────────────────────────────────────────────

class VideoWebhookApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.org, self.vehicle = _make_org_vehicle()

    def test_webhook_unauthorized(self):
        res = self.client.post(
            "/api/video/webhook/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 401)

    def test_webhook_playback_url_creates_asset(self):
        payload = {
            "org_slug": "test-org",
            "vehicle_registration": "CAM001",
            "playback_url": "https://example.invalid/clips/a.mp4",
            "external_id": "vendor-clip-1",
            "trigger_type": VideoTrigger.SPEEDING,
        }
        res = self.client.post(
            "/api/video/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer dev-ingest-token",
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(VideoAsset.objects.count(), 1)
        a = VideoAsset.objects.first()
        self.assertEqual(a.playback_url, payload["playback_url"])
        self.assertEqual(a.ingest_source, IngestSource.WEBHOOK)

    def test_webhook_idempotent_external_id(self):
        payload = {
            "org_slug": "test-org",
            "vehicle_id": self.vehicle.pk,
            "playback_url": "https://example.invalid/clips/b.mp4",
            "external_id": "same-id",
        }
        auth = {"HTTP_AUTHORIZATION": "Bearer dev-ingest-token"}
        self.client.post(
            "/api/video/webhook/", data=json.dumps(payload), content_type="application/json", **auth
        )
        self.client.post(
            "/api/video/webhook/", data=json.dumps(payload), content_type="application/json", **auth
        )
        self.assertEqual(VideoAsset.objects.count(), 1)


# ── Video trigger choices ─────────────────────────────────────────────────────

class VideoTriggerChoicesTests(TestCase):
    def setUp(self):
        self.org, self.vehicle = _make_org_vehicle("trigger-org", "TR01")

    def _post(self, trigger):
        return self.client.post(
            "/api/video/webhook/",
            data=json.dumps({
                "org_slug": "trigger-org",
                "vehicle_registration": "TR01",
                "playback_url": "https://example.invalid/x.mp4",
                "trigger_type": trigger,
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer dev-ingest-token",
        )

    def test_new_trigger_types_accepted(self):
        for trigger in ["phone_use", "fatigue", "seatbelt", "harsh_braking", "lane_departure"]:
            VideoAsset.objects.all().delete()
            res = self._post(trigger)
            self.assertEqual(res.status_code, 200, f"Failed for {trigger}")
            asset = VideoAsset.objects.first()
            self.assertEqual(asset.trigger_type, trigger)

    def test_unknown_trigger_fallback(self):
        res = self._post("invented_trigger_xyz")
        self.assertEqual(res.status_code, 200)
        asset = VideoAsset.objects.first()
        self.assertEqual(asset.trigger_type, VideoTrigger.UNKNOWN)


# ── Alert correlation ─────────────────────────────────────────────────────────

class AlertCorrelationTests(TestCase):
    def setUp(self):
        self.org, self.vehicle = _make_org_vehicle("corr-org", "CR01")

    @override_settings(VIDEO_ALERT_CORRELATION_WINDOW_MINUTES=5)
    def test_correlates_to_nearest_alert_within_window(self):
        # Alert 2 minutes before the clip — inside 5-min window
        alert_near = _make_alert(self.vehicle, delta=-120)
        # Alert 7 minutes before — outside window
        _make_alert(self.vehicle, delta=-420)

        asset = _make_asset(self.vehicle, self.org)
        matched = correlate_asset_to_alert(asset)

        self.assertTrue(matched)
        asset.refresh_from_db()
        self.assertEqual(asset.alert_id, alert_near.pk)

    @override_settings(VIDEO_ALERT_CORRELATION_WINDOW_MINUTES=5)
    def test_no_correlation_when_no_alert_in_window(self):
        _make_alert(self.vehicle, delta=-600)  # 10 min ago — outside window
        asset = _make_asset(self.vehicle, self.org)
        matched = correlate_asset_to_alert(asset)
        self.assertFalse(matched)
        asset.refresh_from_db()
        self.assertIsNone(asset.alert_id)

    @override_settings(VIDEO_ALERT_CORRELATION_WINDOW_MINUTES=5)
    def test_does_not_overwrite_existing_alert_link(self):
        alert1 = _make_alert(self.vehicle, delta=-30)
        _make_alert(self.vehicle, delta=0)  # closer but should be ignored
        asset = _make_asset(self.vehicle, self.org, alert=alert1)

        matched = correlate_asset_to_alert(asset)
        self.assertFalse(matched)
        asset.refresh_from_db()
        self.assertEqual(asset.alert_id, alert1.pk)

    @override_settings(VIDEO_ALERT_CORRELATION_WINDOW_MINUTES=1)
    def test_correlation_respects_window_setting(self):
        _make_alert(self.vehicle, delta=-90)  # 90s ago — outside 1-min window
        asset = _make_asset(self.vehicle, self.org)
        matched = correlate_asset_to_alert(asset)
        self.assertFalse(matched)


class CorrelationIngestIntegrationTests(TestCase):
    """End-to-end: webhook ingest auto-correlates a clip to a nearby Alert."""

    def setUp(self):
        self.org, self.vehicle = _make_org_vehicle("int-org", "INT01")

    @override_settings(VIDEO_ALERT_CORRELATION_WINDOW_MINUTES=5)
    def test_webhook_auto_correlates_to_nearby_alert(self):
        alert = _make_alert(self.vehicle, delta=-60)  # 1 minute ago

        payload = {
            "org_slug": "int-org",
            "vehicle_registration": "INT01",
            "playback_url": "https://example.invalid/auto.mp4",
            "occurred_at": timezone.now().isoformat(),
        }
        with patch("mytrack.notifications.emails.send_email"):
            res = self.client.post(
                "/api/video/webhook/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer dev-ingest-token",
            )
        self.assertEqual(res.status_code, 200)
        asset = VideoAsset.objects.first()
        self.assertIsNotNone(asset)
        self.assertEqual(asset.alert_id, alert.pk)

    @override_settings(VIDEO_ALERT_CORRELATION_WINDOW_MINUTES=5)
    def test_traccar_ingest_auto_correlates(self):
        alert = _make_alert(self.vehicle, delta=-30)
        now = timezone.now()

        with patch("mytrack.notifications.emails.send_email"):
            result = register_clip_from_traccar_attributes(
                {"mediaUrl": "https://cdn.example.invalid/file.mp4"},
                self.vehicle,
                now,
                tracked_trip=None,
                position_id=77777,
            )
        self.assertIsNotNone(result)
        asset, created = result
        self.assertTrue(created)
        asset.refresh_from_db()
        self.assertEqual(asset.alert_id, alert.pk)


# ── Clip requests ─────────────────────────────────────────────────────────────

class ClipRequestTests(TestCase):
    def setUp(self):
        self.org, self.vehicle = _make_org_vehicle("cr-org", "CR02")

    @override_settings(VIDEO_CLIP_REQUEST_URL="")
    def test_noop_when_url_not_configured(self):
        from mytrack.video_telematics.clip_request import request_clip_for_alert
        alert = _make_alert(self.vehicle)
        request_clip_for_alert(alert)
        self.assertEqual(ClipRequest.objects.count(), 0)

    @override_settings(VIDEO_CLIP_REQUEST_URL="http://mock.invalid/clips/")
    def test_creates_clip_request_row_synchronously(self):
        from mytrack.video_telematics.clip_request import request_clip_for_alert

        alert = _make_alert(self.vehicle)
        # Patch the thread so it doesn't actually make an HTTP call
        with patch("mytrack.video_telematics.clip_request.ThreadPoolExecutor") as mock_tpe:
            mock_tpe.return_value.__enter__ = lambda s: s
            mock_tpe.return_value.__exit__ = lambda s, *a: False
            mock_tpe.return_value.submit = lambda fn: None
            request_clip_for_alert(alert)

        cr = ClipRequest.objects.first()
        self.assertIsNotNone(cr)
        self.assertEqual(cr.status, ClipRequestStatus.PENDING)
        self.assertEqual(cr.alert_id, alert.pk)
        self.assertEqual(cr.vehicle_id, self.vehicle.pk)


# ── Video safety email ────────────────────────────────────────────────────────

class VideoSafetyEmailTests(TestCase):
    def setUp(self):
        self.org, self.vehicle = _make_org_vehicle("mail-org", "ML01")
        self.user = User.objects.create_user(
            "admin1",
            email="admin@example.invalid",
            password="pass12345",
            organisation=self.org,
            role=Role.ADMIN,
        )

    def test_send_video_safety_alert_fires_when_alert_linked(self):
        from mytrack.notifications.emails import send_video_safety_alert

        alert = _make_alert(self.vehicle)
        asset = _make_asset(self.vehicle, self.org, alert=alert)

        with patch("mytrack.notifications.emails.send_email") as mock_send:
            send_video_safety_alert(asset)

        mock_send.assert_called_once()
        subject = mock_send.call_args[0][1]
        self.assertIn("Video evidence", subject)
        self.assertIn(str(self.vehicle), subject)

    def test_no_email_when_no_alert_linked(self):
        from mytrack.notifications.emails import send_video_safety_alert

        asset = _make_asset(self.vehicle, self.org)

        with patch("mytrack.notifications.emails.send_email") as mock_send:
            send_video_safety_alert(asset)

        mock_send.assert_not_called()


# ── Retention: purge_expired_video ───────────────────────────────────────────

class PurgeExpiredVideoTests(TestCase):
    def setUp(self):
        self.org, self.vehicle = _make_org_vehicle("purge-org", "PG01")

    def _make_expired(self, count=3):
        past = timezone.now() - timedelta(hours=2)
        for i in range(count):
            VideoAsset.objects.create(
                organisation=self.org,
                vehicle=self.vehicle,
                occurred_at=past,
                trigger_type=VideoTrigger.UNKNOWN,
                ingest_source=IngestSource.WEBHOOK,
                playback_url="https://example.invalid/expired.mp4",
                delete_after=past,
            )

    def test_dry_run_does_not_delete(self):
        self._make_expired(3)
        call_command("purge_expired_video", "--dry-run")
        self.assertEqual(VideoAsset.objects.count(), 3)

    def test_deletes_expired_assets(self):
        self._make_expired(3)
        call_command("purge_expired_video")
        self.assertEqual(VideoAsset.objects.count(), 0)

    def test_skips_unexpired_assets(self):
        self._make_expired(2)
        future = timezone.now() + timedelta(days=1)
        VideoAsset.objects.create(
            organisation=self.org,
            vehicle=self.vehicle,
            occurred_at=timezone.now(),
            trigger_type=VideoTrigger.UNKNOWN,
            ingest_source=IngestSource.WEBHOOK,
            playback_url="https://example.invalid/keep.mp4",
            delete_after=future,
        )
        call_command("purge_expired_video")
        self.assertEqual(VideoAsset.objects.count(), 1)


# ── Camera health view ────────────────────────────────────────────────────────

class CameraHealthViewTests(TestCase):
    def setUp(self):
        self.org, self.vehicle = _make_org_vehicle("health-org", "HH01")
        self.user = User.objects.create_user(
            "healthuser",
            password="pass12345",
            organisation=self.org,
            role=Role.DISPATCHER,
        )
        VideoChannel.objects.create(vehicle=self.vehicle, name="Front", source="vendor")
        VideoChannel.objects.create(
            vehicle=self.vehicle,
            name="Rear",
            source="vendor",
            camera_last_seen=timezone.now() - timedelta(hours=48),  # stale
        )

    def test_camera_health_requires_login(self):
        res = self.client.get("/video/camera-health/")
        self.assertEqual(res.status_code, 302)

    def test_camera_health_renders(self):
        self.client.login(username="healthuser", password="pass12345")
        res = self.client.get("/video/camera-health/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Front")
        self.assertContains(res, "Rear")


class SurveillanceRoomViewTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Surv Org", slug="surv-org")
        self.user = User.objects.create_user(
            "survadmin",
            password="pass12345",
            organisation=self.org,
            role=Role.ADMIN,
        )
        self.depot_a = Depot.objects.create(organisation=self.org, name="Depot A")
        self.depot_b = Depot.objects.create(organisation=self.org, name="Depot B")

        self.vehicle_a = Vehicle.objects.create(
            organisation=self.org, registration="SURV-A1", home_depot=self.depot_a
        )
        self.vehicle_b = Vehicle.objects.create(
            organisation=self.org, registration="SURV-B1", home_depot=self.depot_b
        )

        VideoChannel.objects.create(
            vehicle=self.vehicle_a,
            name="Front",
            source="vendor",
            stream_url="https://example.invalid/live/front.m3u8",
            camera_last_seen=timezone.now(),
        )
        VideoChannel.objects.create(
            vehicle=self.vehicle_b,
            name="Cabin",
            source="traccar",
            stream_url="https://example.invalid/live/cabin.jpg",
            camera_last_seen=timezone.now() - timedelta(hours=48),
        )

    def test_surveillance_room_requires_login(self):
        res = self.client.get("/video/surveillance-room/")
        self.assertEqual(res.status_code, 302)

    def test_surveillance_room_renders_for_logged_in_user(self):
        self.client.login(username="survadmin", password="pass12345")
        res = self.client.get("/video/surveillance-room/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "SURV-A1")
        self.assertContains(res, "SURV-B1")

    def test_surveillance_room_filters_by_status(self):
        self.client.login(username="survadmin", password="pass12345")
        res = self.client.get("/video/surveillance-room/?status=ok")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "SURV-A1")
        self.assertNotContains(res, "SURV-B1")

    def test_surveillance_room_respects_active_depot(self):
        self.client.login(username="survadmin", password="pass12345")
        session = self.client.session
        session["active_depot_id"] = str(self.depot_a.pk)
        session.save()

        res = self.client.get("/video/surveillance-room/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "SURV-A1")
        self.assertNotContains(res, "SURV-B1")

    def test_surveillance_room_caps_page_size(self):
        self.client.login(username="survadmin", password="pass12345")
        res = self.client.get("/video/surveillance-room/?page_size=999")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["page_size"], 16)


# ── Existing tests ─────────────────────────────────────────────────────────────

class VideoUiTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Org", slug="t2")
        self.user = User.objects.create_user(
            "viewer1",
            password="pass12345",
            organisation=self.org,
            role=Role.DISPATCHER,
        )
        self.vehicle = Vehicle.objects.create(organisation=self.org, registration="ZZ99")
        self.asset = VideoAsset.objects.create(
            organisation=self.org,
            vehicle=self.vehicle,
            occurred_at=timezone.now(),
            trigger_type=VideoTrigger.UNKNOWN,
            ingest_source=IngestSource.WEBHOOK,
            external_id="x1",
            playback_url="https://example.invalid/x.mp4",
        )

    def test_detail_requires_login(self):
        c = Client()
        res = c.get(f"/video/{self.asset.pk}/")
        self.assertEqual(res.status_code, 302)

    def test_detail_renders_for_org_user(self):
        c = Client()
        c.login(username="viewer1", password="pass12345")
        res = c.get(f"/video/{self.asset.pk}/")
        self.assertEqual(res.status_code, 200)


class TraccarMediaTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="O", slug="tr-org")
        self.vehicle = Vehicle.objects.create(organisation=self.org, registration="TT01")

    def test_registers_when_media_url_in_attributes(self):
        now = timezone.now()
        out = register_clip_from_traccar_attributes(
            {"mediaUrl": "https://cdn.example.invalid/file.mp4"},
            self.vehicle,
            now,
            tracked_trip=None,
            position_id=999888,
        )
        self.assertIsNotNone(out)
        asset, created = out
        self.assertTrue(created)
        self.assertEqual(asset.ingest_source, IngestSource.TRACCAR)
        self.assertIn("cdn.example.invalid", asset.playback_url)

    def test_skips_without_url(self):
        self.assertIsNone(
            register_clip_from_traccar_attributes(
                {"fuel1": 10}, self.vehicle, None, None, 1
            )
        )
