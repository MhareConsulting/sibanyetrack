import csv
from datetime import timedelta, datetime
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Max, Min, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from mytrack.drivers.models import Driver, DriverScore
from mytrack.geofences.models import Geofence, GeofenceEvent
from mytrack.tenancy.mixins import SESSION_KEY
from mytrack.tenancy.models import Depot, Role
from mytrack.tracking.models import Alert, AlertKind, AlertSeverity, GPSPing, TrackedTrip
from mytrack.vehicles.models import Vehicle, VehicleState


# ─── Depot context helper ─────────────────────────────────────────────────────

def _depot_context(request):
    """Returns (active_depot, accessible_depots, is_admin, extra_ctx_dict)."""
    user = request.user
    is_admin = user.role == Role.ADMIN or user.is_superuser
    accessible = user.accessible_depots()

    session_val = request.session.get(SESSION_KEY)
    if session_val is None or (session_val == "all" and not is_admin):
        active_depot = accessible.first() if not is_admin else None
    elif session_val == "all":
        active_depot = None
    else:
        try:
            active_depot = accessible.get(pk=session_val)
        except (Depot.DoesNotExist, ValueError):
            active_depot = accessible.first()

    ctx = {
        "accessible_depots": accessible,
        "active_depot": active_depot,
        "is_admin": is_admin,
    }
    return active_depot, accessible, is_admin, ctx


def _vehicle_qs(org, active_depot):
    qs = Vehicle.objects.filter(organisation=org, is_active=True)
    if active_depot:
        qs = qs.filter(home_depot=active_depot)
    return qs


def _filter_trips(org, get_params, active_depot=None):
    qs = (
        TrackedTrip.objects
        .filter(vehicle__organisation=org)
        .select_related("vehicle")
        .order_by("-started_at")
    )
    if active_depot:
        qs = qs.filter(vehicle__home_depot=active_depot)
    v = get_params.get("vehicle", "")
    d = get_params.get("date", "")
    if v:
        qs = qs.filter(vehicle_id=v)
    if d:
        parsed = parse_date(d)
        if parsed:
            day_start = timezone.make_aware(datetime.combine(parsed, datetime.min.time()))
            day_end   = timezone.make_aware(datetime.combine(parsed, datetime.max.time()))
            qs = qs.filter(started_at__range=(day_start, day_end))
    return qs


def _filter_geofence_events(org, get_params, active_depot=None):
    qs = (
        GeofenceEvent.objects
        .filter(vehicle__organisation=org)
        .select_related("vehicle", "geofence")
        .order_by("-occurred_at")
    )
    if active_depot:
        qs = qs.filter(vehicle__home_depot=active_depot)
    v  = get_params.get("vehicle", "")
    gf = get_params.get("geofence", "")
    k  = get_params.get("kind", "")
    d  = get_params.get("date", "")
    if v:  qs = qs.filter(vehicle_id=v)
    if gf: qs = qs.filter(geofence_id=gf)
    if k:  qs = qs.filter(kind=k)
    if d:
        parsed = parse_date(d)
        if parsed:
            day_start = timezone.make_aware(datetime.combine(parsed, datetime.min.time()))
            day_end   = timezone.make_aware(datetime.combine(parsed, datetime.max.time()))
            qs = qs.filter(occurred_at__range=(day_start, day_end))
    return qs


def _parse_date_range(get_params, default_days=7):
    today = timezone.localtime(timezone.now()).date()
    default_from = today - timedelta(days=default_days)
    date_from = parse_date(get_params.get("date_from", "")) or default_from
    date_to = parse_date(get_params.get("date_to", "")) or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    day_start = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(date_to, datetime.max.time()))
    return date_from, date_to, day_start, day_end


def _group_event_kinds():
    """Return grouped event kinds for unified filter UI."""
    alert_choices = dict(AlertKind.choices)
    groups = [
        ("Driving behavior", ["speeding", "idle", "harsh_braking", "harsh_accel"]),
        ("Driver safety", ["lane_departure", "fatigue", "phone_use", "seatbelt"]),
        ("Fuel and technical", ["fuel_theft", "fuel_drain", "probe_fault", "excess_consumption", "camera_event"]),
        ("Geofence", ["enter", "exit"]),
    ]
    geofence_choices = dict(GeofenceEvent.KIND_CHOICES)

    out = []
    for title, values in groups:
        items = []
        for value in values:
            if value in alert_choices:
                items.append({"value": value, "label": alert_choices[value]})
            elif value in geofence_choices:
                items.append({"value": value, "label": geofence_choices[value]})
        if items:
            out.append({"title": title, "items": items})
    return out


# ─── Fleet dashboard ──────────────────────────────────────────────────────────

