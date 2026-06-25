from django.utils import timezone

from mytrack.notifications.service import send_email

from .exports import render_csv_string
from .models import CustomReportRun, CustomReportStatus
from .services import execute_custom_report


def run_custom_report_job(report_run_id):
    report_run = CustomReportRun.objects.select_related("definition", "definition__organisation").get(pk=report_run_id)
    report_run.status = CustomReportStatus.RUNNING
    report_run.started_at = timezone.now()
    report_run.error_message = ""
    report_run.save(update_fields=["status", "started_at", "error_message"])

    try:
        rows = execute_custom_report(report_run.definition)
        report_run.row_count = len(rows)
        report_run.artifact_path = f"in_memory:{report_run.id}"
        report_run.status = CustomReportStatus.SUCCESS
        report_run.finished_at = timezone.now()
        report_run.save(update_fields=["row_count", "artifact_path", "status", "finished_at"])
        maybe_send_scheduled_report_email(report_run, rows)
    except Exception as exc:  # noqa: BLE001
        report_run.status = CustomReportStatus.FAILED
        report_run.error_message = str(exc)
        report_run.finished_at = timezone.now()
        report_run.save(update_fields=["status", "error_message", "finished_at"])
        raise


def maybe_send_scheduled_report_email(report_run, rows):
    schedule = report_run.definition.schedule_config or {}
    recipients = schedule.get("emails") or []
    if not recipients:
        return
    csv_payload = render_csv_string(rows)
    html = (
        "<p>Your scheduled custom report is ready.</p>"
        f"<p>Report: <b>{report_run.definition.name}</b><br>"
        f"Rows: <b>{report_run.row_count}</b><br>"
        "CSV preview attached inline below.</p>"
        "<pre style='background:#f7f8fb;padding:12px;border-radius:8px'>"
        f"{csv_payload[:15000]}"
        "</pre>"
    )
    send_email(recipients, f"[myTrack] Scheduled report — {report_run.definition.name}", html)
