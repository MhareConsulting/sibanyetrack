from datetime import timedelta

from .models import FuelEvent, FuelEventKind, FuelReading, FuelSource

# Fallback thresholds — overridden per-org via Organisation fields
_REFUEL_THRESHOLD_DEFAULT  = 8.0   # litres
_THEFT_THRESHOLD_DEFAULT   = 5.0   # litres
_THEFT_SPEED_MAX_DEFAULT   = 5.0   # km/h

DETECTION_WINDOW_MINUTES   = 10    # look back this far for comparison reading
DEDUP_WINDOW_MINUTES       = 30    # suppress duplicate theft/drain/refuel events

# Probe health
PROBE_ZERO_MIN_PREV_LITRES = 5.0   # prev level must exceed this to flag disconnected probe
PROBE_STUCK_COUNT          = 5     # consecutive identical readings = stuck probe
PROBE_STUCK_SPEED_MIN      = 10.0  # km/h — only flag stuck probe when vehicle is moving
PROBE_DEDUP_HOURS          = 1

# Excess consumption
EXCESS_WINDOW_MINUTES      = 60    # rolling window for consumption evaluation
EXCESS_FACTOR              = 1.5   # flag if actual > expected * this
EXCESS_MIN_DISTANCE_KM     = 5.0   # require at least this distance before evaluating
EXCESS_DEDUP_HOURS         = 2

# Signal processing — noise reduction
SMA_WINDOW                 = 5     # readings averaged for the "previous level" baseline
BIFURCATED_WINDOW          = 8     # total readings for bifurcated mean theft detection
REFUEL_SPEED_GATE_READINGS = 3     # number of recent readings checked for speed gate


def _org_thresholds(vehicle):
    org = vehicle.organisation
    return (
        float(org.fuel_refuel_threshold_litres),
        float(org.fuel_theft_threshold_litres),
        float(org.fuel_theft_speed_max_kmh),
    )


# ── Signal processing helpers ──────────────────────────────────────────────────

def _smoothed_level(vehicle, before_ts, n=SMA_WINDOW):
    """
    Simple Moving Average baseline: mean of the last n readings before before_ts.
    Returns None when there are not enough prior readings.
    """
    vals = list(
        FuelReading.objects
        .filter(vehicle=vehicle, device_timestamp__lt=before_ts)
        .order_by('-device_timestamp')
        .values_list('fuel_level_litres', flat=True)[:n]
    )
    return sum(vals) / len(vals) if vals else None


def _bifurcated_mean_drop(vehicle, reading, theft_thresh):
    """
    Bifurcated Mean algorithm (GpsGate 8-point method):
    Collect the last 8 non-zero readings including the current one.
    Split into two halves of 4 (oldest → newest).
    If mean(oldest_4) − mean(newest_4) > theft_thresh → genuine sustained drop.

    Returns True when the algorithm confirms a significant drop, False otherwise.
    """
    recent_vals = list(
        FuelReading.objects
        .filter(
            vehicle=vehicle,
            device_timestamp__lte=reading.device_timestamp,
            fuel_level_litres__gt=0,
        )
        .order_by('-device_timestamp')
        .values_list('fuel_level_litres', flat=True)[:BIFURCATED_WINDOW]
    )

    if len(recent_vals) < BIFURCATED_WINDOW:
        return False

    # recent_vals[0] is newest, [-1] is oldest — reverse for chronological order
    chronological = list(reversed(recent_vals))
    mean_old = sum(chronological[:4]) / 4
    mean_new = sum(chronological[4:]) / 4
    return (mean_old - mean_new) > theft_thresh