@login_required
def fleet_dashboard(request):
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)

    now = timezone.now()
    local_now = timezone.localtime(now)
    today_start_utc = timezone.make_aware(
        datetime(local_now.year, local_now.month, local_now.day),
        timezone.get_current_timezone()
    )
    on_road_cutoff = now - timedelta(minutes=10)

    base_v_filter = {"vehicle__organisation": org}
    if active_depot:
        base_v_filter["vehicle__home_depot"] = active_depot

    vehicles_on_road = VehicleState.objects.filter(
        last_seen__gte=on_road_cutoff, **base_v_filter,
    ).count()

    total_km = (
        TrackedTrip.objects
        .filter(started_at__gte=today_start_utc, **base_v_filter)
        .aggregate(total=Sum("distance_km"))["total"] or 0
    )

    alerts_today = Alert.objects.filter(
        occurred_at__gte=today_start_utc, **base_v_filter,
    ).count()

    geofence_events_today = GeofenceEvent.objects.filter(
        occurred_at__gte=today_start_utc, **base_v_filter,
    ).count()

    trips_today = {
        row["vehicle_id"]: row
        for row in (
            TrackedTrip.objects
            .filter(started_at__gte=today_start_utc, **base_v_filter)
            .values("vehicle_id")
            .annotate(km_today=Sum("distance_km"), top_speed=Max("max_speed_kmh"))
        )
    }

    time_on_road = {}
    for vid, s, e in TrackedTrip.objects.filter(
        started_at__gte=today_start_utc, ended_at__isnull=False, **base_v_filter
    ).values_list("vehicle_id", "started_at", "ended_at"):
        time_on_road[vid] = time_on_road.get(vid, 0) + (e - s).total_seconds() / 60

    for vid, s in TrackedTrip.objects.filter(
        started_at__gte=today_start_utc, ended_at__isnull=True, **base_v_filter
    ).values_list("vehicle_id", "started_at"):
        time_on_road[vid] = time_on_road.get(vid, 0) + (now - s).total_seconds() / 60

    latest_trips = {
        row["vehicle_id"]: row["latest"]
        for row in (
            TrackedTrip.objects
            .filter(**base_v_filter)
            .values("vehicle_id")
            .annotate(latest=Max("id"))
        )
    }

    vehicles = _vehicle_qs(org, active_depot).select_related("state").order_by("registration")

    rows = []
    for v in vehicles:
        state = getattr(v, "state", None)
        last_seen = state.last_seen if state else None
        age_s = (now - last_seen).total_seconds() if last_seen else None
        if age_s is not None and age_s < 120:
            status = "online"
        elif age_s is not None and age_s < 600:
            status = "stale"
        else:
            status = "offline"
        tdata = trips_today.get(v.pk, {})
        rows.append({
            "vehicle": v,
            "status": status,
            "driver": state.driver_name if state else "",
            "km_today": round(tdata.get("km_today") or 0, 1),
            "time_min": round(time_on_road.get(v.pk, 0)),
            "top_speed": round(tdata.get("top_speed") or 0),
            "last_seen": last_seen,
            "latest_trip_id": latest_trips.get(v.pk),
        })

    from mytrack.reporting.models import DailyFleetHealthScore, DailyVehicleMetrics
    from django.db.models import Sum as _Sum
    today = local_now.date()
    yesterday = today - timedelta(days=1)
    _co2_today_agg = DailyVehicleMetrics.objects.filter(organisation=org, metric_date=yesterday).aggregate(total=_Sum("co2_kg"))
    co2_today = round(_co2_today_agg["total"] or 0.0, 1)
    _month_start = today.replace(day=1)
    _co2_mtd_agg = DailyVehicleMetrics.objects.filter(organisation=org, metric_date__gte=_month_start, metric_date__lte=today).aggregate(total=_Sum("co2_kg"))
    co2_mtd = round(_co2_mtd_agg["total"] or 0.0, 1)
    fleet_health = (
        DailyFleetHealthScore.objects
        .filter(organisation=org, depot=None)
        .order_by("-score_date")
        .first()
    )
    health_trend = list(
        DailyFleetHealthScore.objects
        .filter(organisation=org, depot=None)
        .order_by("score_date")
        .values_list("score", flat=True)
        [:30]
    )
    health_sparkline = ""
    if len(health_trend) >= 2:
        w, h = 120, 36
        mn, mx = min(health_trend), max(health_trend)
        rng = max(mx - mn, 1)
        pts = []
        for i, s in enumerate(health_trend):
            x = round(i / (len(health_trend) - 1) * w, 1)
            y = round(h - (s - mn) / rng * h, 1)
            pts.append(f"{x},{y}")
        health_sparkline = " ".join(pts)

    return render(request, "intelligence/dashboard.html", {
        "vehicles_on_road": vehicles_on_road,
        "total_km_today": round(total_km, 1),
        "alerts_today": alerts_today,
        "geofence_events_today": geofence_events_today,
        "rows": rows,
        "fleet_health": fleet_health,
        "health_sparkline": health_sparkline,
        "co2_today": co2_today if co2_today else None,
        "co2_mtd": co2_mtd if co2_mtd else None,
        **depot_ctx,
    })


# ─── Alerts ───────────────────────────────────────────────────────────────────

@login_required
def alert_list(request):
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)

    qs = (
        Alert.objects
        .filter(vehicle__organisation=org)
        .select_related("vehicle")
        .prefetch_related("video_assets")
        .order_by("-occurred_at")
    )
    if active_depot:
        qs = qs.filter(vehicle__home_depot=active_depot)

    kind_filter    = request.GET.get("kind", "")
    vehicle_filter = request.GET.get("vehicle", "")
    date_filter    = request.GET.get("date", "")

    if kind_filter:
        qs = qs.filter(kind=kind_filter)
    if vehicle_filter:
        qs = qs.filter(vehicle_id=vehicle_filter)
    if date_filter:
        d = parse_date(date_filter)
        if d:
            day_start = timezone.make_aware(datetime.combine(d, datetime.min.time()))
            day_end   = timezone.make_aware(datetime.combine(d, datetime.max.time()))
            qs = qs.filter(occurred_at__range=(day_start, day_end))

    open_matching_count = qs.filter(resolved_at__isnull=True).count() if (kind_filter or vehicle_filter or date_filter) else 0

    page = Paginator(qs, 50).get_page(request.GET.get("page", 1))
    vehicles = _vehicle_qs(org, active_depot).order_by("registration")

    return render(request, "intelligence/alerts.html", {
        "page_obj": page,
        "vehicles": vehicles,
        "kind_choices": AlertKind.choices,
        "kind_filter": kind_filter,
        "vehicle_filter": vehicle_filter,
        "date_filter": date_filter,
        "open_matching_count": open_matching_count,
        **depot_ctx,
    })


