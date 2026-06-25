from django.utils import timezone

from mytrack.notifications.service import send_email

EXPIRY_THRESHOLDS = [30, 7, 1]


def _org_recipient_emails(organisation):
    from mytrack.tenancy.models import User, Role
    return list(
        User.objects.filter(
            organisation=organisation,
            role__in=[Role.ADMIN, Role.DISPATCHER],
            is_active=True,
            email__gt="",
        ).values_list("email", flat=True)
    )


def _parse_cc_emails(organisation):
    """Return validated unique CC addresses from organisation.notification_cc_emails."""
    raw = (organisation.notification_cc_emails or "").replace(";", ",").replace("\n", ",")
    seen = set()
    out = []
    for part in raw.split(","):
        addr = part.strip()
        if not addr or "@" not in addr or len(addr) > 254:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def _org_notification_recipients(organisation):
    """Admin/dispatcher emails plus optional CCs (scheduled notification emails only)."""
    base = _org_recipient_emails(organisation)
    extra = _parse_cc_emails(organisation)
    seen = {e.lower() for e in base}
    merged = list(base)
    for e in extra:
        if e.lower() not in seen:
            seen.add(e.lower())
            merged.append(e)
    return merged


def _base_html(org_name, title, table_rows, table_headers):
    headers_html = "".join(
        f"<th style='padding:6px 12px;text-align:left;background:#1e3a5f;color:#fff'>{h}</th>"
        for h in table_headers
    )
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto">
      <div style="background:#1e3a5f;padding:16px 24px">
        <h2 style="color:#fff;margin:0">myTrack — {title}</h2>
        <p style="color:#93c5fd;margin:4px 0 0">{org_name}</p>
      </div>
      <div style="padding:24px">
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <thead><tr>{headers_html}</tr></thead>
          <tbody>{"".join(table_rows)}</tbody>
        </table>
      </div>
      <div style="padding:12px 24px;background:#f1f5f9;font-size:12px;color:#64748b">
        This is an automated notification from myTrack. Do not reply to this email.
      </div>
    </div>
    """


def _kv_html(org_name, title, pairs):
    """Simple key-value layout for single-event notifications."""
    rows = "".join(
        f"<tr><td style='padding:8px 12px;font-weight:bold;color:#374151;width:140px'>{k}</td>"
        f"<td style='padding:8px 12px;color:#111827'>{v}</td></tr>"
        for k, v in pairs
    )
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto">
      <div style="background:#1e3a5f;padding:16px 24px">
        <h2 style="color:#fff;margin:0">myTrack — {title}</h2>
        <p style="color:#93c5fd;margin:4px 0 0">{org_name}</p>
      </div>
      <div style="padding:24px">
        <table style="width:100%;border-collapse:collapse;font-size:14px;border:1px solid #e5e7eb;border-radius:6px">
          <tbody>{rows}</tbody>
        </table>
      </div>
      <div style="padding:12px 24px;background:#f1f5f9;font-size:12px;color:#64748b">
        This is an automated notification from myTrack. Do not reply to this email.
      </div>
    </div>
    """


def _alert_digest_kind_label(alert):
    return alert.get_kind_display()


def _alert_digest_detail(alert):
    """Human-readable detail column for daily digest rows."""
    from mytrack.tracking.models import AlertKind

    k = alert.kind
    if k == AlertKind.SPEEDING:
        return f"{alert.value:.0f} km/h (limit {alert.threshold:.0f})"
    if k == AlertKind.IDLE:
        return f"{alert.value:.0f} min idle (threshold {alert.threshold:.0f})"
    if k in (AlertKind.FUEL_THEFT, AlertKind.FUEL_DRAIN):
        return f"{alert.value:.1f} L (threshold {alert.threshold:.1f} L)"
    if k == AlertKind.PROBE_FAULT:
        return f"Probe delta {alert.value:.1f} L"
    if k == AlertKind.EXCESS_CONSUMPTION:
        return f"{alert.value:.1f} L/100 km (baseline {alert.threshold:.1f})"
    if k in (
        AlertKind.HARSH_BRAKING,
        AlertKind.HARSH_ACCEL,
        AlertKind.LANE_DEPARTURE,
        AlertKind.FATIGUE,
        AlertKind.PHONE_USE,
        AlertKind.SEATBELT,
        AlertKind.CAMERA_EVENT,
    ):
        if alert.value == 1.0 and alert.threshold == 0.0:
            return "Event detected"
        return f"Value {alert.value:g} / threshold {alert.threshold:g}"
    return f"Value {alert.value:g} / threshold {alert.threshold:g}"


# ── Expiry warnings ───────────────────────────────────────────────────────────

