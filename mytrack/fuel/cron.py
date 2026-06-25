"""Cron helper: fetch AA fuel prices and store per-org FuelPriceHistory rows."""

import logging

from mytrack.tenancy.models import Organisation

from .models import FuelPriceHistory
from .price_fetcher import FuelPriceFetchError, fetch_aa_fuel_prices

logger = logging.getLogger(__name__)


def fetch_and_store_fuel_prices() -> dict:
    """
    Fetch current AA prices, then create (or skip if already exists) a
    FuelPriceHistory row for every active organisation.

    Returns a summary dict suitable for the cron API response.
    """
    try:
        data = fetch_aa_fuel_prices()
    except FuelPriceFetchError as exc:
        logger.error("AA fuel price fetch failed: %s", exc)
        return {"error": str(exc), "orgs_updated": 0}

    effective_from = data["effective_from"]
    orgs = Organisation.objects.all()
    created = 0
    skipped = 0

    for org in orgs:
        _, was_created = FuelPriceHistory.objects.get_or_create(
            organisation=org,
            effective_from=effective_from,
            defaults={
                "petrol_95_zar":     data["petrol_95"],
                "petrol_93_zar":     data["petrol_93"],
                "diesel_500ppm_zar": data["diesel_500ppm"],
                "diesel_50ppm_zar":  data["diesel_50ppm"],
                "source":            data["source"],
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    logger.info(
        "Fuel prices fetched for %s: %d orgs created, %d skipped (already had %s)",
        effective_from, created, skipped, effective_from,
    )
    return {
        "effective_from": str(effective_from),
        "petrol_95":      str(data["petrol_95"]) if data["petrol_95"] else None,
        "petrol_93":      str(data["petrol_93"]) if data["petrol_93"] else None,
        "diesel_500ppm":  str(data["diesel_500ppm"]) if data["diesel_500ppm"] else None,
        "diesel_50ppm":   str(data["diesel_50ppm"]) if data["diesel_50ppm"] else None,
        "orgs_created":   created,
        "orgs_skipped":   skipped,
    }