def _refuel_speed_gate(vehicle, reading):
    """
    Speed gate for refuel validation: if any of the last REFUEL_SPEED_GATE_READINGS
    readings (including this one) show speed > 5 km/h, the level rise is likely
    caused by fuel sloshing to the front during acceleration, not a real refuel.
    Returns True when the event should be suppressed (vehicle was moving).
    """
    speed_limit = 5.0
    speeds = list(
        FuelReading.objects
        .filter(
            vehicle=vehicle,
            device_timestamp__lte=reading.device_timestamp,
            speed_kmh__isnull=False,
        )
        .order_by('-device_timestamp')
        .values_list('speed_kmh', flat=True)[:REFUEL_SPEED_GATE_READINGS]
    )
    return any(s > speed_limit for s in speeds)


# ── Public entry point ─────────────────────────────────────────────────────────

def check_fuel_events(vehicle, reading):
    """
    Called after every new FuelReading is saved. Dispatches by data source:
    - CAN/OBD readings carry an ECU 'total fuel used' counter, so we cross-check
      level changes against litres actually burned (far fewer false positives).
    - Probe/estimated readings fall back to the curve-shape heuristics.
    """
    if reading.source in (FuelSource.CAN, FuelSource.OBD) and reading.total_fuel_used_litres is not None:
        _detect_can_path(vehicle, reading)
    else:
        _detect_probe_path(vehicle, reading)


def _detect_probe_path(vehicle, reading):
    """
    Legacy analog-probe detection:
    1. Probe health gate — skip detection on suspect readings.
    2. Refuel / theft / drain detection using SMA baseline + bifurcated mean.
    3. Excess consumption check.
    """
    if _check_probe_health(vehicle, reading):
        return  # Reading is suspect; probe event already created if warranted

    refuel_thresh, theft_thresh, theft_speed_max = _org_thresholds(vehicle)

    # Use SMA-smoothed baseline instead of a single previous reading.
    smoothed_prev = _smoothed_level(vehicle, reading.device_timestamp)
    if smoothed_prev is None:
        _check_excess_consumption(vehicle, reading)
        return

    delta = reading.fuel_level_litres - smoothed_prev
    dedup_start = reading.device_timestamp - timedelta(minutes=DEDUP_WINDOW_MINUTES)

    if delta >= refuel_thresh:
        # Speed gate: ignore level rises while the vehicle is moving.
        if not _refuel_speed_gate(vehicle, reading):
            _handle_refuel(vehicle, reading, smoothed_prev, delta, dedup_start)

    elif delta <= -theft_thresh:
        # Bifurcated mean confirms the drop is sustained, not a transient slosh.
        if _bifurcated_mean_drop(vehicle, reading, theft_thresh):
            speed = reading.speed_kmh or 0
            kind = FuelEventKind.THEFT if speed <= theft_speed_max else FuelEventKind.DRAIN
            _handle_loss(vehicle, reading, smoothed_prev, delta, kind, theft_thresh, dedup_start)

    _check_excess_consumption(vehicle, reading)


# ── CAN / OBD path (ECU fuel-used cross-check) ──────────────────────────────────

def _fuel_burned_since(vehicle, reading, minutes):
    """
    Litres the ECU counter says were burned over the last `minutes`, i.e.
    counter(now) − counter(earliest reading in window). Returns None when there
    aren't two counter samples, and guards against counter resets/rollover by
    discarding negative deltas (returns 0.0).
    """
    since = reading.device_timestamp - timedelta(minutes=minutes)
    vals = list(
        FuelReading.objects
        .filter(
            vehicle=vehicle,
            device_timestamp__gte=since,
            device_timestamp__lte=reading.device_timestamp,
            total_fuel_used_litres__isnull=False,
        )
        .order_by('device_timestamp')
        .values_list('total_fuel_used_litres', flat=True)
    )
    if len(vals) < 2:
        return None
    burned = vals[-1] - vals[0]
    return burned if burned >= 0 else 0.0