def _expiry_row(label, expiry_date, days_remaining):
    if days_remaining == 0:
        badge = '<span style="color:#b91c1c;font-weight:bold">Expires TODAY</span>'
    elif days_remaining < 0:
        badge = f'<span style="color:#b91c1c;font-weight:bold">Expired {abs(days_remaining)}d ago</span>'
    else:
        badge = f'<span style="color:#b45309;font-weight:bold">In {days_remaining} day{"s" if days_remaining != 1 else ""}</span>'
    return (
        f"<tr><td style='padding:6px 12px'>{label}</td>"
        f"<td style='padding:6px 12px'>{expiry_date}</td>"
        f"<td style='padding:6px 12px'>{badge}</td></tr>"
    )


def send_expiry_warnings(dry_run=False):
    """
    Check driver licence/PDP and vehicle document expiry for all organisations.
    Sends a single email per org if any item hits a threshold (30, 7, or 1 day).
    Returns list of (org_name, warning_count, recipients) tuples.
    """
    from mytrack.compliance.models import VehicleDocument
    from mytrack.drivers.models import Driver
    from mytrack.tenancy.models import Organisation

    today = timezone.now().date()
    results = []

    for org in Organisation.objects.all():
        if not org.email_expiry_warnings_enabled:
            continue

        rows = []

        for driver in Driver.objects.filter(organisation=org, is_active=True):
            if driver.licence_expiry:
                days = (driver.licence_expiry - today).days
                if days in EXPIRY_THRESHOLDS or days == 0:
                    rows.append(_expiry_row(f"{driver.full_name} — Licence", driver.licence_expiry, days))

            if driver.pdp_expiry:
                days = (driver.pdp_expiry - today).days
                if days in EXPIRY_THRESHOLDS or days == 0:
                    rows.append(_expiry_row(f"{driver.full_name} — PDP", driver.pdp_expiry, days))

        for doc in VehicleDocument.objects.filter(
            vehicle__organisation=org, expiry_date__isnull=False
        ).select_related('vehicle'):
            days = (doc.expiry_date - today).days
            if days <= doc.warning_days or days == 0:
                label = f"{doc.vehicle.registration} — {doc.get_kind_display()}"
                if doc.label:
                    label += f" ({doc.label})"
                rows.append(_expiry_row(label, doc.expiry_date, days))

        if not rows:
            continue

        recipients = _org_notification_recipients(org)
        if not recipients:
            continue

        html = _base_html(
            org_name=org.name,
            title="Document Expiry Warning",
            table_rows=rows,
            table_headers=["Document", "Expiry Date", "Status"],
        )

        if not dry_run:
            send_email(recipients, f"[myTrack] Document expiry warning — {org.name}", html)

        results.append((org.name, len(rows), recipients))

    return results


# ── Alert digest ──────────────────────────────────────────────────────────────

def send_alert_digest(dry_run=False):
    """
    Send a daily digest of unresolved alerts (last 24 h) per organisation.
    Returns list of (org_name, alert_count, recipients) tuples.
    """
    from mytrack.tracking.models import Alert
    from mytrack.tenancy.models import Organisation

    since = timezone.now() - timezone.timedelta(hours=24)
    results = []

    for org in Organisation.objects.all():
        if not org.email_daily_digest_enabled:
            continue

        alerts = (
            Alert.objects.filter(
                vehicle__organisation=org,
                occurred_at__gte=since,
                resolved_at__isnull=True,
            )
            .select_related("vehicle")
            .order_by("-occurred_at")
        )

        if not alerts.exists():
            continue

        recipients = _org_notification_recipients(org)
        if not recipients:
            continue

        rows = []
        for alert in alerts:
            occurred = timezone.localtime(alert.occurred_at).strftime("%d %b %H:%M")
            rows.append(
                f"<tr>"
                f"<td style='padding:6px 12px'>{alert.vehicle}</td>"
                f"<td style='padding:6px 12px'>{alert.driver_name or '—'}</td>"
                f"<td style='padding:6px 12px'>{_alert_digest_kind_label(alert)}</td>"
                f"<td style='padding:6px 12px'>{_alert_digest_detail(alert)}</td>"
                f"<td style='padding:6px 12px'>{occurred}</td>"
                f"</tr>"
            )

        html = _base_html(
            org_name=org.name,
            title="Daily Alert Digest",
            table_rows=rows,
            table_headers=["Vehicle", "Driver", "Type", "Detail", "Time"],
        )

        if not dry_run:
            send_email(recipients, f"[myTrack] Daily alert digest — {org.name}", html)

        results.append((org.name, len(rows), recipients))

    return results


# ── Real-time: speeding alert ─────────────────────────────────────────────────