@login_required
def alerts_bulk_action(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    org = request.user.organisation
    action = request.POST.get("action", "")
    alert_ids = [i for i in request.POST.getlist("alert_ids") if i.isdigit()]

    if not alert_ids:
        return redirect("alert-list")

    qs = Alert.objects.filter(pk__in=alert_ids, vehicle__organisation=org)

    if action == "resolve":
        note = request.POST.get("bulk_note", "")
        qs.filter(resolved_at__isnull=True).update(
            resolved_at=timezone.now(),
            resolved_by=request.user,
            resolution_note=note,
        )
        return redirect("alert-list")

    if action == "export_pdf":
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        alerts = list(qs.select_related("vehicle").order_by("-occurred_at"))
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                leftMargin=1.5*cm, rightMargin=1.5*cm,
                                topMargin=1.5*cm, bottomMargin=1.5*cm)
        styles = getSampleStyleSheet()
        table_rows = [["Kind", "Severity", "Vehicle", "Driver", "Value", "Occurred At", "Status"]]
        for a in alerts:
            table_rows.append([
                a.get_kind_display(),
                a.severity,
                a.vehicle.registration,
                a.driver_name or "—",
                f"{a.value:.1f}",
                a.occurred_at.strftime("%d %b %Y %H:%M") if a.occurred_at else "",
                "Resolved" if a.resolved_at else "Open",
            ])
        doc.build([
            Paragraph(f"Selected Alerts — {org.name}", styles["Heading1"]),
            Paragraph(f"Generated: {timezone.localtime(timezone.now()).strftime('%d %b %Y %H:%M')}", styles["Normal"]),
            Spacer(1, 0.4*cm),
            Table(table_rows, repeatRows=1, style=_pdf_table_style()),
        ])
        buf.seek(0)
        response = HttpResponse(buf, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="selected-alerts.pdf"'
        return response

    return redirect("alert-list")


@login_required
def alert_resolve(request, alert_id):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    alert = get_object_or_404(Alert, pk=alert_id, vehicle__organisation=request.user.organisation)
    if alert.resolved_at is None:
        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user
        alert.resolution_note = request.POST.get("note", "")
        alert.save(update_fields=["resolved_at", "resolved_by", "resolution_note"])
    if request.headers.get("HX-Request"):
        return render(request, "intelligence/_alert_row.html", {"alert": alert})
    next_url = request.POST.get("next", "")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("alert-list")


@login_required
def alerts_resolve_filtered(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    org = request.user.organisation
    qs = Alert.objects.filter(vehicle__organisation=org, resolved_at__isnull=True)

    kind_filter    = request.POST.get("kind", "")
    vehicle_filter = request.POST.get("vehicle", "")
    date_filter    = request.POST.get("date", "")

    if kind_filter:
        qs = qs.filter(kind=kind_filter)
    if vehicle_filter:
        qs = qs.filter(vehicle_id=vehicle_filter)
    if date_filter:
        d = parse_date(date_filter)
        if d:
            day_start = timezone.make_aware(datetime.combine(d, datetime.min.time()))
            day_end   = timezone.make_aware(datetime.combine(d, datetime.max.time()))
            qs = qs.filter(occurred_at__range=(day_start, day_end))

    note = request.POST.get("note", "")
    qs.update(
        resolved_at=timezone.now(),
        resolved_by=request.user,
        resolution_note=note,
    )

    from django.urls import reverse
    url = reverse("alert-list")
    params = "&".join(
        f"{k}={v}" for k, v in [("kind", kind_filter), ("vehicle", vehicle_filter), ("date", date_filter)] if v
    )
    return redirect(f"{url}?{params}" if params else url)


# ─── Trips ────────────────────────────────────────────────────────────────────

@login_required
def trip_list(request):
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)

    vehicle_filter = request.GET.get("vehicle", "")
    date_filter    = request.GET.get("date", "")

    qs = _filter_trips(org, request.GET, active_depot)
    page = Paginator(qs, 50).get_page(request.GET.get("page", 1))
    vehicles = _vehicle_qs(org, active_depot).order_by("registration")

    return render(request, "intelligence/trips.html", {
        "page_obj": page,
        "vehicles": vehicles,
        "vehicle_filter": vehicle_filter,
        "date_filter": date_filter,
        **depot_ctx,
    })


@login_required
def export_sars_logbook(request):
    """Export a SARS-compliant mileage logbook CSV for a vehicle and date range."""
    import csv as _csv
    import io
    from django.http import HttpResponse

    org = request.user.organisation
    vehicle_id = request.GET.get("vehicle", "")
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")

    if not vehicle_id:
        return redirect("trip-list")

    vehicle = get_object_or_404(Vehicle, pk=vehicle_id, organisation=org)
    parsed_from = parse_date(date_from) if date_from else None
    parsed_to   = parse_date(date_to) if date_to else None

    qs = TrackedTrip.objects.filter(vehicle=vehicle, ended_at__isnull=False).order_by("started_at")
    if parsed_from:
        qs = qs.filter(started_at__date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(started_at__date__lte=parsed_to)

    # Build cumulative odometer from trip distances (approximate)
    odo = 0.0
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["Date", "Start Odometer (km)", "End Odometer (km)", "Distance (km)",
                     "Destination", "Business Purpose", "Driver"])
    for trip in qs:
        dist = trip.distance_km or 0.0
        start_odo = round(odo, 1)
        odo += dist
        end_odo = round(odo, 1)
        writer.writerow([
            trip.started_at.date().isoformat(),
            start_odo,
            end_odo,
            round(dist, 1),
            trip.destination_name or "",
            trip.business_purpose or "Business Travel",
            trip.driver_name or "",
        ])

    reg = vehicle.registration.replace(" ", "_")
    fname = f"logbook_{reg}_{date_from or 'all'}_{date_to or 'all'}.csv"
    response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    return response


@login_required
def trip_replay(request, trip_id):
    trip = get_object_or_404(TrackedTrip, pk=trip_id, vehicle__organisation=request.user.organisation)
    _, _, _, depot_ctx = _depot_context(request)
    return render(request, "intelligence/trip_replay.html", {"trip": trip, **depot_ctx})


# ─── Geofence events ──────────────────────────────────────────────────────────

@login_required
def geofence_event_list(request):
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)

    qs = _filter_geofence_events(org, request.GET, active_depot)
    page      = Paginator(qs, 50).get_page(request.GET.get("page", 1))
    vehicles  = _vehicle_qs(org, active_depot).order_by("registration")
    geofences = Geofence.objects.filter(organisation=org, is_active=True).order_by("name")

    return render(request, "intelligence/geofence_events.html", {
        "page_obj":        page,
        "vehicles":        vehicles,
        "geofences":       geofences,
        "vehicle_filter":  request.GET.get("vehicle", ""),
        "geofence_filter": request.GET.get("geofence", ""),
        "kind_filter":     request.GET.get("kind", ""),
        "date_filter":     request.GET.get("date", ""),
        "kind_choices":    GeofenceEvent.KIND_CHOICES,
        **depot_ctx,
    })


