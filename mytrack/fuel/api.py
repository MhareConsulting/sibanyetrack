"""
Fuel Intelligence REST API — JSON endpoints for external consumers and mobile clients.

All endpoints require session authentication (login_required).
Responses are JSON; no DRF dependency.
"""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone

from mytrack.vehicles.models import Vehicle

from .models import FuelEvent, FuelEventKind, FuelReading


@login_required
def api_events(request):
    """
    GET /fuel/api/events/

    Query params:
        vehicle  — vehicle pk (optional)
        kind     — one of: refuel, theft, drain, probe, excess (optional)
        days     — look-back window in days, default 7
        ack      — 0 = unacknowledged only, 1 = acknowledged only (optional)
    """
    org = request.user.organisation
    qs = (
        FuelEvent.objects
        .filter(vehicle__organisation=org)
        .select_related('vehicle')
        .order_by('-occurred_at')
    )

    vehicle_id = request.GET.get('vehicle')
    kind       = request.GET.get('kind')
    days       = int(request.GET.get('days', 7))
    ack        = request.GET.get('ack')

    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
    if kind:
        qs = qs.filter(kind=kind)
    if ack == '0':
        qs = qs.filter(acknowledged=False)
    elif ack == '1':
        qs = qs.filter(acknowledged=True)

    since = timezone.now() - timedelta(days=days)
    qs = qs.filter(occurred_at__gte=since)

    events = [
        {
            'id':            e.id,
            'vehicle_id':    e.vehicle_id,
            'vehicle':       str(e.vehicle),
            'kind':          e.kind,
            'kind_display':  e.get_kind_display(),
            'occurred_at':   e.occurred_at.isoformat(),
            'level_before':  e.level_before,
            'level_after':   e.level_after,
            'delta_litres':  e.delta_litres,
            'driver_name':   e.driver_name,
            'lat':           e.lat,
            'lon':           e.lon,
            'acknowledged':  e.acknowledged,
            'notes':         e.notes,
        }
        for e in qs[:500]
    ]
    return JsonResponse({'events': events, 'count': len(events)})


@login_required
def api_vehicles(request):
    """
    GET /fuel/api/vehicles/

    Returns fleet fuel summary: latest reading per vehicle + unacknowledged alert count.
    """
    org = request.user.organisation
    vehicles = (
        Vehicle.objects
        .filter(organisation=org, is_active=True)
        .order_by('registration')
    )

    _anomaly_kinds = [
        FuelEventKind.THEFT,
        FuelEventKind.DRAIN,
        FuelEventKind.PROBE_FAULT,
        FuelEventKind.EXCESS_CONSUMPTION,
    ]

    rows = []
    for v in vehicles:
        latest = (
            FuelReading.objects
            .filter(vehicle=v)
            .order_by('-device_timestamp')
            .first()
        )
        unacked = FuelEvent.objects.filter(
            vehicle=v,
            kind__in=_anomaly_kinds,
            acknowledged=False,
        ).count()

        pct_full = None
        if latest and v.fuel_tank_capacity_litres:
            pct_full = round((latest.fuel_level_litres / v.fuel_tank_capacity_litres) * 100, 1)

        rows.append({
            'vehicle_id':            v.id,
            'registration':          v.registration,
            'label':                 v.label,
            'tank_capacity_litres':  v.fuel_tank_capacity_litres,
            'expected_lper100km':    v.expected_fuel_lper100km,
            'latest_level_litres':   latest.fuel_level_litres if latest else None,
            'pct_full':              pct_full,
            'latest_timestamp':      latest.device_timestamp.isoformat() if latest else None,
            'unacked_alerts':        unacked,
        })

    return JsonResponse({'vehicles': rows})


@login_required
def api_readings(request, vehicle_id):
    """
    GET /fuel/api/vehicles/<vehicle_id>/readings/

    Query params:
        days  — look-back window, default 1
    """
    org = request.user.organisation
    try:
        vehicle = Vehicle.objects.get(pk=vehicle_id, organisation=org)
    except Vehicle.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    days = int(request.GET.get('days', 1))
    since = timezone.now() - timedelta(days=days)

    readings = [
        {
            'timestamp':         r.device_timestamp.isoformat(),
            'fuel_level_litres': r.fuel_level_litres,
            'speed_kmh':         r.speed_kmh,
            'lat':               r.lat,
            'lon':               r.lon,
            'driver_name':       r.driver_name,
        }
        for r in FuelReading.objects
                            .filter(vehicle=vehicle, device_timestamp__gte=since)
                            .order_by('device_timestamp')
    ]
    return JsonResponse({'vehicle_id': vehicle_id, 'readings': readings, 'count': len(readings)})
