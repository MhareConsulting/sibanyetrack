import hmac

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle


class CronEmailJobsThrottle(SimpleRateThrottle):
    scope = "cron_email_jobs"

    def get_cache_key(self, request, view):
        ident = request.META.get("REMOTE_ADDR", "") or "unknown"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class CronFlushOutboxThrottle(SimpleRateThrottle):
    scope = "cron_flush_outbox"

    def get_cache_key(self, request, view):
        ident = request.META.get("REMOTE_ADDR", "") or "unknown"
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _bearer_token(request):
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("Bearer "):
        return None
    return auth[7:].strip()


def _token_ok(provided: str, expected: str) -> bool:
    if not expected or not provided:
        return False
    pa, ex = provided.encode(), expected.encode()
    if len(pa) != len(ex):
        return False
    return hmac.compare_digest(pa, ex)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([CronEmailJobsThrottle])
def cron_email_jobs(request):
    """
    Trigger scheduled notification emails (GitHub Actions / external cron).
    Authorization: Bearer <CRON_EMAIL_TRIGGER_TOKEN>
    Body: {"job": "digest"|"weekly"|"monthly"|"expiry"}
    """
    expected = (getattr(settings, "CRON_EMAIL_TRIGGER_TOKEN", None) or "").strip()
    if not expected:
        return Response(
            {"detail": "Scheduled email trigger is not configured on this server."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    provided = _bearer_token(request) or ""
    if not _token_ok(provided, expected):
        return Response({"detail": "Invalid or missing bearer token."}, status=status.HTTP_401_UNAUTHORIZED)

    job = (request.data.get("job") if isinstance(request.data, dict) else None) or ""
    job = str(job).strip().lower()

    from mytrack.notifications import emails as email_mod

    if job == "scheduled_reports":
        from mytrack.reporting.cron import run_scheduled_reports
        count = run_scheduled_reports()
        return Response({"job": job, "reports_sent": count}, status=status.HTTP_200_OK)

    if job == "fetch_fuel_prices":
        from mytrack.fuel.cron import fetch_and_store_fuel_prices
        result = fetch_and_store_fuel_prices()
        return Response({"job": job, **result}, status=status.HTTP_200_OK)

    if job == "poll_traccar_alarms":
        from mytrack.tracking.traccar_poll import poll_traccar_alarms
        result = poll_traccar_alarms()
        return Response({"job": job, **result}, status=status.HTTP_200_OK)

    dispatch = {
        "digest": email_mod.send_alert_digest,
        "weekly": email_mod.send_weekly_summary,
        "monthly": email_mod.send_monthly_summary,
        "expiry": email_mod.send_expiry_warnings,
    }
    if job not in dispatch:
        return Response(
            {"detail": 'Body must include "job": one of digest, weekly, monthly, expiry, scheduled_reports, fetch_fuel_prices.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    results = dispatch[job](dry_run=False)
    return Response(
        {
            "job": job,
            "result_count": len(results),
            "results": [{"org": row[0], "detail": list(row[1:])} for row in results],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([CronFlushOutboxThrottle])
def cron_flush_outbox(request):
    """
    Flush pending SyncOutbox rows, delivering them to external systems.
    Authorization: Bearer <CRON_EMAIL_TRIGGER_TOKEN>  (reuses the same token)
    Call every ~30 s from GitHub Actions to ensure reliable sync delivery.
    Rows are retried up to 3 times; beyond that they are dead-lettered (visible in admin).
    """
    import json
    import urllib.request
    from urllib.parse import urlparse

    from django.utils import timezone as tz

    from mytrack.tracking.models import SyncOutbox

    expected = (getattr(settings, "CRON_EMAIL_TRIGGER_TOKEN", None) or "").strip()
    if not expected:
        return Response({"detail": "Cron token not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    provided = _bearer_token(request) or ""
    if not _token_ok(provided, expected):
        return Response({"detail": "Invalid or missing bearer token."}, status=status.HTTP_401_UNAUTHORIZED)

    MAX_ATTEMPTS = 3
    BATCH = 50

    sync_url = getattr(settings, "MYROUTES_SYNC_URL", "")
    sync_token = getattr(settings, "MYROUTES_SYNC_TOKEN", "")

    parsed = urlparse(sync_url) if sync_url else None
    base = f"{parsed.scheme}://{parsed.netloc}" if parsed else ""

    url_map = {
        SyncOutbox.DEST_MYROUTES_POSITION: f"{base}/api/driver/tracking/position/",
        SyncOutbox.DEST_MYROUTES_SYNC: sync_url,
        SyncOutbox.DEST_MYROUTES_FUEL: f"{base}/api/sync/mytrack/fuel/",
    }

    pending = list(
        SyncOutbox.objects.filter(succeeded_at__isnull=True, attempts__lt=MAX_ATTEMPTS)
        .order_by("created_at")[:BATCH]
    )

    # Also drain webhook deliveries
    try:
        from mytrack.webhooks.dispatch import flush_pending_deliveries
        wh = flush_pending_deliveries()
        webhook_results = {"webhooks_flushed": wh["flushed"], "webhooks_failed": wh["failed"] + wh["dead_lettered"]}
    except Exception:
        webhook_results = {}

    results = {"flushed": 0, "failed": 0, "dead_lettered": 0}
    now = tz.now()

    for row in pending:
        url = url_map.get(row.destination)
        if not url:
            row.attempts += 1
            row.error = f"Unknown destination: {row.destination}"
            row.last_attempted_at = now
            row.save(update_fields=["attempts", "error", "last_attempted_at"])
            continue

        try:
            body = json.dumps(row.payload).encode()
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {sync_token}",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            row.succeeded_at = now
            row.attempts += 1
            row.last_attempted_at = now
            row.save(update_fields=["succeeded_at", "attempts", "last_attempted_at"])
            results["flushed"] += 1
        except Exception as exc:
            row.attempts += 1
            row.error = str(exc)[:500]
            row.last_attempted_at = now
            row.save(update_fields=["attempts", "error", "last_attempted_at"])
            if row.attempts >= MAX_ATTEMPTS:
                results["dead_lettered"] += 1
            else:
                results["failed"] += 1

    return Response({**results, **webhook_results}, status=status.HTTP_200_OK)