def _detect_can_path(vehicle, reading):
    """
    CAN/OBD detection. The OEM gives us a tank-% level (→ litres) and a monotonic
    'total fuel used' counter. Level *changes* are validated against litres the ECU
    actually burned, so a drop with no matching burn is genuine loss, and a rise with
    no burn is a refuel — no slosh/speed-gate guesswork or probe-health checks needed.
    """
    refuel_thresh, theft_thresh, theft_speed_max = _org_thresholds(vehicle)

    smoothed_prev = _smoothed_level(vehicle, reading.device_timestamp)
    if smoothed_prev is None:
        _check_excess_consumption_can(vehicle, reading)
        return

    delta = reading.fuel_level_litres - smoothed_prev
    dedup_start = reading.device_timestamp - timedelta(minutes=DEDUP_WINDOW_MINUTES)
    burned = _fuel_burned_since(vehicle, reading, DETECTION_WINDOW_MINUTES)

    if delta >= refuel_thresh:
        # A real refuel adds fuel while the engine burns ~nothing over the window.
        if burned is None or burned < refuel_thresh:
            _handle_refuel(vehicle, reading, smoothed_prev, delta, dedup_start)

    elif delta <= -theft_thresh:
        # Cross-check: litres the level lost beyond what the ECU actually burned.
        unaccounted = abs(delta) - (burned or 0.0)
        if unaccounted > theft_thresh:
            speed = reading.speed_kmh or 0
            kind = FuelEventKind.THEFT if speed <= theft_speed_max else FuelEventKind.DRAIN
            _handle_loss(vehicle, reading, smoothed_prev, delta, kind, theft_thresh, dedup_start)

    _check_excess_consumption_can(vehicle, reading)


def _check_excess_consumption_can(vehicle, reading):
    """
    Excess consumption from the ECU counter: actual L/100 km = burned litres
    (counter delta) / distance over EXCESS_WINDOW_MINUTES. More accurate than
    integrating level drops because it ignores slosh and refuels.
    """
    if not vehicle.expected_fuel_lper100km:
        return

    since = reading.device_timestamp - timedelta(minutes=EXCESS_WINDOW_MINUTES)
    readings = list(
        FuelReading.objects
        .filter(
            vehicle=vehicle,
            device_timestamp__gte=since,
            device_timestamp__lte=reading.device_timestamp,
            total_fuel_used_litres__isnull=False,
        )
        .order_by('device_timestamp')
    )
    if len(readings) < 2:
        return

    fuel_used = readings[-1].total_fuel_used_litres - readings[0].total_fuel_used_litres
    if fuel_used <= 0:  # counter reset or no burn
        return

    distance_km = 0.0
    for i in range(1, len(readings)):
        elapsed_h = (readings[i].device_timestamp - readings[i - 1].device_timestamp).total_seconds() / 3600
        avg_speed = ((readings[i].speed_kmh or 0) + (readings[i - 1].speed_kmh or 0)) / 2
        distance_km += avg_speed * elapsed_h

    if distance_km < EXCESS_MIN_DISTANCE_KM:
        return

    actual = (fuel_used / distance_km) * 100
    if actual <= vehicle.expected_fuel_lper100km * EXCESS_FACTOR:
        return

    dedup_start = reading.device_timestamp - timedelta(hours=EXCESS_DEDUP_HOURS)
    if FuelEvent.objects.filter(vehicle=vehicle, kind=FuelEventKind.EXCESS_CONSUMPTION, occurred_at__gte=dedup_start).exists():
        return

    _emit_excess_event(vehicle, reading, readings[0].fuel_level_litres, fuel_used, actual, distance_km)


# ── Probe health ───────────────────────────────────────────────────────────────

