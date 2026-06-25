"""
Management command: compute_fleet_health

Calculates a composite Fleet Health Score (0–100) for each organisation
(and optionally per depot) and upserts a DailyFleetHealthScore row.

Score breakdown:
  40% — Driver component: average DriverScore.score across active drivers
  30% — Alert component: (1 - unresolved_alerts / total_pings) × 100
  20% — Compliance component: % vehicles with all docs valid + last inspection < 7 days
  10% — Utilisation component: % active vehicles today

Run nightly, e.g.:
  python manage.py compute_fleet_health
  python manage.py compute_fleet_health --date 2025-06-01
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_date

from mytrack.compliance.models import VehicleDocument
from mytrack.drivers.models import DriverScore
from mytrack.reporting.models import DailyFleetHealthScore
from mytrack.tenancy.models import Organisation
from mytrack.tracking.models import Alert, GPSPing
from mytrack.vehicles.models import Vehicle


class Command(BaseCommand):
    help = "Compute daily fleet health scores for all organisations"

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None, help="Score date (YYYY-MM-DD, default: yesterday)")

    def handle(self, *args, **options):
        score_date = parse_date(options["date"]) if options["date"] else (date.today() - timedelta(days=1))
        self.stdout.write(f"Computing fleet health for {score_date}…")

        for org in Organisation.objects.all():
            score_obj = _compute_for_org(org, score_date)
            DailyFleetHealthScore.objects.update_or_create(
                organisation=org,
                depot=None,
                score_date=score_date,
                defaults={
                    "score":                 score_obj["score"],
                    "driver_component":      score_obj["driver"],
                    "alert_component":       score_obj["alert"],
                    "compliance_component":  score_obj["compliance"],
                    "utilisation_component": score_obj["utilisation"],
                },
            )
            self.stdout.write(
                f"  {org.name}: {score_obj['score']:.1f} "
                f"(driver={score_obj['driver']:.0f} alert={score_obj['alert']:.0f} "
                f"compliance={score_obj['compliance']:.0f} util={score_obj['utilisation']:.0f})"
            )

        self.stdout.write(self.style.SUCCESS("Done."))


def _compute_for_org(org, score_date) -> dict:
    # 40% — Driver average score
    driver_scores = list(
        DriverScore.objects.filter(
            driver__organisation=org,
            driver__is_active=True,
            scored_date=score_date,
        ).values_list("score", flat=True)
    )
    driver_component = (sum(driver_scores) / len(driver_scores)) if driver_scores else 50.0

    # 30% — Alert rate
    day_start = timezone.datetime.combine(score_date, timezone.datetime.min.time()).replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    total_pings = GPSPing.objects.filter(vehicle__organisation=org, received_at__gte=day_start, received_at__lt=day_end).count()
    unresolved = Alert.objects.filter(
        vehicle__organisation=org,
        occurred_at__gte=day_start,
        occurred_at__lt=day_end,
        resolved_at__isnull=True,
    ).count()
    if total_pings > 0:
        alert_component = max(0.0, (1.0 - unresolved / total_pings) * 100)
    else:
        alert_component = 80.0  # neutral if no data

    # 20% — Compliance
    vehicles = list(Vehicle.objects.filter(organisation=org, is_active=True))
    compliant = 0
    for v in vehicles:
        all_docs_valid = not VehicleDocument.objects.filter(
            vehicle=v,
            expiry_date__lt=score_date,
        ).exists()
        last_inspection = v.inspections.order_by("-submitted_at").first()
        inspection_ok = last_inspection and (score_date - last_inspection.submitted_at.date()).days <= 7
        if all_docs_valid and inspection_ok:
            compliant += 1
    compliance_component = (compliant / len(vehicles) * 100) if vehicles else 50.0

    # 10% — Utilisation (vehicles with at least 1 ping today)
    active_vehicle_ids = set(
        GPSPing.objects.filter(vehicle__organisation=org, received_at__gte=day_start, received_at__lt=day_end)
        .values_list("vehicle_id", flat=True)
        .distinct()
    )
    utilisation_component = (len(active_vehicle_ids) / len(vehicles) * 100) if vehicles else 50.0

    score = (
        driver_component * 0.40
        + alert_component * 0.30
        + compliance_component * 0.20
        + utilisation_component * 0.10
    )

    return {
        "score": round(score, 2),
        "driver": round(driver_component, 2),
        "alert": round(alert_component, 2),
        "compliance": round(compliance_component, 2),
        "utilisation": round(utilisation_component, 2),
    }