# ─── Unified events ───────────────────────────────────────────────────────────

@login_required
def unified_event_list(request):
    # Dispatcher console is the primary events landing page
    if not request.GET:
        return redirect("events-live-dashboard")
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)
    vehicles = _vehicle_qs(org, active_depot).order_by("registration")

    source_filter = request.GET.get("source", "all")
    status_filter = request.GET.get("status", "all")
    selected_kinds = [k for k in request.GET.getlist("kind") if k]
    vehicle_filter = request.GET.get("vehicle", "")
    query = request.GET.get("q", "").strip()
    per_page_raw = request.GET.get("per_page", "100")
    try:
        per_page = max(25, min(int(per_page_raw), 200))
    except (TypeError, ValueError):
        per_page = 100

    date_from, date_to, day_start, day_end = _parse_date_range(request.GET)

    alerts_qs = (
        Alert.objects.filter(
            vehicle__organisation=org,
            occurred_at__range=(day_start, day_end),
        )
        .select_related("vehicle")
        .prefetch_related("video_assets")
        .order_by("-occurred_at")
    )
    geofence_qs = (
        GeofenceEvent.objects.filter(
            vehicle__organisation=org,
            occurred_at__range=(day_start, day_end),
        )
        .select_related("vehicle", "geofence")
        .order_by("-occurred_at")
    )

    if active_depot:
        alerts_qs = alerts_qs.filter(vehicle__home_depot=active_depot)
        geofence_qs = geofence_qs.filter(vehicle__home_depot=active_depot)
    if vehicle_filter:
        alerts_qs = alerts_qs.filter(vehicle_id=vehicle_filter)
        geofence_qs = geofence_qs.filter(vehicle_id=vehicle_filter)
    if query:
        alerts_qs = alerts_qs.filter(vehicle__registration__icontains=query)
        geofence_qs = geofence_qs.filter(vehicle__registration__icontains=query)
    if selected_kinds:
        alert_kinds = [k for k in selected_kinds if k in dict(AlertKind.choices)]
        geofence_kinds = [k for k in selected_kinds if k in {k for k, _ in GeofenceEvent.KIND_CHOICES}]
        if alert_kinds:
            alerts_qs = alerts_qs.filter(kind__in=alert_kinds)
        else:
            alerts_qs = alerts_qs.none()
        if geofence_kinds:
            geofence_qs = geofence_qs.filter(kind__in=geofence_kinds)
        else:
            geofence_qs = geofence_qs.none()
    if status_filter == "open":
        alerts_qs = alerts_qs.filter(resolved_at__isnull=True)
    elif status_filter == "resolved":
        alerts_qs = alerts_qs.filter(resolved_at__isnull=False)

    event_rows = []
    include_alerts = source_filter in ("all", "alert")
    include_geofence = source_filter in ("all", "geofence")

    if include_alerts:
        for alert in alerts_qs:
            event_rows.append({
                "source": "alert",
                "occurred_at": alert.occurred_at,
                "kind": alert.kind,
                "kind_display": alert.get_kind_display(),
                "vehicle": alert.vehicle,
                "driver_name": alert.driver_name,
                "status": "resolved" if alert.resolved_at else "open",
                "record": alert,
                "video_assets": list(alert.video_assets.all()),
            })

    if include_geofence:
        for ev in geofence_qs:
            event_rows.append({
                "source": "geofence",
                "occurred_at": ev.occurred_at,
                "kind": ev.kind,
                "kind_display": ev.get_kind_display(),
                "vehicle": ev.vehicle,
                "driver_name": ev.driver_name,
                "status": "closed",
                "record": ev,
                "geofence": ev.geofence,
                "video_assets": [],
            })

    event_rows.sort(key=lambda row: row["occurred_at"], reverse=True)
    page = Paginator(event_rows, per_page).get_page(request.GET.get("page", 1))

    kind_choices = list(AlertKind.choices) + list(GeofenceEvent.KIND_CHOICES)
    return render(request, "intelligence/events_unified.html", {
        "page_obj": page,
        "vehicles": vehicles,
        "kind_choices": kind_choices,
        "kind_groups": _group_event_kinds(),
        "selected_kinds": selected_kinds,
        "source_filter": source_filter,
        "status_filter": status_filter,
        "vehicle_filter": vehicle_filter,
        "q_filter": query,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "per_page": per_page,
        **depot_ctx,
    })


_SAFETY_KINDS = frozenset({
    "speeding", "harsh_braking", "harsh_accel", "harsh_cornering",
    "lane_departure", "fatigue", "phone_use", "seatbelt", "camera_event",
})
_OPS_KINDS = frozenset({
    "idle", "fuel_theft", "fuel_drain", "probe_fault",
    "excess_consumption", "geofence_after_hours",
})