def _check_probe_health(vehicle, reading):
    """
    Returns True when the reading is suspect so that the caller skips normal detection.

    Two fault conditions:
    - Zero reading after a non-empty previous reading → likely disconnected probe.
    - Same reading value for PROBE_STUCK_COUNT consecutive readings while moving → stuck probe.
    """
    if reading.fuel_level_litres == 0:
        prev = (
            FuelReading.objects
            .filter(vehicle=vehicle, device_timestamp__lt=reading.device_timestamp)
            .order_by('-device_timestamp')
            .first()
        )
        if prev and prev.fuel_level_litres > PROBE_ZERO_MIN_PREV_LITRES:
            dedup_start = reading.device_timestamp - timedelta(hours=PROBE_DEDUP_HOURS)
            if not FuelEvent.objects.filter(vehicle=vehicle, kind=FuelEventKind.PROBE_FAULT, occurred_at__gte=dedup_start).exists():
                event = FuelEvent.objects.create(
                    vehicle=vehicle,
                    kind=FuelEventKind.PROBE_FAULT,
                    occurred_at=reading.device_timestamp,
                    level_before=prev.fuel_level_litres,
                    level_after=0,
                    delta_litres=-prev.fuel_level_litres,
                    driver_name=reading.driver_name,
                    lat=reading.lat,
                    lon=reading.lon,
                    notes="Probe reported 0 L after non-empty reading — possible disconnection.",
                )
                _push_fuel_event_to_outbox(vehicle, event)
                _raise_probe_alert(vehicle, event)
                _send_probe_email(vehicle, event)
        return True  # Always skip detection on a zero reading

    # Stuck probe: vehicle moving but probe value unchanged for N readings
    speed = reading.speed_kmh or 0
    if speed >= PROBE_STUCK_SPEED_MIN:
        recent = list(
            FuelReading.objects
            .filter(vehicle=vehicle, device_timestamp__lt=reading.device_timestamp)
            .order_by('-device_timestamp')
            .values_list('fuel_level_litres', flat=True)[:PROBE_STUCK_COUNT - 1]
        )
        if len(recent) == PROBE_STUCK_COUNT - 1 and all(abs(v - reading.fuel_level_litres) < 0.1 for v in recent):
            dedup_start = reading.device_timestamp - timedelta(hours=PROBE_DEDUP_HOURS * 2)
            if not FuelEvent.objects.filter(vehicle=vehicle, kind=FuelEventKind.PROBE_FAULT, occurred_at__gte=dedup_start).exists():
                event = FuelEvent.objects.create(
                    vehicle=vehicle,
                    kind=FuelEventKind.PROBE_FAULT,
                    occurred_at=reading.device_timestamp,
                    level_before=reading.fuel_level_litres,
                    level_after=reading.fuel_level_litres,
                    delta_litres=0,
                    driver_name=reading.driver_name,
                    lat=reading.lat,
                    lon=reading.lon,
                    notes=(
                        f"Probe stuck at {reading.fuel_level_litres:.1f} L for "
                        f"{PROBE_STUCK_COUNT}+ readings while vehicle moving at {speed:.0f} km/h."
                    ),
                )
                _push_fuel_event_to_outbox(vehicle, event)
                _raise_probe_alert(vehicle, event)
                _send_probe_email(vehicle, event)
            return True  # Skip detection — reading is unreliable

    return False


# ── Refuel / theft / drain ─────────────────────────────────────────────────────

def _handle_refuel(vehicle, reading, level_before, delta, dedup_start):
    """level_before is the SMA-smoothed baseline level (float), not a FuelReading."""
    if FuelEvent.objects.filter(vehicle=vehicle, kind=FuelEventKind.REFUEL, occurred_at__gte=dedup_start).exists():
        return
    event = FuelEvent.objects.create(
        vehicle=vehicle,
        kind=FuelEventKind.REFUEL,
        occurred_at=reading.device_timestamp,
        level_before=round(level_before, 2),
        level_after=reading.fuel_level_litres,
        delta_litres=round(delta, 2),
        driver_name=reading.driver_name,
        lat=reading.lat,
        lon=reading.lon,
    )
    _push_fuel_event_to_outbox(vehicle, event)


