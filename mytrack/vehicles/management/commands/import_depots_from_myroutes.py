"""
One-time command: pull all depots from MyRoutes into myTrack, then push them
back so every depot gets a mytrack_id on the MyRoutes side.

Usage:
    python manage.py import_depots_from_myroutes --org-slug demo

What it does:
  1. Calls GET /api/driver/sync/mytrack/depots/?org_slug=<slug> on MyRoutes
     to fetch every existing depot that has no mytrack_id yet.
  2. For each, creates (or skips if already exists by name) a Depot in myTrack.
  3. The post_save signal fires automatically, pushing the new depot back to
     MyRoutes with its mytrack_id — MyRoutes matches by name and links it.
"""

import urllib.request
import json

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from mytrack.tenancy.models import Depot, Organisation


class Command(BaseCommand):
    help = "Import depots from MyRoutes into myTrack (run once to establish source-of-truth)."

    def add_arguments(self, parser):
        parser.add_argument("--org-slug", required=True, help="Organisation slug (must match MyRoutes tenant slug)")
        parser.add_argument("--dry-run", action="store_true", help="Print what would be created without saving")

    def handle(self, *args, **options):
        org_slug = options["org_slug"]
        dry_run = options["dry_run"]

        try:
            org = Organisation.objects.get(slug=org_slug)
        except Organisation.DoesNotExist:
            raise CommandError(f"Organisation '{org_slug}' not found in myTrack.")

        url = getattr(settings, "MYROUTES_SYNC_URL", "").rstrip("/")
        token = getattr(settings, "MYROUTES_SYNC_TOKEN", "")
        if not url or not token:
            raise CommandError("MYROUTES_SYNC_URL and MYROUTES_SYNC_TOKEN must be set in settings.")

        # Derive the depot list URL from the sync URL
        # MYROUTES_SYNC_URL is typically .../api/driver/sync/mytrack/
        list_url = url.rstrip("/").rsplit("/sync/mytrack", 1)[0] + f"/sync/mytrack/depots/?org_slug={org_slug}"

        self.stdout.write(f"Fetching depots from {list_url} ...")
        try:
            req = urllib.request.Request(
                list_url,
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                depots = json.loads(resp.read())
        except Exception as exc:
            raise CommandError(f"Failed to fetch depots from MyRoutes: {exc}")

        self.stdout.write(f"Found {len(depots)} depot(s) in MyRoutes.")

        created = linked = skipped = 0

        for d in depots:
            name = d["name"]
            already_linked = d.get("mytrack_id") is not None
            exists_in_mytrack = Depot.objects.filter(organisation=org, name=name).exists()

            if already_linked:
                self.stdout.write(f"  SKIP  '{name}' — already linked (mytrack_id={d['mytrack_id']})")
                skipped += 1
                continue

            if exists_in_mytrack:
                self.stdout.write(f"  LINK  '{name}' — exists in myTrack, re-pushing to link")
                if not dry_run:
                    depot = Depot.objects.get(organisation=org, name=name)
                    # Re-save to fire signal and push mytrack_id back to MyRoutes
                    depot.save()
                linked += 1
                continue

            self.stdout.write(f"  CREATE '{name}'")
            if not dry_run:
                Depot.objects.create(
                    organisation=org,
                    name=name,
                    address=d.get("address", ""),
                    is_active=True,
                )
            created += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run — no changes made."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nDone. Created: {created}  Linked: {linked}  Skipped: {skipped}"
            ))
