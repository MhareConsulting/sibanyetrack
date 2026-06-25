from django.core.management.base import BaseCommand

from mytrack.notifications.emails import send_monthly_summary


class Command(BaseCommand):
    help = (
        "Send monthly fleet and safety summary emails for the previous calendar month "
        "(run on the 1st of each month via cron)."
    )

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

        results = send_monthly_summary(dry_run=dry_run)

        if not results:
            self.stdout.write("No organisations with recipients found.")
            return

        for org_name, recipients in results:
            status = "Would send" if dry_run else "Sent"
            self.stdout.write(
                self.style.SUCCESS(f"{status} to {org_name} → {', '.join(recipients)}")
            )
