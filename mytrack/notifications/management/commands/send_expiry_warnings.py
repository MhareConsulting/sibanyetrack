from django.core.management.base import BaseCommand

from mytrack.notifications.emails import send_expiry_warnings


class Command(BaseCommand):
    help = "Send driver licence/PDP expiry warning emails (run daily via cron)"

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

        results = send_expiry_warnings(dry_run=dry_run)

        if not results:
            self.stdout.write("No expiry warnings to send today.")
            return

        for org_name, count, recipients in results:
            status = "Would send" if dry_run else "Sent"
            self.stdout.write(
                self.style.SUCCESS(f"{status} to {org_name}: {count} warning(s) → {', '.join(recipients)}")
            )