def _handle_loss(vehicle, reading, level_before, delta, kind, theft_thresh, dedup_start):
    """level_before is the SMA-smoothed baseline level (float), not a FuelReading."""
    if FuelEvent.objects.filter(
        vehicle=vehicle,
        kind__in=[FuelEventKind.THEFT, FuelEventKind.DRAIN],
        occurred_at__gte=dedup_start,
    ).exists():
        return

    event = FuelEvent.objects.create(
        vehicle=vehicle,
        kind=kind,
        occurred_at=reading.device_timestamp,
        level_before=round(level_before, 2),
        level_after=reading.fuel_level_litres,
        delta_litres=round(delta, 2),
        driver_name=reading.driver_name,
        lat=reading.lat,
        lon=reading.lon,
    )
    _push_fuel_event_to_outbox(vehicle, event)
    _raise_loss_alert(vehicle, event, theft_thresh)
    if kind == FuelEventKind.THEFT:
        _send_theft_email(vehicle, event)
    else:
        _send_drain_email(vehicle, event)


# ── Excess consumption ─────────────────────────────────────────────────────────

def _check_excess_consumption(vehicle, reading):
    """
    Computes actual L/100 km over the last EXCESS_WINDOW_MINUTES and flags it
    when it exceeds vehicle.expected_fuel_lper100km * EXCESS_FACTOR.
    Requires at least EXCESS_MIN_DISTANCE_KM of movement before evaluating.
    """
    if not vehicle.expected_fuel_lper100km:
        return

    since = reading.device_timestamp - timedelta(minutes=EXCESS_WINDOW_MINUTES)
    readings = list(
        FuelReading.objects
        .filter(vehicle=vehicle, device_timestamp__gte=since, device_timestamp__lte=reading.device_timestamp)
        .order_by('device_timestamp')
    )
    if len(readings) < 5:
        return

    fuel_used = 0.0
    distance_km = 0.0
    for i in range(1, len(readings)):
        delta = readings[i].fuel_level_litres - readings[i - 1].fuel_level_litres
        if -20 < delta < 0:
            fuel_used += abs(delta)
        elapsed_h = (readings[i].device_timestamp - readings[i - 1].device_timestamp).total_seconds() / 3600
        avg_speed = ((readings[i].speed_kmh or 0) + (readings[i - 1].speed_kmh or 0)) / 2
        distance_km += avg_speed * elapsed_h

    if distance_km < EXCESS_MIN_DISTANCE_KM or fuel_used == 0:
        return

    actual = (fuel_used / distance_km) * 100
    if actual <= vehicle.expected_fuel_lper100km * EXCESS_FACTOR:
        return

    dedup_start = reading.device_timestamp - timedelta(hours=EXCESS_DEDUP_HOURS)
    if FuelEvent.objects.filter(vehicle=vehicle, kind=FuelEventKind.EXCESS_CONSUMPTION, occurred_at__gte=dedup_start).exists():
        return

    _emit_excess_event(vehicle, reading, readings[0].fuel_level_litres, fuel_used, actual, distance_km)


def _emit_excess_event(vehicle, reading, level_before, fuel_used, actual, distance_km):
    event = FuelEvent.objects.create(
        vehicle=vehicle,
        kind=FuelEventKind.EXCESS_CONSUMPTION,
        occurred_at=reading.device_timestamp,
        level_before=level_before,
        level_after=reading.fuel_level_litres,
        delta_litres=-fuel_used,
        driver_name=reading.driver_name,
        lat=reading.lat,
        lon=reading.lon,
        notes=(
            f"Actual: {actual:.1f} L/100 km over last {EXCESS_WINDOW_MINUTES} min "
            f"({distance_km:.1f} km). Baseline: {vehicle.expected_fuel_lper100km:.1f} L/100 km."
        ),
    )
    _push_fuel_event_to_outbox(vehicle, event)
    _raise_excess_alert(vehicle, event, actual)
    _send_excess_email(vehicle, event, actual)


# ── SyncOutbox push ───────────────────────────────────────────────────────────