def send_speeding_alert(alert):
    """Fires immediately when a speeding Alert is created."""
    org = alert.vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    occurred = timezone.localtime(alert.occurred_at).strftime("%d %b %Y %H:%M")
    excess = alert.value - alert.threshold

    html = _kv_html(
        org_name=org.name,
        title="Speeding Alert",
        pairs=[
            ("Vehicle", str(alert.vehicle)),
            ("Driver", alert.driver_name or "—"),
            ("Speed", f'<span style="color:#b91c1c;font-weight:bold">{alert.value:.0f} km/h</span>'),
            ("Limit", f"{alert.threshold:.0f} km/h"),
            ("Excess", f"+{excess:.0f} km/h over limit"),
            ("Time", occurred),
        ],
    )
    send_email(
        recipients,
        f"[myTrack] Speeding alert — {alert.vehicle} at {alert.value:.0f} km/h",
        html,
    )


# ── Real-time: failed inspection ──────────────────────────────────────────────

def send_inspection_alert(inspection):
    """Fires immediately when an inspection with result DEFECT or FAIL is saved."""
    org = inspection.vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    result_colour = "#b91c1c" if inspection.result == "fail" else "#b45309"
    submitted = timezone.localtime(inspection.submitted_at).strftime("%d %b %Y %H:%M")

    pairs = [
        ("Vehicle", str(inspection.vehicle)),
        ("Driver", inspection.driver_name or "—"),
        ("Type", inspection.get_inspection_type_display()),
        ("Result", f'<span style="color:{result_colour};font-weight:bold">{inspection.get_result_display()}</span>'),
        ("Time", submitted),
    ]
    if inspection.defects:
        pairs.append(("Defects", inspection.defects.replace("\n", "<br>")))
    if inspection.notes:
        pairs.append(("Notes", inspection.notes.replace("\n", "<br>")))

    html = _kv_html(
        org_name=org.name,
        title=f"Failed Inspection — {inspection.get_result_display()}",
        pairs=pairs,
    )
    send_email(
        recipients,
        f"[myTrack] Failed inspection — {inspection.vehicle} ({inspection.get_result_display()})",
        html,
    )


# ── Real-time: geofence entry/exit ────────────────────────────────────────────

def send_geofence_alert(event):
    """Fires immediately when a vehicle enters or exits a geofence."""
    org = event.vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    kind_label = "Entered" if event.kind == "enter" else "Exited"
    colour = "#15803d" if event.kind == "enter" else "#b45309"
    occurred = timezone.localtime(event.occurred_at).strftime("%d %b %Y %H:%M")

    html = _kv_html(
        org_name=org.name,
        title=f"Geofence {kind_label}",
        pairs=[
            ("Vehicle", str(event.vehicle)),
            ("Driver", event.driver_name or "—"),
            ("Geofence", event.geofence.name),
            ("Event", f'<span style="color:{colour};font-weight:bold">{kind_label}</span>'),
            ("Time", occurred),
        ],
    )
    send_email(
        recipients,
        f"[myTrack] {event.vehicle} {kind_label.lower()} {event.geofence.name}",
        html,
    )


# ── Weekly / monthly fleet + safety summaries ────────────────────────────────

def _alert_kind_counts_rows(alerts_qs):
    from django.db.models import Count
    from mytrack.tracking.models import AlertKind

    rows = list(alerts_qs.values("kind").annotate(c=Count("id")).order_by("-c", "kind"))
    labels = dict(AlertKind.choices)
    return [(labels.get(r["kind"], r["kind"]), r["c"]) for r in rows]


def _video_asset_counts_by_trigger(video_qs):
    from django.db.models import Count
    from mytrack.video_telematics.models import VideoTrigger

    raw = list(video_qs.values("trigger_type").annotate(c=Count("id")).order_by("-c"))
    labels = dict(VideoTrigger.choices)
    return [(labels.get(r["trigger_type"], r["trigger_type"]), r["c"]) for r in raw]


def _top_vehicles_by_alert_count(alerts_qs, limit=5):
    from django.db.models import Count
    from mytrack.vehicles.models import Vehicle

    agg = list(
        alerts_qs.values("vehicle_id").annotate(total=Count("id")).order_by("-total")[:limit]
    )
    if not agg:
        return []
    ids = [r["vehicle_id"] for r in agg]
    vehicles = {v.id: v for v in Vehicle.objects.filter(pk__in=ids)}
    out = []
    for r in agg:
        v = vehicles.get(r["vehicle_id"])
        label = str(v) if v else f"Vehicle #{r['vehicle_id']}"
        out.append((label, r["total"]))
    return out


