"""Road-specific speed limit resolution: Traccar attrs → cache → PostGIS → org fallback."""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional, Tuple

from django.db import close_old_connections, connection, transaction

from mytrack.tracking.road_maxspeed import resolve_segment_limit_kmh

logger = logging.getLogger(__name__)

# ~110 m grid at mid-latitudes; balances cache hits vs precision
_CELL_DECIMALS = 3
_SEARCH_RADIUS_M = 85.0

_TRACCAR_KEYS = (
    "speedLimit",
    "roadSpeedLimit",
    "speed_limit",
    "road_speed_limit",
    "postedSpeed",
)


def _cell_key(lat: float, lon: float) -> str:
    return f"{round(lat, _CELL_DECIMALS):.3f}|{round(lon, _CELL_DECIMALS):.3f}"


def _postgis_table_ready() -> bool:
    if connection.vendor != "postgresql":
        return False
    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'tracking_roadsegment'
                )
                """
            )
            return bool(c.fetchone()[0])
    except Exception:
        return False


def _traccar_road_limit_kmh(attributes: Optional[dict[str, Any]]) -> Optional[float]:
    if not attributes:
        return None
    for key in _TRACCAR_KEYS:
        raw = attributes.get(key)
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if 8.0 <= v <= 200.0:
            return v
        if 5.0 <= v < 8.0:
            return round(v * 1.852, 1)
    return None


def _lookup_postgis_row(lat: float, lon: float) -> Optional[Tuple[float, int]]:
    """
    Return (limit_kmh, osm_way_id) from nearest road segment within search radius, or None.
    """
    if not _postgis_table_ready():
        return None
    sql = """
        SELECT highway, maxspeed, osm_way_id
        FROM tracking_roadsegment
        WHERE ST_DWithin(
            geom::geography,
            (ST_SetSRID(ST_MakePoint(%s, %s), 4326))::geography,
            %s
        )
        ORDER BY ST_Distance(geom::geography, (ST_SetSRID(ST_MakePoint(%s, %s), 4326))::geography)
        LIMIT 1
    """
    try:
        with connection.cursor() as c:
            c.execute(sql, [lon, lat, _SEARCH_RADIUS_M, lon, lat])
            row = c.fetchone()
            if not row:
                return None
            highway, maxspeed_raw, osm_way_id = str(row[0] or ""), row[1], row[2]
            lim = resolve_segment_limit_kmh(highway, maxspeed_raw)
            if lim is None:
                return None
            wid = int(osm_way_id) if osm_way_id is not None else 0
            return (float(lim), wid)
    except Exception as e:
        logger.debug("PostGIS road lookup failed: %s", e)
        return None


def _cache_get(cell_key: str) -> Optional[float]:
    from mytrack.tracking.models import RoadSpeedCache

    try:
        row = RoadSpeedCache.objects.only("limit_kmh").filter(cell_key=cell_key).first()
        if row:
            return float(row.limit_kmh)
    except Exception:
        pass
    return None


def _cache_set(cell_key: str, limit_kmh: float, osm_way_id: Optional[int] = None) -> None:
    from mytrack.tracking.models import RoadSpeedCache

    try:
        RoadSpeedCache.objects.update_or_create(
            cell_key=cell_key,
            defaults={"limit_kmh": limit_kmh, "osm_way_id": osm_way_id},
        )
    except Exception as e:
        logger.debug("Road speed cache write failed: %s", e)


def _async_warm_cache(lat: float, lon: float, cell_key: str) -> None:
    """Background: resolve PostGIS and populate RoadSpeedCache."""

    def _run():
        close_old_connections()
        try:
            row = _lookup_postgis_row(lat, lon)
            if row is not None:
                lim, wid = row
                with transaction.atomic():
                    _cache_set(cell_key, lim, osm_way_id=wid or None)
        except Exception as e:
            logger.debug("Async road speed warm failed: %s", e)
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()


def resolve_speed_limit_for_ping(
    *,
    vehicle,
    lat: float,
    lon: float,
    traccar_attributes: Optional[dict[str, Any]] = None,
) -> Tuple[float, str]:
    """
    Return (limit_kmh, source) for speeding checks and GPSPing storage.

    source is one of: traccar, cache, postgis, fallback
    """
    org = vehicle.organisation
    fallback = float(getattr(org, "speed_limit_kmh", 120) or 120)

    if not getattr(org, "road_speed_limits_enabled", False):
        return fallback, "fallback"

    tl = _traccar_road_limit_kmh(traccar_attributes)
    if tl is not None:
        return tl, "traccar"

    ck = _cell_key(lat, lon)
    cached = _cache_get(ck)
    if cached is not None:
        return cached, "cache"

    row = _lookup_postgis_row(lat, lon)
    if row is not None:
        lim, wid = row
        _cache_set(ck, lim, osm_way_id=wid or None)
        return lim, "postgis"

    _async_warm_cache(lat, lon, ck)
    return fallback, "fallback"