def _push_fuel_event_to_outbox(vehicle, event):
    from mytrack.tracking.models import SyncOutbox
    SyncOutbox.objects.create(
        destination=SyncOutbox.DEST_MYROUTES_FUEL,
        payload={
            "kind": "fuel_event",
            "org_slug": vehicle.organisation.slug,
            "vehicle_reg": vehicle.registration,
            "event_kind": event.kind,
            "occurred_at": event.occurred_at.isoformat(),
            "delta_litres": float(event.delta_litres),
            "level_before": float(event.level_before),
            "level_after": float(event.level_after),
            "driver_name": event.driver_name or "",
            "lat": event.lat,
            "lon": event.lon,
            "mytrack_event_id": event.pk,
        },
    )


# ── Alert helpers ──────────────────────────────────────────────────────────────

def _raise_loss_alert(vehicle, event, threshold):
    import threading
    from mytrack.tracking.models import Alert, AlertKind, AlertSeverity, default_severity_for_kind
    kind = AlertKind.FUEL_THEFT if event.kind == FuelEventKind.THEFT else AlertKind.FUEL_DRAIN
    severity = default_severity_for_kind(kind)
    alert = Alert.objects.create(
        vehicle=vehicle,
        kind=kind,
        severity=severity,
        value=abs(event.delta_litres),
        threshold=threshold,
        occurred_at=event.occurred_at,
        driver_name=event.driver_name,
    )
    if severity == AlertSeverity.CRITICAL and getattr(vehicle.organisation, "notify_critical_instant", True):
        from mytrack.notifications.emails import send_critical_alert_email
        threading.Thread(target=send_critical_alert_email, args=(alert,), daemon=True).start()
    if event.kind == FuelEventKind.THEFT:
        try:
            from mytrack.webhooks.dispatch import fire_webhook
            fire_webhook(vehicle.organisation, "fuel.theft", {
                "alert_id": alert.pk,
                "vehicle_reg": vehicle.registration,
                "delta_litres": round(abs(event.delta_litres), 2),
                "occurred_at": str(event.occurred_at),
            })
        except Exception:
            pass


def _raise_probe_alert(vehicle, event):
    from mytrack.tracking.models import Alert, AlertKind, default_severity_for_kind
    Alert.objects.create(
        vehicle=vehicle,
        kind=AlertKind.PROBE_FAULT,
        severity=default_severity_for_kind(AlertKind.PROBE_FAULT),
        value=abs(event.delta_litres),
        threshold=0,
        occurred_at=event.occurred_at,
        driver_name=event.driver_name,
    )


def _raise_excess_alert(vehicle, event, actual_lper100km):
    from mytrack.tracking.models import Alert, AlertKind, default_severity_for_kind
    Alert.objects.create(
        vehicle=vehicle,
        kind=AlertKind.EXCESS_CONSUMPTION,
        severity=default_severity_for_kind(AlertKind.EXCESS_CONSUMPTION),
        value=round(actual_lper100km, 1),
        threshold=vehicle.expected_fuel_lper100km,
        occurred_at=event.occurred_at,
        driver_name=event.driver_name,
    )


# ── Email helpers ──────────────────────────────────────────────────────────────

def _send_theft_email(vehicle, event):
    try:
        from mytrack.notifications.emails import send_fuel_theft_alert
        send_fuel_theft_alert(vehicle, event)
    except Exception:
        pass


def _send_drain_email(vehicle, event):
    try:
        from mytrack.notifications.emails import send_fuel_drain_alert
        send_fuel_drain_alert(vehicle, event)
    except Exception:
        pass


def _send_probe_email(vehicle, event):
    try:
        from mytrack.notifications.emails import send_probe_fault_alert
        send_probe_fault_alert(vehicle, event)
    except Exception:
        pass


def _send_excess_email(vehicle, event, actual_lper100km):
    try:
        from mytrack.notifications.emails import send_excess_consumption_alert
        send_excess_consumption_alert(vehicle, event, actual_lper100km)
    except Exception:
        pass