def _safety_and_video_section_html(heading, alerts_qs, video_qs, mom_alert_delta=None):
    from django.utils.html import escape

    kind_rows = _alert_kind_counts_rows(alerts_qs)
    total_alerts = alerts_qs.count()
    total_video = video_qs.count()
    trigger_rows = _video_asset_counts_by_trigger(video_qs)
    top_vehicles = _top_vehicles_by_alert_count(alerts_qs)

    mom_note = ""
    if mom_alert_delta is not None:
        mom_note = (
            f' <span style="color:#64748b;font-size:13px">'
            f"({mom_alert_delta:+d} vs prior calendar month)</span>"
        )

    parts = [
        f"<h3 style='margin:24px 0 8px;font-size:14px;color:#374151'>{escape(heading)}</h3>",
        "<p style='margin:0 0 12px;font-size:14px;color:#374151'>"
        f"<strong>Total alerts</strong>: {total_alerts}{mom_note}"
        f" &nbsp;·&nbsp; <strong>Video clips</strong>: {total_video}"
        "</p>",
    ]

    if kind_rows:
        body = "".join(
            f"<tr><td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{escape(label)}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:right'>{c}</td></tr>"
            for label, c in kind_rows
        )
        parts.append(
            "<table style='width:100%;border-collapse:collapse;font-size:14px;border:1px solid #e5e7eb'>"
            "<thead><tr>"
            "<th style='padding:6px 12px;text-align:left;background:#f8fafc;color:#334155'>Alert type</th>"
            "<th style='padding:6px 12px;text-align:right;background:#f8fafc;color:#334155'>Count</th>"
            "</tr></thead><tbody>"
            f"{body}</tbody></table>"
        )

    if trigger_rows and total_video > 0:
        tbody = "".join(
            f"<tr><td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{escape(label)}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:right'>{c}</td></tr>"
            for label, c in trigger_rows
        )
        parts.append(
            "<h4 style='margin:20px 0 8px;font-size:13px;color:#374151'>Video clips by trigger</h4>"
            "<table style='width:100%;border-collapse:collapse;font-size:14px;border:1px solid #e5e7eb'>"
            "<thead><tr>"
            "<th style='padding:6px 12px;text-align:left;background:#f8fafc;color:#334155'>Trigger</th>"
            "<th style='padding:6px 12px;text-align:right;background:#f8fafc;color:#334155'>Count</th>"
            "</tr></thead><tbody>"
            f"{tbody}</tbody></table>"
        )

    if top_vehicles:
        tbody = "".join(
            f"<tr><td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{escape(label)}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:right'>{c}</td></tr>"
            for label, c in top_vehicles
        )
        parts.append(
            "<h4 style='margin:20px 0 8px;font-size:13px;color:#374151'>Top vehicles by alert count</h4>"
            "<table style='width:100%;border-collapse:collapse;font-size:14px;border:1px solid #e5e7eb'>"
            "<thead><tr>"
            "<th style='padding:6px 12px;text-align:left;background:#f8fafc;color:#334155'>Vehicle</th>"
            "<th style='padding:6px 12px;text-align:right;background:#f8fafc;color:#334155'>Alerts</th>"
            "</tr></thead><tbody>"
            f"{tbody}</tbody></table>"
        )

    return "".join(parts)


