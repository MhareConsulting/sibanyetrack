"""
Fetch current SA fuel prices from the AA website (aa.co.za/fuel-pricing/).
Returns a dict with effective_from date and per-litre ZAR prices.
Raises FuelPriceFetchError when the page is unreachable or the expected
price table cannot be parsed.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup

AA_URL = "https://www.aa.co.za/fuel-pricing/"
_PRICE_RE = re.compile(r"R?\s*(\d{1,3}[.,]\d{1,3})")


class FuelPriceFetchError(Exception):
    pass


def fetch_aa_fuel_prices() -> dict:
    """
    Scrape the AA fuel pricing page.

    Returns a dict::

        {
            "effective_from": date,
            "petrol_95":      Decimal,   # may be None if not found
            "petrol_93":      Decimal,
            "diesel_500ppm":  Decimal,
            "diesel_50ppm":   Decimal,
            "source":         "aa_scrape",
        }
    """
    try:
        resp = requests.get(
            AA_URL,
            timeout=20,
            headers={"User-Agent": "myTrack/1.0 (+fleet-management)"},
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FuelPriceFetchError(f"Could not reach AA fuel pricing page: {exc}") from exc

    soup = BeautifulSoup(resp.text, "lxml")

    effective_from = _parse_effective_date(soup)
    prices = _parse_prices(soup)

    return {
        "effective_from": effective_from,
        "petrol_95":      prices.get("95"),
        "petrol_93":      prices.get("93"),
        "diesel_500ppm":  prices.get("500ppm"),
        "diesel_50ppm":   prices.get("50ppm"),
        "source":         "aa_scrape",
    }


def _parse_effective_date(soup: BeautifulSoup) -> date:
    """Extract the 'effective from' date from the page heading or table caption."""
    text = soup.get_text(" ", strip=True)

    # Patterns like "1 June 2025", "June 1, 2025", or "2025-06-01"
    patterns = [
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
        r"\b(\d{4})-(\d{2})-(\d{2})\b",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                g = m.groups()
                if re.match(r"\d{4}", g[0]):
                    return datetime.strptime(f"{g[0]}-{g[1]}-{g[2]}", "%Y-%m-%d").date()
                if re.match(r"\d{1,2}", g[0]):
                    return datetime.strptime(f"{g[0]} {g[1]} {g[2]}", "%d %B %Y").date()
                # Month first
                return datetime.strptime(f"{g[1]} {g[0]} {g[2]}", "%d %B %Y").date()
            except (ValueError, IndexError):
                continue

    # Fall back to current month's first day
    today = date.today()
    return today.replace(day=1)


def _parse_prices(soup: BeautifulSoup) -> dict:
    """
    Walk all tables on the page and extract fuel prices by matching row text
    against known product names.  Returns a dict keyed by shorthand:
    '95', '93', '500ppm', '50ppm'.
    """
    ALIASES = {
        "95":     ["95", "petrol 95", "unleaded 95", "unlead 95"],
        "93":     ["93", "petrol 93", "unleaded 93", "unlead 93"],
        "500ppm": ["500ppm", "diesel 500", "500 ppm", "0.05%"],
        "50ppm":  ["50ppm",  "diesel 50",  "50 ppm",  "0.005%"],
    }

    found: dict[str, Decimal] = {}

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            row_text = " ".join(cells).lower()
            for key, aliases in ALIASES.items():
                if key in found:
                    continue
                if any(alias in row_text for alias in aliases):
                    # Look for a price value in any cell after the first
                    for cell in cells[1:]:
                        m = _PRICE_RE.search(cell)
                        if m:
                            try:
                                price_str = m.group(1).replace(",", ".")
                                found[key] = Decimal(price_str)
                            except InvalidOperation:
                                pass
                            break

    if not found:
        # Try a flat text scan as last resort
        page_text = soup.get_text(" ", strip=True)
        _fallback_scan(page_text, ALIASES, found)

    return found


def _fallback_scan(text: str, aliases: dict, found: dict) -> None:
    """Secondary extraction: scan raw text for price patterns near product names."""
    for key, names in aliases.items():
        if key in found:
            continue
        for name in names:
            idx = text.lower().find(name)
            if idx == -1:
                continue
            snippet = text[idx: idx + 80]
            m = _PRICE_RE.search(snippet)
            if m:
                try:
                    found[key] = Decimal(m.group(1).replace(",", "."))
                except InvalidOperation:
                    pass
                break
