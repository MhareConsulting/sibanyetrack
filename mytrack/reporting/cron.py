"""Scheduled report delivery — called from cron_api when job='scheduled_reports'."""
from datetime import timedelta
from django.utils import timezone


def run_scheduled_reports() -> int:
    """Run all due ReportSchedule entries, email CSV to recipients. Returns count sent."""
    from mytrack.reporting.models import ReportSchedule
    from mytrack.notifications.emails import send_email

    now = timezone.now()
    due = ReportSchedule.objects.filter(is_active=True, next_run_at__lte=now).select_related("template", "organisation")
    sent = 0

    for sched in due:
        try:
            rows = _run_report(sched)
            recipients = sched.recipient_list()
            if recipients and rows:
                subject = f"[{sched.organisation.name}] Scheduled Report: {sched.template.name}"
                csv_text = _build_csv(rows).decode("utf-8")
                html = (
                    f"<p>Your scheduled <strong>{sched.get_frequency_display().lower()}</strong> report "
                    f"<em>{sched.template.name}</em> is ready.</p>"
                    f"<p>Generated: {timezone.localtime(now).strftime('%d %b %Y %H:%M')} &nbsp;|&nbsp; "
                    f"{len(rows)} rows</p>"
                    f"<pre style='font-size:0.78rem;background:#f8fafc;padding:12px;border-radius:6px;"
                    f"overflow:auto;max-height:400px'>{csv_text[:8000]}"
                    f"{'...(truncated)' if len(csv_text) > 8000 else ''}</pre>"
                )
                send_email(recipients, subject, html)
                sent += 1
        except Exception:
            pass  # Don't block other schedules on one failure

        sched.last_run_at = now
        sched.next_run_at = _compute_next_run(now, sched.frequency)
        sched.save(update_fields=["last_run_at", "next_run_at"])

    return sent


def _run_report(sched) -> list:
    from mytrack.reporting.services import execute_custom_report
    from mytrack.reporting.models import CustomReportDefinition

    cfg = sched.template.config
    # Build a transient definition-like object for execute_custom_report
    defn = CustomReportDefinition(
        organisation=sched.organisation,
        domain=sched.template.domain,
        columns=cfg.get("columns", []),
        metrics=cfg.get("metrics", []),
        group_by=cfg.get("group_by", []),
        filters=cfg.get("filters", {}),
        sort_by=cfg.get("sort_by", []),
    )
    rows, _ = execute_custom_report(defn, limit=5000)
    return rows


def _build_csv(rows: list) -> bytes:
    if not rows:
        return b""
    import csv, io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _compute_next_run(now, frequency: str):
    if frequency == "daily":
        return now + timedelta(days=1)
    if frequency == "weekly":
        return now + timedelta(weeks=1)
    if frequency == "monthly":
        # Advance by ~30 days
        return now + timedelta(days=30)
    return now + timedelta(days=1)