@login_required
def events_live_dashboard(request):
    import json
    from mytrack.vehicles.models import VehicleState
    org = request.user.organisation
    now = timezone.now()
    local_now = timezone.localtime(now)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    stale_cutoff = now - timedelta(minutes=15)

    # All open alerts, newest first
    open_alerts = list(
        Alert.objects.filter(vehicle__organisation=org, resolved_at__isnull=True)
        .select_related("vehicle")
        .order_by("-occurred_at")
    )

    def _cat(a):
        if a.severity == AlertSeverity.CRITICAL:
            return "critical"
        if a.kind in _SAFETY_KINDS:
            return "safety"
        return "operational"

    for a in open_alerts:
        a.cat = _cat(a)

    critical_alerts = [a for a in open_alerts if a.cat == "critical"]
    safety_alerts   = [a for a in open_alerts if a.cat == "safety"]
    ops_alerts      = [a for a in open_alerts if a.cat == "operational"]
    idle_open       = sum(1 for a in ops_alerts if a.kind == "idle")

    resolved_today  = Alert.objects.filter(
        vehicle__organisation=org,
        occurred_at__gte=today_start,
        resolved_at__isnull=False,
    ).count()

    # Worst open alert per vehicle (for map colouring)
    worst_map = {}  # vehicle_id -> category
    _rank = {"critical": 3, "safety": 2, "operational": 1}
    for a in open_alerts:
        vid = a.vehicle_id
        if _rank.get(a.cat, 0) > _rank.get(worst_map.get(vid), 0):
            worst_map[vid] = a.cat

    # Vehicle positions for map
    vs_qs = list(
        VehicleState.objects.filter(vehicle__organisation=org)
        .select_related("vehicle")
    )
    vs_ids = [vs.vehicle_id for vs in vs_qs]
    from mytrack.drivers.models import Driver as _Driver
    _assigned = {
        d.default_vehicle_id: d.full_name
        for d in _Driver.objects.filter(
            organisation=org, default_vehicle_id__in=vs_ids, is_active=True
        ).only("full_name", "default_vehicle_id")
    }
    vehicles_json = json.dumps([{
        "id": vs.vehicle_id,
        "reg": vs.vehicle.registration,
        "lat": vs.lat, "lon": vs.lon,
        "heading": vs.heading or 0,
        "speed": round(vs.speed_kmh or 0),
        "driver": vs.driver_name or _assigned.get(vs.vehicle_id, ""),
        "worst": worst_map.get(vs.vehicle_id),
        "stale": (timezone.make_aware(vs.last_seen) if timezone.is_naive(vs.last_seen) else vs.last_seen) < stale_cutoff,
    } for vs in vs_qs if vs.lat is not None and vs.lon is not None])

    # Event location for "Locate" buttons — nearest GPS ping to occurred_at
    for a in open_alerts:
        ping = (
            GPSPing.objects.filter(
                vehicle=a.vehicle,
                received_at__lte=a.occurred_at,
            )
            .order_by("-received_at")
            .values("lat", "lon")
            .first()
        )
        a.map_lon = ping["lon"] if ping else None
        a.map_lat = ping["lat"] if ping else None

    # Top offenders — open alerts
    top_offenders = list(
        Alert.objects.filter(vehicle__organisation=org, resolved_at__isnull=True)
        .values("vehicle__registration")
        .annotate(total=Count("id"))
        .order_by("-total")[:6]
    )
    max_offender = top_offenders[0]["total"] if top_offenders else 1

    # Shift dot-plot data (today per hour, safety vs ops)
    hourly = {}
    for a in Alert.objects.filter(vehicle__organisation=org, occurred_at__gte=today_start)\
            .annotate(h=ExtractHour("occurred_at", tzinfo=timezone.get_current_timezone())).values("h", "severity", "kind"):
        h = a["h"]
        bucket = hourly.setdefault(h, {"c": 0, "s": 0, "o": 0})
        if a["severity"] == "critical":
            bucket["c"] += 1
        elif a["kind"] in _SAFETY_KINDS:
            bucket["s"] += 1
        else:
            bucket["o"] += 1
    hourly_json = json.dumps([{"h": h, **hourly.get(h, {"c": 0, "s": 0, "o": 0})}
                               for h in range(24)])

    # Category breakdown (today total)
    kind_display = dict(AlertKind.choices)
    def _breakdown(kinds):
        rows = (
            Alert.objects.filter(vehicle__organisation=org,
                                 occurred_at__gte=today_start, kind__in=kinds)
            .values("kind").annotate(n=Count("id")).order_by("-n")
        )
        return [{"label": kind_display.get(r["kind"], r["kind"]), "n": r["n"]} for r in rows]

    safety_bd = _breakdown(_SAFETY_KINDS)
    ops_bd    = _breakdown(_OPS_KINDS)

    return render(request, "intelligence/events_live_dashboard.html", {
        "critical_alerts": critical_alerts,
        "safety_alerts":   safety_alerts,
        "ops_alerts":      ops_alerts,
        "critical_count":  len(critical_alerts),
        "safety_count":    len(safety_alerts),
        "ops_count":       len(ops_alerts),
        "idle_open":       idle_open,
        "resolved_today":  resolved_today,
        "vehicles_json":   vehicles_json,
        "top_offenders":   top_offenders,
        "max_offender":    max_offender,
        "hourly_json":     hourly_json,
        "safety_bd_json":  json.dumps(safety_bd),
        "ops_bd_json":     json.dumps(ops_bd),
        "now_hour":        timezone.localtime(now).hour,
    })


@login_required
def dispatcher_queue_fragment(request):
    """Returns rendered HTML for just the alert queue panel — polled by the dispatcher console."""
    import json
    from mytrack.vehicles.models import VehicleState
    org = request.user.organisation
    now = timezone.now()

    open_alerts = list(
        Alert.objects.filter(vehicle__organisation=org, resolved_at__isnull=True)
        .select_related("vehicle")
        .order_by("-occurred_at")
    )

    def _cat(a):
        if a.severity == AlertSeverity.CRITICAL:
            return "critical"
        if a.kind in _SAFETY_KINDS:
            return "safety"
        return "operational"

    for a in open_alerts:
        a.cat = _cat(a)

    for a in open_alerts:
        ping = (
            GPSPing.objects.filter(vehicle=a.vehicle, received_at__lte=a.occurred_at)
            .order_by("-received_at").values("lat", "lon").first()
        )
        a.map_lon = ping["lon"] if ping else None
        a.map_lat = ping["lat"] if ping else None

    stale_cutoff = now - timedelta(minutes=15)
    vs_qs = list(VehicleState.objects.filter(vehicle__organisation=org).select_related("vehicle"))
    worst_map = {}
    _rank = {"critical": 3, "safety": 2, "operational": 1}
    for a in open_alerts:
        if _rank.get(a.cat, 0) > _rank.get(worst_map.get(a.vehicle_id), 0):
            worst_map[a.vehicle_id] = a.cat

    from mytrack.drivers.models import Driver as _Driver
    _frag_ids = [vs.vehicle_id for vs in vs_qs]
    _frag_assigned = {
        d.default_vehicle_id: d.full_name
        for d in _Driver.objects.filter(
            organisation=org, default_vehicle_id__in=_frag_ids, is_active=True
        ).only("full_name", "default_vehicle_id")
    }
    vehicles_data = json.dumps([{
        "id": vs.vehicle_id,
        "reg": vs.vehicle.registration,
        "lat": vs.lat, "lon": vs.lon,
        "heading": vs.heading or 0,
        "speed": round(vs.speed_kmh or 0),
        "driver": vs.driver_name or _frag_assigned.get(vs.vehicle_id, ""),
        "worst": worst_map.get(vs.vehicle_id),
        "stale": (timezone.make_aware(vs.last_seen) if timezone.is_naive(vs.last_seen) else vs.last_seen) < stale_cutoff,
    } for vs in vs_qs if vs.lat is not None and vs.lon is not None])

    local_now = timezone.localtime(now)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_today = Alert.objects.filter(
        vehicle__organisation=org, occurred_at__gte=today_start, resolved_at__isnull=False,
    ).count()

    critical_alerts = [a for a in open_alerts if a.cat == "critical"]
    safety_alerts   = [a for a in open_alerts if a.cat == "safety"]
    ops_alerts      = [a for a in open_alerts if a.cat == "operational"]

    from django.http import JsonResponse
    from django.template.loader import render_to_string
    queue_html = render_to_string("intelligence/_dispatcher_queue.html", {
        "critical_alerts": critical_alerts,
        "safety_alerts":   safety_alerts,
        "ops_alerts":      ops_alerts,
        "critical_count":  len(critical_alerts),
        "safety_count":    len(safety_alerts),
        "ops_count":       len(ops_alerts),
    }, request=request)
    return JsonResponse({
        "critical_count": len(critical_alerts),
        "safety_count":   len(safety_alerts),
        "ops_count":      len(ops_alerts),
        "resolved_today": resolved_today,
        "vehicles":       vehicles_data,
        "queue_html":     queue_html,
    })


