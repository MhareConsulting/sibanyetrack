"""Parse OSM maxspeed tags and infer ZA defaults from highway class."""

from __future__ import annotations

import re
from typing import Optional


def maxspeed_tag_to_kmh(raw: Optional[str], highway: str = "") -> Optional[float]:
    """
    Convert an OSM maxspeed tag value to km/h, or None if unknown.

    South Africa uses km/h only; values tagged in mph are ignored (returns None) so we
    never apply imperial conversions. Handles: "80", "80 km/h", "ZA:urban", "signals",
    "none", ranges with km/h hints.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("signals", "none", "variable", "nsl", "unposted"):
        return None

    # ZA context-specific (OpenStreetMap ZA conventions)
    zl = s.upper()
    if zl in ("ZA:URBAN", "ZA:TRAFFIC_CALMING"):
        return 60.0
    if zl in ("ZA:RURAL", "ZA:TRUNK"):
        return 100.0
    if zl in ("ZA:MOTORWAY", "ZA:NATIONAL_ROAD"):
        return 120.0

    # "80;100" or "60 (20:00-06:00)" — use conservative minimum numeric token
    parts = re.split(r"[;|]", s)
    candidates: list[float] = []
    for part in parts:
        part = part.strip()
        if "mph" in part.lower():
            continue
        m = re.match(
            r"^(\d+(?:\.\d+)?)\s*(km/h|kmh|kph)?\s*$",
            part,
            re.IGNORECASE,
        )
        if not m:
            continue
        candidates.append(float(m.group(1)))
    if candidates:
        return min(candidates)

    return None


def default_kmh_for_highway(highway: str) -> Optional[float]:
    """When maxspeed is missing, use common SA defaults by road class."""
    h = (highway or "").lower()
    if h in ("motorway", "motorway_link"):
        return 120.0
    if h in ("trunk", "trunk_link"):
        return 100.0
    if h in ("primary", "primary_link", "secondary", "secondary_link"):
        return 100.0
    if h in ("tertiary", "tertiary_link", "unclassified"):
        return 80.0
    if h in ("residential", "living_street", "service"):
        return 60.0
    if h in ("track", "path", "footway", "cycleway", "pedestrian", "steps"):
        return None
    return 80.0


def resolve_segment_limit_kmh(highway: str, maxspeed_raw: Optional[str]) -> Optional[float]:
    """Posted limit from OSM row: explicit maxspeed tag, else highway heuristic."""
    tagged = maxspeed_tag_to_kmh(maxspeed_raw, highway)
    if tagged is not None:
        return tagged
    return default_kmh_for_highway(highway)
