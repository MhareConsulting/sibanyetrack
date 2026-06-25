from django.db.models import Avg, Count, Max, Sum

from .models import CustomReportDefinition, CustomReportDomain
from .query_builders import (
    fuel_event_summary,
    fuel_queryset,
    geofence_queryset,
    geofence_summary,
    route_queryset,
    speed_queryset,
    speed_summary,
)


ALLOWED_DOMAIN_COLUMNS = {
    CustomReportDomain.SPEED: {"vehicle__registration", "started_at", "ended_at", "distance_km", "max_speed_kmh", "ping_count"},
    CustomReportDomain.FUEL: {"vehicle__registration", "device_timestamp", "fuel_level_litres", "speed_kmh"},
    CustomReportDomain.GEOFENCE: {"vehicle__registration", "geofence__name", "kind", "occurred_at"},
    CustomReportDomain.ROUTE: {"vehicle__registration", "started_at", "ended_at", "distance_km", "max_speed_kmh"},
}


def _validate_fields(domain, columns):
    allowed = ALLOWED_DOMAIN_COLUMNS[domain]
    unsupported = [col for col in columns if col not in allowed]
    if unsupported:
        raise ValueError(f"Unsupported columns for {domain}: {', '.join(unsupported)}")


def run_common_report(domain, org, depot=None, params=None):
    params = params or {}
    if domain == CustomReportDomain.SPEED:
        qs = speed_queryset(org, depot=depot, params=params)
        return {"rows": qs, "summary": speed_summary(org, depot=depot, params=params)}
    if domain == CustomReportDomain.FUEL:
        qs = fuel_queryset(org, depot=depot, params=params)
        return {"rows": qs, "summary": fuel_event_summary(org, depot=depot, params=params)}
    if domain == CustomReportDomain.GEOFENCE:
        qs = geofence_queryset(org, depot=depot, params=params)
        return {"rows": qs, "summary": geofence_summary(org, depot=depot, params=params)}
    if domain == CustomReportDomain.ROUTE:
        qs = route_queryset(org, depot=depot, params=params)
        summary = {
            "trip_count": qs.count(),
            "distance_km": round(qs.aggregate(total=Sum("distance_km"))["total"] or 0.0, 2),
            "avg_top_speed": round(qs.aggregate(avg=Avg("max_speed_kmh"))["avg"] or 0.0, 2),
            "peak_speed": round(qs.aggregate(top=Max("max_speed_kmh"))["top"] or 0.0, 2),
        }
        return {"rows": qs, "summary": summary}
    raise ValueError(f"Unsupported domain: {domain}")


def _build_metric_annotations(metrics):
    annotations = {}
    for metric in metrics:
        source = metric.get("field")
        func = (metric.get("func") or "").lower()
        alias = metric.get("alias") or f"{func}_{source.replace('__', '_')}"
        if func == "sum":
            annotations[alias] = Sum(source)
        elif func == "avg":
            annotations[alias] = Avg(source)
        elif func == "max":
            annotations[alias] = Max(source)
        elif func == "count":
            annotations[alias] = Count(source)
        else:
            raise ValueError(f"Unsupported aggregate function: {func}")
    return annotations


def execute_custom_report(definition: CustomReportDefinition, depot=None):
    domain = definition.domain
    columns = definition.columns or []
    metrics = definition.metrics or []
    group_by = definition.group_by or []
    filters = definition.filters or {}

    _validate_fields(domain, columns + group_by + [m.get("field", "") for m in metrics if m.get("field")])

    result = run_common_report(domain, definition.organisation, depot=depot, params=filters)
    qs = result["rows"]
    if group_by:
        annotations = _build_metric_annotations(metrics)
        grouped_qs = qs.values(*group_by).annotate(**annotations)
        if definition.sort_by:
            grouped_qs = grouped_qs.order_by(*definition.sort_by)
        return list(grouped_qs)

    selected = columns or list(ALLOWED_DOMAIN_COLUMNS[domain])[:4]
    rows = qs.values(*selected)
    if definition.sort_by:
        rows = rows.order_by(*definition.sort_by)
    return list(rows[:5000])
