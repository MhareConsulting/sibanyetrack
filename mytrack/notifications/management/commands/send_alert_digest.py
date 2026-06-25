from django.core.management.base import BaseCommand

from mytrack.notifications.emails import send_alert_digest


class Command(BaseCommand):
    help = "Send daily unresolved alert digest emails (run daily via cron)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be sent without actually sending emails",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no emails will be sent\n"))

        results = send_alert_digest(dry_run=dry_run)

        if not results:
            self.stdout.write("No unresolved alerts in the last 24 hours.")
            return

        for org_name, count, recipients in results:
            status = "Would send" if dry_run else "Sent"
            self.stdout.write(
                self.style.SUCCESS(f"{status} to {org_name}: {count} alert(s) → {', '.join(recipients)}")
            )
