"""
Webhook dispatch: queue deliveries and flush them with exponential backoff.

Fire points call fire_webhook(org, event_type, payload).
The cron endpoint calls flush_pending_deliveries() to actually deliver them.
"""

import hashlib
import hmac
import json
import logging
import urllib.request
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# Backoff schedule in minutes: attempt 1 → 1 min, 2 → 5 min, 3 → give up
_BACKOFF_MINUTES = [1, 5, 30]
MAX_ATTEMPTS = len(_BACKOFF_MINUTES)


def fire_webhook(org, event_type: str, payload: dict):
    """Queue a delivery for every active endpoint subscribed to event_type."""
    from .models import WebhookDelivery, WebhookEndpoint

    endpoints = WebhookEndpoint.objects.filter(
        organisation=org,
        is_active=True,
        events__contains=event_type,
    )
    now = timezone.now()
    for ep in endpoints:
        WebhookDelivery.objects.create(
            endpoint=ep,
            event_type=event_type,
            payload=payload,
            next_retry_at=now,
        )


def flush_pending_deliveries(batch: int = 50) -> dict:
    """
    Deliver queued webhooks.  Called from cron_flush_outbox.
    Returns counts: flushed, failed, dead_lettered.
    """
    from .models import WebhookDelivery

    now = timezone.now()
    pending = list(
        WebhookDelivery.objects
        .filter(delivered_at__isnull=True, attempts__lt=MAX_ATTEMPTS, next_retry_at__lte=now)
        .select_related('endpoint')
        .order_by('created_at')[:batch]
    )

    results = {"flushed": 0, "failed": 0, "dead_lettered": 0}

    for delivery in pending:
        try:
            _deliver(delivery, now)
            results["flushed"] += 1
        except Exception as exc:
            delivery.attempts += 1
            delivery.error = str(exc)[:500]
            if delivery.attempts < MAX_ATTEMPTS:
                backoff = _BACKOFF_MINUTES[delivery.attempts - 1]
                delivery.next_retry_at = now + timedelta(minutes=backoff)
                results["failed"] += 1
            else:
                delivery.next_retry_at = None
                results["dead_lettered"] += 1
            delivery.save(update_fields=["attempts", "error", "next_retry_at"])

    return results


def _deliver(delivery, now):
    from .models import WebhookDelivery

    body = json.dumps(delivery.payload, default=str).encode()
    sig = hmac.new(delivery.endpoint.secret.encode(), body, hashlib.sha256).hexdigest()

    req = urllib.request.Request(
        delivery.endpoint.url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-myTrack-Signature": f"sha256={sig}",
            "X-myTrack-Event": delivery.event_type,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.status

    delivery.status_code = status
    delivery.delivered_at = now
    delivery.attempts += 1
    delivery.error = ""
    delivery.save(update_fields=["status_code", "delivered_at", "attempts", "error"])
