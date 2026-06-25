from django.core.management.base import BaseCommand
from django.utils import timezone

from mytrack.reporting.models import CustomReportDefinition, CustomReportRun
from mytrack.reporting.tasks import run_custom_report_job


class Command(BaseCommand):
    help = "Run scheduled custom reports based on schedule_config."

    def handle(self, *args, **options):
        now = timezone.localtime(timezone.now())
        weekday = now.weekday()
        day = now.day
        hour = now.hour

        reports = CustomReportDefinition.objects.filter(is_active=True)
        triggered = 0
        for definition in reports:
            cfg = definition.schedule_config or {}
            frequency = cfg.get("frequency")
            sched_hour = int(cfg.get("hour", 6))
            if sched_hour != hour:
                continue
            if frequency == "daily":
                should_run = True
            elif frequency == "weekly":
                should_run = int(cfg.get("weekday", 0)) == weekday
            elif frequency == "monthly":
                should_run = int(cfg.get("day", 1)) == day
            else:
                should_run = False
            if not should_run:
                continue

            run = CustomReportRun.objects.create(definition=definition, format=cfg.get("format", "csv"))
            run_custom_report_job(run.id)
            triggered += 1

        self.stdout.write(self.style.SUCCESS(f"Triggered {triggered} scheduled reports."))