def _org_fleet_safety_email_html(
    org,
    period_start,
    period_end_exclusive,
    *,
    title,
    header_subtitle,
    safety_section_heading,
    trip_row_label,
    distance_row_label,
    alert_total_row_label,
    open_alerts_row_html=None,
    mom_alert_delta=None,
):
    from django.db.models import Sum, Q
    from mytrack.compliance.models import VehicleDocument
    from mytrack.drivers.models import Driver
    from mytrack.tracking.models import TrackedTrip, Alert
    from mytrack.video_telematics.models import VideoAsset

    now = timezone.now()
    trips = TrackedTrip.objects.filter(
        vehicle__organisation=org,
        started_at__gte=period_start,
        started_at__lt=period_end_exclusive,
    )
    trip_count = trips.count()
    total_distance = trips.aggregate(total=Sum("distance_km"))["total"] or 0

    alerts_qs = Alert.objects.filter(
        vehicle__organisation=org,
        occurred_at__gte=period_start,
        occurred_at__lt=period_end_exclusive,
    )
    video_qs = VideoAsset.objects.filter(
        organisation=org,
        occurred_at__gte=period_start,
        occurred_at__lt=period_end_exclusive,
    )
    total_alert_count = alerts_qs.count()

    today = now.date()
    thirty_days = today + timezone.timedelta(days=30)

    expiring_drivers = Driver.objects.filter(
        organisation=org,
        is_active=True,
    ).filter(
        Q(licence_expiry__lte=thirty_days, licence_expiry__gte=today)
        | Q(pdp_expiry__lte=thirty_days, pdp_expiry__gte=today)
    )
    expiring_docs = VehicleDocument.objects.filter(
        vehicle__organisation=org,
        expiry_date__lte=thirty_days,
        expiry_date__gte=today,
    )
    expiring_count = expiring_drivers.count() + expiring_docs.count()

    summary_rows = [
        f"<tr><td style='padding:8px 12px;font-weight:bold'>{trip_row_label}</td>"
        f"<td style='padding:8px 12px'>{trip_count}</td></tr>",
        f"<tr><td style='padding:8px 12px;font-weight:bold'>{distance_row_label}</td>"
        f"<td style='padding:8px 12px'>{total_distance:.0f} km</td></tr>",
        f"<tr><td style='padding:8px 12px;font-weight:bold'>{alert_total_row_label}</td>"
        f"<td style='padding:8px 12px'>{total_alert_count}</td></tr>",
    ]
    if open_alerts_row_html:
        summary_rows.append(open_alerts_row_html)
    summary_rows.append(
        f"<tr><td style='padding:8px 12px;font-weight:bold'>Docs expiring (30d)</td>"
        f"<td style='padding:8px 12px'>{expiring_count} item(s)</td></tr>"
    )

    expiry_rows = []
    for d in expiring_drivers:
        if d.licence_expiry and d.licence_expiry <= thirty_days:
            days = (d.licence_expiry - today).days
            expiry_rows.append(
                f"<tr><td style='padding:6px 12px'>{d.full_name} — Licence</td>"
                f"<td style='padding:6px 12px'>{d.licence_expiry}</td>"
                f"<td style='padding:6px 12px;color:#b45309'>{days}d remaining</td></tr>"
            )
        if d.pdp_expiry and d.pdp_expiry <= thirty_days:
            days = (d.pdp_expiry - today).days
            expiry_rows.append(
                f"<tr><td style='padding:6px 12px'>{d.full_name} — PDP</td>"
                f"<td style='padding:6px 12px'>{d.pdp_expiry}</td>"
                f"<td style='padding:6px 12px;color:#b45309'>{days}d remaining</td></tr>"
            )
    for doc in expiring_docs.select_related("vehicle"):
        days = (doc.expiry_date - today).days
        label = f"{doc.vehicle.registration} — {doc.get_kind_display()}"
        if doc.label:
            label += f" ({doc.label})"
        expiry_rows.append(
            f"<tr><td style='padding:6px 12px'>{label}</td>"
            f"<td style='padding:6px 12px'>{doc.expiry_date}</td>"
            f"<td style='padding:6px 12px;color:#b45309'>{days}d remaining</td></tr>"
        )

    expiry_section = ""
    if expiry_rows:
        expiry_section = (
            "<h3 style='margin:24px 0 8px;font-size:14px;color:#374151'>Expiring Documents</h3>"
            "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
            "<thead><tr>"
            "<th style='padding:6px 12px;text-align:left;background:#1e3a5f;color:#fff'>Driver / Document</th>"
            "<th style='padding:6px 12px;text-align:left;background:#1e3a5f;color:#fff'>Expiry</th>"
            "<th style='padding:6px 12px;text-align:left;background:#1e3a5f;color:#fff'>Status</th>"
            "</tr></thead><tbody>"
            + "".join(expiry_rows)
            + "</tbody></table>"
        )

    safety_section = _safety_and_video_section_html(
        safety_section_heading, alerts_qs, video_qs, mom_alert_delta=mom_alert_delta
    )

    return f"""
        <div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto">
          <div style="background:#1e3a5f;padding:16px 24px">
            <h2 style="color:#fff;margin:0">myTrack — {title}</h2>
            <p style="color:#93c5fd;margin:4px 0 0">{org.name} &nbsp;·&nbsp; {header_subtitle}</p>
          </div>
          <div style="padding:24px">
            <table style="width:100%;border-collapse:collapse;font-size:14px;border:1px solid #e5e7eb">
              <tbody>{"".join(summary_rows)}</tbody>
            </table>
            {safety_section}
            {expiry_section}
          </div>
          <div style="padding:12px 24px;background:#f1f5f9;font-size:12px;color:#64748b">
            This is an automated notification from myTrack. Do not reply to this email.
          </div>
        </div>
        """


def send_weekly_summary(dry_run=False):
    """
    Send a weekly fleet and safety summary per organisation.
    Returns list of (org_name, recipients) tuples.
    """
    from mytrack.tenancy.models import Organisation

    since = timezone.now() - timezone.timedelta(days=7)
    period_end = timezone.now()
    week_start = since.strftime("%d %b")
    week_end = period_end.strftime("%d %b %Y")
    results = []

    for org in Organisation.objects.all():
        if not org.email_weekly_summary_enabled:
            continue

        recipients = _org_notification_recipients(org)
        if not recipients:
            continue

        html = _org_fleet_safety_email_html(
            org,
            since,
            period_end,
            title="Weekly Fleet and Safety Summary",
            header_subtitle=f"{week_start} – {week_end}",
            safety_section_heading="Safety and video (last 7 days)",
            trip_row_label="Trips (7 days)",
            distance_row_label="Distance (7 days)",
            alert_total_row_label="Total alerts (7 days)",
        )

        if not dry_run:
            send_email(recipients, f"[myTrack] Weekly fleet and safety summary — {org.name}", html)

        results.append((org.name, recipients))

    return results