@login_required
def events_dashboard(request):
    import json
    from datetime import date as _date
    org = request.user.organisation
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    base_today = Alert.objects.filter(vehicle__organisation=org, occurred_at__gte=today_start)
    base_week = Alert.objects.filter(vehicle__organisation=org, occurred_at__gte=week_start)

    # Stat cards
    total_today = base_today.count()
    open_today = base_today.filter(resolved_at__isnull=True).count()
    resolved_today = total_today - open_today
    critical_today = base_today.filter(severity=AlertSeverity.CRITICAL).count()
    top_vehicle = (
        base_week.filter(resolved_at__isnull=True)
        .values("vehicle__registration")
        .annotate(n=Count("id"))
        .order_by("-n")
        .first()
    )

    # 7-day daily trend — fill missing days with 0
    trend_raw = {
        row["day"]: row["count"]
        for row in base_week.annotate(day=TruncDate("occurred_at"))
        .values("day").annotate(count=Count("id")).order_by("day")
    }
    dates_7d = [now.date() - timedelta(days=i) for i in range(6, -1, -1)]
    daily_labels = json.dumps([d.strftime("%a %-d %b") for d in dates_7d])
    daily_values = json.dumps([trend_raw.get(d, 0) for d in dates_7d])

    # Alert kind breakdown (top 10, 7 days)
    kind_display = dict(AlertKind.choices)
    kind_rows = (
        base_week.values("kind").annotate(count=Count("id")).order_by("-count")[:10]
    )
    kind_labels = json.dumps([kind_display.get(r["kind"], r["kind"]) for r in kind_rows])
    kind_values = json.dumps([r["count"] for r in kind_rows])

    # Per-vehicle open alerts (top 8)
    veh_rows = (
        base_week.filter(resolved_at__isnull=True)
        .values("vehicle__registration").annotate(count=Count("id"))
        .order_by("-count")[:8]
    )
    veh_labels = json.dumps([r["vehicle__registration"] for r in veh_rows])
    veh_values = json.dumps([r["count"] for r in veh_rows])

    # Hourly distribution (0–23)
    hourly_raw = {
        row["hour"]: row["count"]
        for row in base_week.annotate(hour=ExtractHour("occurred_at"))
        .values("hour").annotate(count=Count("id"))
    }
    hourly_data = json.dumps([hourly_raw.get(h, 0) for h in range(24)])

    # Recent unresolved (last 12)
    recent_open = (
        Alert.objects.filter(vehicle__organisation=org, resolved_at__isnull=True)
        .select_related("vehicle")
        .order_by("-occurred_at")[:12]
    )

    return render(request, "intelligence/events_dashboard.html", {
        "total_today": total_today,
        "open_today": open_today,
        "resolved_today": resolved_today,
        "critical_today": critical_today,
        "top_vehicle": top_vehicle,
        "daily_labels": daily_labels,
        "daily_values": daily_values,
        "kind_labels": kind_labels,
        "kind_values": kind_values,
        "veh_labels": veh_labels,
        "veh_values": veh_values,
        "hourly_data": hourly_data,
        "recent_open": recent_open,
    })


# ─── Driver Scoring ───────────────────────────────────────────────────────────

@login_required
def driver_score_list(request):
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)

    from django.db.models import Q as _Q
    drivers_qs = Driver.objects.filter(organisation=org, is_active=True)
    if active_depot:
        # Keep drivers with no default_vehicle — exclude only those explicitly in another depot.
        drivers_qs = drivers_qs.filter(
            _Q(default_vehicle__home_depot=active_depot) | _Q(default_vehicle__isnull=True)
        )

    today = timezone.localtime(timezone.now()).date()
    week_ago = today - timedelta(days=6)

    rows = []
    for driver in drivers_qs.order_by("full_name"):
        recent = list(
            driver.scores
            .filter(scored_date__gte=week_ago)
            .order_by("scored_date")
        )
        latest = recent[-1] if recent else None
        if len(recent) >= 2:
            trend = recent[-1].score - recent[0].score
        else:
            trend = 0
        rows.append({
            "driver": driver,
            "latest": latest,
            "trend": trend,
        })

    rows.sort(key=lambda r: r["latest"].score if r["latest"] else -1, reverse=True)

    _, _, _, depot_ctx = _depot_context(request)
    return render(request, "intelligence/driver_scores.html", {
        "rows": rows,
        **depot_ctx,
    })


@login_required
def driver_score_detail(request, driver_id):
    org = request.user.organisation
    driver = get_object_or_404(Driver, pk=driver_id, organisation=org)
    _, _, _, depot_ctx = _depot_context(request)

    today = timezone.localtime(timezone.now()).date()
    month_ago = today - timedelta(days=29)

    scores = list(driver.scores.filter(scored_date__gte=month_ago).order_by("scored_date"))

    return render(request, "intelligence/driver_score_detail.html", {
        "driver": driver,
        "scores": scores,
        **depot_ctx,
    })


