"""
Management command: purge_expired_video

Deletes VideoAsset rows (and their stored files / S3 objects) where
delete_after <= now. Safe to run multiple times (idempotent).

Recommended cron: 0 2 * * * python manage.py purge_expired_video

Options:
    --dry-run   Print what would be deleted without executing.
    --batch N   Max assets to purge per run (default: 500).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete expired VideoAsset records and their stored media."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview deletions without executing them.",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=500,
            help="Maximum assets to purge in one run (default: 500).",
        )

    def handle(self, *args, **options):
        from django.conf import settings
        from pathlib import Path
        from mytrack.video_telematics.models import VideoAsset

        dry_run = options["dry_run"]
        batch = options["batch"]
        backend = getattr(settings, "VIDEO_STORAGE_BACKEND", "local")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be deleted.\n"))

        now = timezone.now()
        qs = list(
            VideoAsset.objects
            .filter(delete_after__isnull=False, delete_after__lte=now)
            .order_by("delete_after")[:batch]
        )

        if not qs:
            self.stdout.write("No expired video assets found.")
            return

        deleted_count = 0
        error_count = 0

        for asset in qs:
            if asset.storage_key:
                if dry_run:
                    self.stdout.write(
                        f"  Would delete storage: {asset.storage_key} (asset {asset.pk})"
                    )
                else:
                    try:
                        if backend == "s3":
                            _delete_s3_object(asset.storage_key)
                        else:
                            path = Path(settings.MEDIA_ROOT) / asset.storage_key
                            path.unlink(missing_ok=True)
                    except Exception as exc:
                        self.stderr.write(
                            f"  WARNING: Could not delete storage for asset {asset.pk}: {exc}"
                        )
                        error_count += 1
                        continue

            if dry_run:
                self.stdout.write(
                    f"  Would delete: asset {asset.pk} — {asset.vehicle} @ {asset.occurred_at}"
                )
            else:
                asset.delete()
                deleted_count += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"\nWould purge {len(qs)} expired asset(s).")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Purged {deleted_count} expired asset(s). Storage errors: {error_count}."
                )
            )


def _delete_s3_object(storage_key: str) -> None:
    from mytrack.video_telematics.s3_utils import get_s3_client
    from django.conf import settings

    bucket = getattr(settings, "VIDEO_S3_BUCKET", "")
    if not bucket:
        return
    client = get_s3_client()
    client.delete_object(Bucket=bucket, Key=storage_key)