def send_monthly_summary(dry_run=False):
    """
    Send a fleet and safety summary for the previous calendar month per organisation.
    Returns list of (org_name, recipients) tuples.
    """
    import datetime as dt

    from mytrack.tenancy.models import Organisation
    from mytrack.tracking.models import Alert

    tz = timezone.get_current_timezone()
    today_local = timezone.localdate()
    first_this_month = today_local.replace(day=1)
    last_prev_month_day = first_this_month - dt.timedelta(days=1)
    first_prev_month = last_prev_month_day.replace(day=1)
    period_start = timezone.make_aware(
        dt.datetime.combine(first_prev_month, dt.time.min),
        tz,
    )
    period_end_exclusive = timezone.make_aware(
        dt.datetime.combine(first_this_month, dt.time.min),
        tz,
    )

    first_prev2 = (first_prev_month - dt.timedelta(days=1)).replace(day=1)
    prev_period_start = timezone.make_aware(
        dt.datetime.combine(first_prev2, dt.time.min),
        tz,
    )
    prev_period_end_exclusive = period_start

    month_title = first_prev_month.strftime("%B %Y")
    results = []

    for org in Organisation.objects.all():
        if not org.email_monthly_summary_enabled:
            continue

        recipients = _org_notification_recipients(org)
        if not recipients:
            continue

        prev_count = Alert.objects.filter(
            vehicle__organisation=org,
            occurred_at__gte=prev_period_start,
            occurred_at__lt=prev_period_end_exclusive,
        ).count()
        curr_count = Alert.objects.filter(
            vehicle__organisation=org,
            occurred_at__gte=period_start,
            occurred_at__lt=period_end_exclusive,
        ).count()
        mom_delta = curr_count - prev_count

        open_alerts = Alert.objects.filter(
            vehicle__organisation=org,
            resolved_at__isnull=True,
        ).count()
        open_row = (
            f"<tr><td style='padding:8px 12px;font-weight:bold'>Open unresolved alerts (now)</td>"
            f"<td style='padding:8px 12px'>{open_alerts}</td></tr>"
        )

        html = _org_fleet_safety_email_html(
            org,
            period_start,
            period_end_exclusive,
            title="Monthly Fleet and Safety Summary",
            header_subtitle=month_title,
            safety_section_heading=f"Safety and video ({month_title})",
            trip_row_label=f"Trips ({month_title})",
            distance_row_label=f"Distance ({month_title})",
            alert_total_row_label=f"Total alerts ({month_title})",
            open_alerts_row_html=open_row,
            mom_alert_delta=mom_delta,
        )

        if not dry_run:
            send_email(recipients, f"[myTrack] Monthly fleet and safety summary — {org.name}", html)

        results.append((org.name, recipients))

    return results


# ── Fuel theft alert ─────────────────────────────────────────────────────────

def send_fuel_theft_alert(vehicle, event):
    """Fires immediately when a fuel theft FuelEvent is detected."""
    org = vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    from django.utils import timezone
    occurred = timezone.localtime(event.occurred_at).strftime("%d %b %Y %H:%M")

    html = _kv_html(
        org_name=org.name,
        title="Fuel Theft Detected",
        pairs=[
            ("Vehicle", str(vehicle)),
            ("Driver", event.driver_name or "—"),
            ("Level before", f"{event.level_before:.1f} L"),
            ("Level after", f'<span style="color:#b91c1c;font-weight:bold">{event.level_after:.1f} L</span>'),
            ("Loss", f'<span style="color:#b91c1c;font-weight:bold">{abs(event.delta_litres):.1f} L</span>'),
            ("Time", occurred),
        ],
    )
    send_email(
        recipients,
        f"[myTrack] Fuel theft detected — {vehicle} ({abs(event.delta_litres):.1f} L)",
        html,
    )


def send_fuel_drain_alert(vehicle, event):
    """Fires immediately when a fuel drain FuelEvent is detected (moving vehicle)."""
    org = vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    occurred = timezone.localtime(event.occurred_at).strftime("%d %b %Y %H:%M")

    html = _kv_html(
        org_name=org.name,
        title="Unexplained Fuel Drain Detected",
        pairs=[
            ("Vehicle", str(vehicle)),
            ("Driver", event.driver_name or "—"),
            ("Level before", f"{event.level_before:.1f} L"),
            ("Level after", f'<span style="color:#b45309;font-weight:bold">{event.level_after:.1f} L</span>'),
            ("Loss", f'<span style="color:#b45309;font-weight:bold">{abs(event.delta_litres):.1f} L</span>'),
            ("Note", "Vehicle was moving — possible siphon device or leak."),
            ("Time", occurred),
        ],
    )
    send_email(
        recipients,
        f"[myTrack] Fuel drain detected — {vehicle} ({abs(event.delta_litres):.1f} L)",
        html,
    )