# ─── Dwell Time ───────────────────────────────────────────────────────────────

@login_required
def dwell_time_report(request):
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)

    geofence_filter = request.GET.get("geofence", "")
    vehicle_filter  = request.GET.get("vehicle", "")
    date_from       = request.GET.get("date_from", "")
    date_to         = request.GET.get("date_to", "")

    events_qs = (
        GeofenceEvent.objects
        .filter(vehicle__organisation=org)
        .select_related("vehicle", "geofence")
        .order_by("vehicle_id", "geofence_id", "occurred_at")
    )
    if active_depot:
        events_qs = events_qs.filter(vehicle__home_depot=active_depot)
    if geofence_filter:
        events_qs = events_qs.filter(geofence_id=geofence_filter)
    if vehicle_filter:
        events_qs = events_qs.filter(vehicle_id=vehicle_filter)
    if date_from:
        parsed = parse_date(date_from)
        if parsed:
            events_qs = events_qs.filter(occurred_at__date__gte=parsed)
    if date_to:
        parsed = parse_date(date_to)
        if parsed:
            events_qs = events_qs.filter(occurred_at__date__lte=parsed)

    # Pair enter → exit events to compute dwell durations
    dwell_map = {}  # key: (vehicle_id, geofence_id) → list of dwell minutes
    pending_enters = {}  # key: (vehicle_id, geofence_id) → enter event

    for ev in events_qs:
        key = (ev.vehicle_id, ev.geofence_id)
        if ev.kind == "enter":
            pending_enters[key] = ev
        elif ev.kind == "exit":
            enter = pending_enters.pop(key, None)
            if enter:
                minutes = (ev.occurred_at - enter.occurred_at).total_seconds() / 60
                if minutes > 0:
                    entry = dwell_map.setdefault(key, {
                        "geofence": ev.geofence,
                        "vehicle": ev.vehicle,
                        "durations": [],
                        "last_visit": None,
                    })
                    entry["durations"].append(minutes)
                    if entry["last_visit"] is None or ev.occurred_at > entry["last_visit"]:
                        entry["last_visit"] = ev.occurred_at

    rows = []
    for entry in dwell_map.values():
        durations = entry["durations"]
        rows.append({
            "geofence": entry["geofence"],
            "vehicle": entry["vehicle"],
            "visits": len(durations),
            "avg_dwell": round(sum(durations) / len(durations), 1),
            "max_dwell": round(max(durations), 1),
            "last_visit": entry["last_visit"],
        })
    rows.sort(key=lambda r: r["avg_dwell"], reverse=True)

    vehicles  = _vehicle_qs(org, active_depot).order_by("registration")
    geofences = Geofence.objects.filter(organisation=org, is_active=True).order_by("name")

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="dwell-time.csv"'
        writer = csv.writer(response)
        writer.writerow(["Geofence", "Vehicle", "Visits", "Avg Dwell (min)", "Max Dwell (min)", "Last Visit"])
        for r in rows:
            writer.writerow([
                r["geofence"].name,
                r["vehicle"].registration,
                r["visits"],
                r["avg_dwell"],
                r["max_dwell"],
                r["last_visit"].strftime("%Y-%m-%d %H:%M") if r["last_visit"] else "",
            ])
        return response

    return render(request, "intelligence/dwell_time.html", {
        "rows": rows,
        "vehicles": vehicles,
        "geofences": geofences,
        "geofence_filter": geofence_filter,
        "vehicle_filter": vehicle_filter,
        "date_from": date_from,
        "date_to": date_to,
        **depot_ctx,
    })


# ─── Fleet Cost ───────────────────────────────────────────────────────────────

@login_required
def fleet_cost_report(request):
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)

    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")

    today = timezone.localtime(timezone.now()).date()
    if not date_from:
        date_from = (today - timedelta(days=29)).isoformat()
    if not date_to:
        date_to = today.isoformat()

    parsed_from = parse_date(date_from) or (today - timedelta(days=29))
    parsed_to   = parse_date(date_to) or today

    drivers_qs = Driver.objects.filter(organisation=org, is_active=True)
    if active_depot:
        drivers_qs = drivers_qs.filter(default_vehicle__home_depot=active_depot)

    from mytrack.fuel.models import FuelPriceHistory
    _price_record = FuelPriceHistory.current_for_org(org, as_of=parsed_to)
    if _price_record:
        fuel_price = float(_price_record.diesel_500ppm_zar or _price_record.petrol_95_zar or org.fuel_price_zar)
    else:
        fuel_price = float(org.fuel_price_zar)
    burn_rate      = float(org.idle_burn_rate_lph)

    rows = []
    total_idle_cost  = 0.0
    total_distance   = 0.0
    total_idle_min   = 0.0

    for driver in drivers_qs.select_related("default_vehicle").order_by("full_name"):
        agg = driver.scores.filter(
            scored_date__gte=parsed_from,
            scored_date__lte=parsed_to,
        ).aggregate(
            total_distance=Sum("distance_km"),
            total_idle=Sum("idling_minutes"),
        )
        distance   = agg["total_distance"] or 0.0
        idle_min   = agg["total_idle"] or 0.0
        idle_cost  = (idle_min / 60.0) * burn_rate * fuel_price

        total_idle_cost += idle_cost
        total_distance  += distance
        total_idle_min  += idle_min

        rows.append({
            "driver": driver,
            "vehicle": driver.default_vehicle,
            "distance_km": round(distance, 1),
            "idle_minutes": round(idle_min, 1),
            "idle_cost": round(idle_cost, 2),
        })

    rows.sort(key=lambda r: r["idle_cost"], reverse=True)

    return render(request, "intelligence/fleet_cost.html", {
        "rows": rows,
        "total_idle_cost": round(total_idle_cost, 2),
        "total_distance": round(total_distance, 1),
        "total_idle_min": round(total_idle_min, 1),
        "date_from": date_from,
        "date_to": date_to,
        "fuel_price": fuel_price,
        "burn_rate": burn_rate,
        **depot_ctx,
    })


