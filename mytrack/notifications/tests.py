from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from mytrack.notifications.emails import (
    _alert_digest_detail,
    _alert_digest_kind_label,
    _alert_kind_counts_rows,
    _org_notification_recipients,
    _parse_cc_emails,
    send_alert_digest,
    send_weekly_summary,
)
from mytrack.tenancy.models import Organisation, Role, User
from mytrack.tracking.models import Alert, AlertKind
from mytrack.vehicles.models import Vehicle


class AlertDigestHelpersTests(TestCase):
    def test_digest_detail_speeding(self):
        a = Alert(
            kind=AlertKind.SPEEDING,
            value=95.0,
            threshold=80.0,
        )
        self.assertEqual(_alert_digest_detail(a), "95 km/h (limit 80)")

    def test_digest_detail_idle(self):
        a = Alert(
            kind=AlertKind.IDLE,
            value=25.0,
            threshold=10.0,
        )
        self.assertEqual(_alert_digest_detail(a), "25 min idle (threshold 10)")

    def test_digest_detail_harsh_event_detected(self):
        a = Alert(kind=AlertKind.HARSH_BRAKING, value=1.0, threshold=0.0)
        self.assertEqual(_alert_digest_detail(a), "Event detected")

    def test_digest_detail_fuel_theft(self):
        a = Alert(kind=AlertKind.FUEL_THEFT, value=12.5, threshold=5.0)
        self.assertEqual(_alert_digest_detail(a), "12.5 L (threshold 5.0 L)")

    def test_digest_detail_excess_consumption(self):
        a = Alert(kind=AlertKind.EXCESS_CONSUMPTION, value=18.2, threshold=12.0)
        self.assertEqual(_alert_digest_detail(a), "18.2 L/100 km (baseline 12.0)")

    def test_digest_kind_label_uses_display(self):
        a = Alert(kind=AlertKind.LANE_DEPARTURE, value=1.0, threshold=0.0)
        self.assertEqual(_alert_digest_kind_label(a), "Lane Departure")


class AlertDigestAggregationTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Digest Org", slug="digest-org")
        self.user = User.objects.create_user(
            username="disp1",
            email="disp@example.com",
            password="x",
            organisation=self.org,
            role=Role.DISPATCHER,
        )
        self.vehicle = Vehicle.objects.create(
            organisation=self.org,
            registration="ZZ99GP",
            label="ZZ99GP",
        )

    def test_alert_kind_counts_rows(self):
        now = timezone.now()
        Alert.objects.create(
            vehicle=self.vehicle,
            kind=AlertKind.SPEEDING,
            value=100,
            threshold=80,
            occurred_at=now,
        )
        Alert.objects.create(
            vehicle=self.vehicle,
            kind=AlertKind.SPEEDING,
            value=90,
            threshold=80,
            occurred_at=now,
        )
        Alert.objects.create(
            vehicle=self.vehicle,
            kind=AlertKind.HARSH_BRAKING,
            value=1,
            threshold=0,
            occurred_at=now,
        )
        qs = Alert.objects.filter(vehicle=self.vehicle)
        rows = _alert_kind_counts_rows(qs)
        by_label = dict(rows)
        self.assertEqual(by_label.get("Speeding"), 2)
        self.assertEqual(by_label.get("Harsh Braking"), 1)

    def test_send_alert_digest_dry_run_finds_recent_alerts(self):
        now = timezone.now()
        Alert.objects.create(
            vehicle=self.vehicle,
            kind=AlertKind.SEATBELT,
            value=1,
            threshold=0,
            occurred_at=now - timedelta(hours=1),
        )
        results = send_alert_digest(dry_run=True)
        self.assertTrue(any(r[0] == "Digest Org" and r[1] >= 1 for r in results))


class NotificationCcParsingTests(TestCase):
    def test_parse_cc_dedupes_and_validates(self):
        org = Organisation(
            name="X",
            slug="x-org",
            notification_cc_emails="a@x.com, A@x.com ; bad\nfoo@y.co.za",
        )
        org.save()
        self.assertEqual(_parse_cc_emails(org), ["a@x.com", "foo@y.co.za"])

    def test_org_notification_recipients_merges(self):
        org = Organisation.objects.create(name="Y", slug="y-org", notification_cc_emails="cc@z.com")
        User.objects.create_user(
            username="d",
            email="cc@z.com",
            password="x",
            organisation=org,
            role=Role.DISPATCHER,
        )
        self.assertEqual(_org_notification_recipients(org), ["cc@z.com"])


class WeeklySummaryOrgFlagTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Weekly Org",
            slug="weekly-org",
            email_weekly_summary_enabled=False,
        )
        User.objects.create_user(
            username="w",
            email="w@example.com",
            password="x",
            organisation=self.org,
            role=Role.DISPATCHER,
        )

    @patch("mytrack.notifications.emails.send_email")
    def test_weekly_skipped_when_org_disabled(self, mock_send):
        send_weekly_summary(dry_run=False)
        mock_send.assert_not_called()


class CronEmailJobsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(CRON_EMAIL_TRIGGER_TOKEN="")
    def test_cron_returns_503_when_token_unset(self):
        res = self.client.post("/api/cron/email-jobs/", {"job": "digest"}, format="json")
        self.assertEqual(res.status_code, 503)

    @override_settings(CRON_EMAIL_TRIGGER_TOKEN="secret")
    def test_cron_returns_401_on_bad_bearer(self):
        res = self.client.post(
            "/api/cron/email-jobs/",
            {"job": "digest"},
            format="json",
            HTTP_AUTHORIZATION="Bearer wrong",
        )
        self.assertEqual(res.status_code, 401)

    @override_settings(CRON_EMAIL_TRIGGER_TOKEN="secret")
    def test_cron_returns_400_unknown_job(self):
        res = self.client.post(
            "/api/cron/email-jobs/",
            {"job": "nope"},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret",
        )
        self.assertEqual(res.status_code, 400)

    @override_settings(CRON_EMAIL_TRIGGER_TOKEN="secret")
    @patch("mytrack.notifications.emails.send_alert_digest", return_value=[])
    def test_cron_digest_200(self, _mock_digest):
        res = self.client.post(
            "/api/cron/email-jobs/",
            {"job": "digest"},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["job"], "digest")