def send_probe_fault_alert(vehicle, event):
    """Fires when a fuel probe appears disconnected or stuck."""
    org = vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    occurred = timezone.localtime(event.occurred_at).strftime("%d %b %Y %H:%M")

    html = _kv_html(
        org_name=org.name,
        title="Fuel Probe Fault Detected",
        pairs=[
            ("Vehicle", str(vehicle)),
            ("Driver", event.driver_name or "—"),
            ("Detail", event.notes or "Probe reading appears unreliable."),
            ("Time", occurred),
        ],
    )
    send_email(
        recipients,
        f"[myTrack] Fuel probe fault — {vehicle}",
        html,
    )


def send_excess_consumption_alert(vehicle, event, actual_lper100km):
    """Fires when a vehicle's rolling fuel consumption significantly exceeds its baseline."""
    org = vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    occurred = timezone.localtime(event.occurred_at).strftime("%d %b %Y %H:%M")

    html = _kv_html(
        org_name=org.name,
        title="Excessive Fuel Consumption Detected",
        pairs=[
            ("Vehicle", str(vehicle)),
            ("Driver", event.driver_name or "—"),
            ("Actual consumption", f'<span style="color:#b45309;font-weight:bold">{actual_lper100km:.1f} L/100 km</span>'),
            ("Baseline", f"{vehicle.expected_fuel_lper100km:.1f} L/100 km"),
            ("Detail", event.notes or ""),
            ("Time", occurred),
        ],
    )
    send_email(
        recipients,
        f"[myTrack] Excess fuel consumption — {vehicle} ({actual_lper100km:.1f} L/100 km)",
        html,
    )


# ── Video safety alert ───────────────────────────────────────────────────────

def send_video_safety_alert(asset):
    """Fires when a VideoAsset is created and auto-correlated to a safety Alert."""
    from django.conf import settings

    alert = asset.alert
    if not alert:
        return
    org = asset.vehicle.organisation
    recipients = _org_recipient_emails(org)
    if not recipients:
        return

    occurred = timezone.localtime(asset.occurred_at).strftime("%d %b %Y %H:%M")
    kind_label = alert.get_kind_display()
    clip_url = f"{getattr(settings, 'SITE_URL', '')}/video/{asset.pk}/"

    pairs = [
        ("Vehicle", str(asset.vehicle)),
        ("Driver", alert.driver_name or "—"),
        ("Event type", f'<span style="color:#b91c1c;font-weight:bold">{kind_label}</span>'),
        ("Occurred", occurred),
        ("Clip", f'<a href="{clip_url}" style="color:#1e3a5f">View video evidence</a>'),
    ]
    if asset.duration_seconds:
        pairs.append(("Duration", f"{asset.duration_seconds} s"))
    if asset.channel_id and hasattr(asset, "channel") and asset.channel:
        pairs.append(("Camera", str(asset.channel.name)))

    html = _kv_html(
        org_name=org.name,
        title=f"Video Evidence — {kind_label}",
        pairs=pairs,
    )
    send_email(
        recipients,
        f"[myTrack] Video evidence — {kind_label} — {asset.vehicle}",
        html,
    )


# ── Delivery tracking link ────────────────────────────────────────────────────