# ─── CSV exports ──────────────────────────────────────────────────────────────

@login_required
def reports_trips_csv(request):
    org = request.user.organisation
    active_depot, _, _, _ = _depot_context(request)
    qs = _filter_trips(org, request.GET, active_depot)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="trip-summary.csv"'

    writer = csv.writer(response)
    writer.writerow(["Vehicle", "Driver", "Started", "Ended", "Duration (min)", "Distance (km)", "Top Speed (km/h)", "Pings"])
    for t in qs:
        writer.writerow([
            t.vehicle.registration,
            t.driver_name or "",
            t.started_at.strftime("%Y-%m-%d %H:%M") if t.started_at else "",
            t.ended_at.strftime("%Y-%m-%d %H:%M") if t.ended_at else "Active",
            t.duration_minutes or "",
            round(t.distance_km, 1) if t.distance_km else "",
            round(t.max_speed_kmh) if t.max_speed_kmh else "",
            t.ping_count,
        ])
    return response


@login_required
def reports_geofence_csv(request):
    org = request.user.organisation
    active_depot, _, _, _ = _depot_context(request)
    qs = _filter_geofence_events(org, request.GET, active_depot)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="geofence-events.csv"'

    writer = csv.writer(response)
    writer.writerow(["Geofence", "Vehicle", "Driver", "Event", "Occurred At", "Lat", "Lon"])
    for ev in qs:
        writer.writerow([
            ev.geofence.name,
            ev.vehicle.registration,
            ev.driver_name or "",
            ev.get_kind_display(),
            ev.occurred_at.strftime("%Y-%m-%d %H:%M") if ev.occurred_at else "",
            ev.lat,
            ev.lon,
        ])
    return response


# ─── PDF exports ──────────────────────────────────────────────────────────────

def _pdf_table_style():
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1,  0), colors.HexColor("#8A2BE2")),
        ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F8FB")]),
        ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])


@login_required
def reports_trips_pdf(request):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    org = request.user.organisation
    active_depot, _, _, _ = _depot_context(request)
    qs = _filter_trips(org, request.GET, active_depot)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()

    table_rows = [["Vehicle", "Driver", "Started", "Ended", "Duration", "Distance", "Top Speed", "Pings"]]
    for t in qs:
        table_rows.append([
            t.vehicle.registration,
            t.driver_name or "—",
            t.started_at.strftime("%d %b %H:%M") if t.started_at else "",
            t.ended_at.strftime("%d %b %H:%M") if t.ended_at else "Active",
            f"{t.duration_minutes} min" if t.duration_minutes else "—",
            f"{round(t.distance_km, 1)} km" if t.distance_km else "—",
            f"{round(t.max_speed_kmh)} km/h" if t.max_speed_kmh else "—",
            str(t.ping_count),
        ])

    doc.build([
        Paragraph(f"Trip Summary — {org.name}", styles["Heading1"]),
        Paragraph(f"Generated: {timezone.localtime(timezone.now()).strftime('%d %b %Y %H:%M')}", styles["Normal"]),
        Spacer(1, 0.4*cm),
        Table(table_rows, repeatRows=1, style=_pdf_table_style()),
    ])

    buf.seek(0)
    response = HttpResponse(buf, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="trip-summary.pdf"'
    return response


@login_required
def reports_geofence_pdf(request):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    org = request.user.organisation
    active_depot, _, _, _ = _depot_context(request)
    qs = _filter_geofence_events(org, request.GET, active_depot)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()

    table_rows = [["Geofence", "Vehicle", "Driver", "Event", "Occurred At"]]
    for ev in qs:
        table_rows.append([
            ev.geofence.name,
            ev.vehicle.registration,
            ev.driver_name or "—",
            ev.get_kind_display(),
            ev.occurred_at.strftime("%d %b %Y %H:%M") if ev.occurred_at else "",
        ])

    doc.build([
        Paragraph(f"Geofence Event Log — {org.name}", styles["Heading1"]),
        Paragraph(f"Generated: {timezone.localtime(timezone.now()).strftime('%d %b %Y %H:%M')}", styles["Normal"]),
        Spacer(1, 0.4*cm),
        Table(table_rows, repeatRows=1, style=_pdf_table_style()),
    ])

    buf.seek(0)
    response = HttpResponse(buf, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="geofence-events.pdf"'
    return response


# ─── Route Dispatch Console ───────────────────────────────────────────────────

def _myroutes_base():
    from urllib.parse import urlparse
    from django.conf import settings
    url = getattr(settings, "MYROUTES_SYNC_URL", "") or ""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme else ""


def _fetch_trips_from_myroutes(org_slug):
    import urllib.request
    import json as _json
    from django.conf import settings

    base = _myroutes_base()
    token = getattr(settings, "MYROUTES_SYNC_TOKEN", "") or ""
    if not base or not token:
        return []

    url = f"{base}/api/dispatcher/trips/today/?org_slug={org_slug}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            payload = _json.loads(r.read())
            return payload.get("trips", [])
    except Exception:
        return []


@login_required
def route_dispatch(request):
    import json as _json
    org = request.user.organisation

    trips = _fetch_trips_from_myroutes(org.slug)
    trips_json = _json.dumps(trips)

    vs_qs = list(
        VehicleState.objects.filter(vehicle__organisation=org)
        .select_related("vehicle")
    )
    vehicles_json = _json.dumps([
        {
            "id": vs.vehicle_id,
            "reg": vs.vehicle.registration,
            "lat": vs.lat,
            "lon": vs.lon,
            "heading": vs.heading or 0,
            "speed": round(vs.speed_kmh or 0),
            "driver": vs.driver_name or "",
            "trip_id": vs.myroutes_trip_id,
        }
        for vs in vs_qs
        if vs.lat is not None and vs.lon is not None
    ])

    return render(request, "intelligence/route_dispatch.html", {
        "trips_json": trips_json,
        "vehicles_json": vehicles_json,
    })


@login_required
def route_dispatch_trips_fragment(request):
    import json as _json
    from django.http import JsonResponse
    org = request.user.organisation
    trips = _fetch_trips_from_myroutes(org.slug)
    return JsonResponse({"trips": trips, "ts": timezone.now().isoformat()})