def send_delivery_link(share):
    """Send a live tracking link to a customer for a specific delivery."""
    from django.conf import settings

    tracking_url = f"{settings.SITE_URL}/track/{share.token}/"
    expires = timezone.localtime(share.expires_at).strftime("%d %b %Y at %H:%M")
    greeting = f"Hello {share.customer_name}," if share.customer_name else "Hello,"
    note_line = (
        f"<p style='background:#f0f1f5;border-left:3px solid #8A2BE2;padding:10px 14px;"
        f"border-radius:0 8px 8px 0;color:#374151;margin:16px 0'>{share.note}</p>"
        if share.note else ""
    )
    destination_line = (
        f"<p style='font-size:13px;color:#6b7280;margin:8px 0'>📍 Delivering to: <strong>{share.destination_address}</strong></p>"
        if share.destination_address else ""
    )

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">

      <!-- Header with gradient -->
      <div style="background:linear-gradient(135deg,#00C8FF 0%,#8A2BE2 100%);padding:28px 32px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
          <div style="width:32px;height:32px;background:rgba(255,255,255,0.25);border-radius:8px"></div>
          <span style="color:rgba(255,255,255,0.85);font-size:13px;font-weight:600;letter-spacing:0.05em">MyReach · myTrack</span>
        </div>
        <h1 style="color:#fff;margin:0;font-size:22px;font-weight:800;letter-spacing:-0.02em">Your delivery is on the way 📦</h1>
      </div>

      <!-- Body -->
      <div style="padding:28px 32px">
        <p style="color:#374151;margin:0 0 12px;font-size:15px">{greeting}</p>
        {note_line}
        {destination_line}
        <p style="color:#6b7280;font-size:14px;margin:16px 0">Track your delivery live — see exactly where the driver is and get a real-time ETA.</p>

        <!-- CTA button -->
        <div style="text-align:center;margin:28px 0">
          <a href="{tracking_url}"
             style="display:inline-block;background:linear-gradient(135deg,#00C8FF 0%,#8A2BE2 100%);
                    color:#fff;padding:14px 36px;border-radius:999px;text-decoration:none;
                    font-weight:700;font-size:15px;letter-spacing:-0.01em;
                    box-shadow:0 4px 14px -4px rgba(138,43,226,0.5)">
            Track My Delivery →
          </a>
        </div>

        <p style="font-size:12px;color:#9ca3af;text-align:center;margin:0">
          Or open: <a href="{tracking_url}" style="color:#8A2BE2;word-break:break-all">{tracking_url}</a>
        </p>
      </div>

      <!-- Footer -->
      <div style="padding:14px 32px;background:#f7f8fb;border-top:1px solid #e5e7eb">
        <p style="font-size:11px;color:#9ca3af;margin:0">
          This tracking link expires on <strong>{expires}</strong>.
          Powered by <strong>MyReach</strong> · Do not reply to this email.
        </p>
      </div>
    </div>
    """
    send_email([share.customer_email], "Your delivery is on the way — Track here", html)


def send_critical_alert_email(alert):
    """Immediate email to all org admins/dispatchers when a CRITICAL alert is created."""
    from django.conf import settings

    org = alert.vehicle.organisation
    recipients = _org_notification_recipients(org)
    if not recipients:
        return

    kind_labels = {
        "fuel_theft": "Fuel Theft", "harsh_braking": "Harsh Braking",
        "harsh_accel": "Harsh Acceleration", "harsh_cornering": "Harsh Cornering",
        "fatigue": "Driver Fatigue", "lane_departure": "Lane Departure",
        "phone_use": "Phone Use",
    }
    kind_icons = {
        "fuel_theft": "🚨", "harsh_braking": "🛑", "harsh_accel": "⚡",
        "harsh_cornering": "↪️", "fatigue": "😴", "lane_departure": "⚠️",
        "phone_use": "📱",
    }
    label = kind_labels.get(alert.kind, alert.kind.replace("_", " ").title())
    icon = kind_icons.get(alert.kind, "⚠️")
    occurred = timezone.localtime(alert.occurred_at).strftime("%d %b %Y at %H:%M")
    driver_line = f"<p style='margin:6px 0;font-size:14px'>👤 Driver: <strong>{alert.driver_name}</strong></p>" if alert.driver_name else ""
    site_url = getattr(settings, "SITE_URL", "")

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;max-width:580px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
      <div style="background:linear-gradient(135deg,#dc2626 0%,#991b1b 100%);padding:24px 32px">
        <div style="font-size:22px;font-weight:800;color:#fff">{icon} Critical Alert — {label}</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.8);margin-top:4px">{org.name}</div>
      </div>
      <div style="padding:24px 32px">
        <p style="margin:0 0 16px;font-size:15px;color:#374151">
          A critical safety event was detected and requires your attention.
        </p>
        <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:16px 20px;margin-bottom:20px">
          <p style="margin:0 0 6px;font-size:14px">🚗 Vehicle: <strong>{alert.vehicle.registration}</strong></p>
          {driver_line}
          <p style="margin:6px 0;font-size:14px">⏰ Time: <strong>{occurred}</strong></p>
          <p style="margin:6px 0;font-size:14px">📊 Observed value: <strong>{alert.value:.1f}</strong> (threshold: {alert.threshold:.1f})</p>
        </div>
        <a href="{site_url}/intelligence/events/" style="display:inline-block;background:linear-gradient(135deg,#dc2626 0%,#991b1b 100%);color:#fff;text-decoration:none;padding:10px 22px;border-radius:999px;font-weight:600;font-size:14px">View Alert</a>
      </div>
      <div style="padding:12px 32px;background:#f9fafb;font-size:11px;color:#9ca3af">
        This is an automated critical alert from myTrack. Sent immediately because your organisation has instant notifications enabled.
      </div>
    </div>
    """
    subject = f"🚨 [{org.name}] Critical: {label} — {alert.vehicle.registration}"
    send_email(recipients, subject, html)
