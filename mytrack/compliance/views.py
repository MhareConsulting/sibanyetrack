from collections import defaultdict
from datetime import timedelta, datetime

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from mytrack.drivers.models import Driver
from mytrack.tracking.models import Alert, AlertKind, TrackedTrip
from mytrack.vehicles.models import Vehicle

from .models import CHECKLIST_ITEMS, DocumentKind, InspectionLog, ServiceSchedule, VehicleDocument


@login_required
def driver_scorecard(request):
    """
    Compute a 7-day safety scorecard for every active Driver in the org.

    Trip/alert matching strategy (in priority order):
      1. driver_name on the trip/alert matches driver.full_name  (Traccar sends RFID)
      2. trip.vehicle == driver.default_vehicle AND driver_name is blank  (name not sent)
    This ensures drivers always appear even when Traccar does not transmit driver IDs.
    """
    org = request.user.organisation
    now = timezone.now()
    week_start = now - timedelta(days=7)

    drivers = list(Driver.objects.filter(organisation=org, is_active=True).select_related('default_vehicle'))

    rows = []
    for driver in drivers:
        # Build a Q that matches trips/alerts for this driver
        q_trips = Q(driver_name=driver.full_name)
        q_alerts = Q(driver_name=driver.full_name)
        if driver.default_vehicle_id:
            # Also capture trips on their vehicle when driver_name was not transmitted
            q_trips  |= Q(vehicle_id=driver.default_vehicle_id, driver_name='')
            q_alerts |= Q(vehicle_id=driver.default_vehicle_id, driver_name='')

        trips = list(
            TrackedTrip.objects
            .filter(vehicle__organisation=org, started_at__gte=week_start)
            .filter(q_trips)
            .values('started_at', 'ended_at')
        )

        driving_minutes = 0.0
        after_hours_count = 0
        for t in trips:
            local_start = timezone.localtime(t['started_at'])
            if local_start.hour < 6 or local_start.hour >= 20:
                after_hours_count += 1
            if t['ended_at']:
                driving_minutes += (t['ended_at'] - t['started_at']).total_seconds() / 60
            else:
                driving_minutes += (now - t['started_at']).total_seconds() / 60

        base = Alert.objects.filter(vehicle__organisation=org, occurred_at__gte=week_start)
        speeding_count = base.filter(kind=AlertKind.SPEEDING).filter(q_alerts).count()
        idle_count     = base.filter(kind=AlertKind.IDLE).filter(q_alerts).count()

        score = max(0, 100 - speeding_count * 5 - idle_count * 3 - after_hours_count * 8)
        if score >= 90:   grade = 'A'
        elif score >= 80: grade = 'B'
        elif score >= 70: grade = 'C'
        elif score >= 60: grade = 'D'
        else:             grade = 'F'

        rows.append({
            'driver': driver.full_name,
            'speeding_count': speeding_count,
            'idle_count': idle_count,
            'after_hours_count': after_hours_count,
            'score': score,
            'grade': grade,
            'driving_minutes': round(driving_minutes),
        })

    rows.sort(key=lambda r: r['score'], reverse=True)
    return render(request, 'compliance/scorecard.html', {'rows': rows})


@login_required
def hours_of_service(request):
    """
    7-day hours-of-service summary for every active Driver in the org.
    Uses the same dual-match strategy as driver_scorecard: driver_name field
    first, then default_vehicle fallback when Traccar omits the driver ID.
    """
    org = request.user.organisation
    now = timezone.now()
    week_start = now - timedelta(days=7)

    DAILY_LIMIT  = 660    # 11 h in minutes
    WEEKLY_LIMIT = 3600   # 60 h in minutes

    drivers = list(Driver.objects.filter(organisation=org, is_active=True).select_related('default_vehicle'))
    dates   = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]

    drivers_data = []
    for driver in drivers:
        q = Q(driver_name=driver.full_name)
        if driver.default_vehicle_id:
            q |= Q(vehicle_id=driver.default_vehicle_id, driver_name='')

        trips = list(
            TrackedTrip.objects
            .filter(vehicle__organisation=org, started_at__gte=week_start)
            .filter(q)
            .values('started_at', 'ended_at')
        )

        dmap = defaultdict(float)
        for t in trips:
            local_start = timezone.localtime(t['started_at'])
            if t['ended_at']:
                mins = (t['ended_at'] - t['started_at']).total_seconds() / 60
            else:
                mins = (now - t['started_at']).total_seconds() / 60
            dmap[local_start.date()] += mins

        week_total = sum(dmap.values())
        days = []
        for d in dates:
            mins = dmap.get(d, 0)
            pct  = mins / DAILY_LIMIT
            if pct >= 0.9:   day_status = 'danger'
            elif pct >= 0.8: day_status = 'warning'
            else:            day_status = 'ok'
            h, m = divmod(round(mins), 60)
            days.append({'date': d, 'minutes': round(mins), 'display': f"{h}:{m:02d}", 'status': day_status})

        week_pct = week_total / WEEKLY_LIMIT
        if week_pct >= 0.9:   week_status = 'danger'
        elif week_pct >= 0.8: week_status = 'warning'
        else:                  week_status = 'ok'

        wh, wm = divmod(round(week_total), 60)
        drivers_data.append({
            'driver': driver.full_name,
            'week_total': round(week_total),
            'week_display': f"{wh}:{wm:02d}",
            'week_status': week_status,
            'days': days,
        })

    drivers_data.sort(key=lambda r: r['driver'])
    return render(request, 'compliance/hours_of_service.html', {
        'drivers_data': drivers_data,
        'dates': dates,
    })


@login_required
def inspection_list(request):
    org = request.user.organisation
    qs = (
        InspectionLog.objects
        .filter(vehicle__organisation=org)
        .select_related('vehicle')
        .order_by('-submitted_at')
    )

    vehicle_filter = request.GET.get('vehicle', '')
    result_filter  = request.GET.get('result', '')
    date_filter    = request.GET.get('date', '')

    if vehicle_filter:
        qs = qs.filter(vehicle_id=vehicle_filter)
    if result_filter:
        qs = qs.filter(result=result_filter)
    if date_filter:
        d = parse_date(date_filter)
        if d:
            day_start = timezone.make_aware(datetime.combine(d, datetime.min.time()))
            day_end   = timezone.make_aware(datetime.combine(d, datetime.max.time()))
            qs = qs.filter(submitted_at__range=(day_start, day_end))

    page = Paginator(qs, 50).get_page(request.GET.get('page', 1))
    vehicles = Vehicle.objects.filter(organisation=org, is_active=True).order_by('registration')

    return render(request, 'compliance/inspection_list.html', {
        'page_obj': page,
        'vehicles': vehicles,
        'result_choices': InspectionLog.Result.choices,
        'vehicle_filter': vehicle_filter,
        'result_filter': result_filter,
        'date_filter': date_filter,
    })


@login_required
def inspection_create(request):
    org = request.user.organisation
    vehicles = Vehicle.objects.filter(organisation=org, is_active=True).order_by('registration')
    errors = []

    if request.method == 'POST':
        vehicle_id = request.POST.get('vehicle', '').strip()
        driver_name = request.POST.get('driver_name', '').strip()
        inspection_type = request.POST.get('inspection_type', '').strip()
        result = request.POST.get('result', '').strip()
        defects = request.POST.get('defects', '').strip()
        notes = request.POST.get('notes', '').strip()
        odometer_raw = request.POST.get('odometer_km', '').strip()

        checklist = {}
        for key, _ in CHECKLIST_ITEMS:
            checklist[key] = request.POST.get(f'check_{key}') == 'on'

        if not vehicle_id:
            errors.append('Vehicle is required.')
        if not any(checklist.values()):
            errors.append('At least one checklist item must be checked.')

        if not errors:
            try:
                vehicle = vehicles.get(pk=vehicle_id)
            except Vehicle.DoesNotExist:
                errors.append('Invalid vehicle.')

        if not errors:
            odometer_km = None
            if odometer_raw:
                try:
                    odometer_km = float(odometer_raw)
                except ValueError:
                    errors.append('Odometer must be a number.')

        if not errors:
            InspectionLog.objects.create(
                vehicle=vehicle,
                driver_name=driver_name,
                inspection_type=inspection_type,
                result=result,
                checklist=checklist,
                defects=defects,
                odometer_km=odometer_km,
                notes=notes,
            )
            return redirect('inspection-list')

    return render(request, 'compliance/inspection_form.html', {
        'vehicles': vehicles,
        'checklist_items': CHECKLIST_ITEMS,
        'inspection_type_choices': InspectionLog.InspectionType.choices,
        'result_choices': InspectionLog.Result.choices,
        'errors': errors,
        'post': request.POST if request.method == 'POST' else {},
    })


@login_required
def document_list(request):
    org = request.user.organisation
    qs = (
        VehicleDocument.objects
        .filter(vehicle__organisation=org)
        .select_related('vehicle')
        .order_by('-uploaded_at')
    )

    vehicle_filter = request.GET.get('vehicle', '')
    kind_filter    = request.GET.get('kind', '')

    if vehicle_filter:
        qs = qs.filter(vehicle_id=vehicle_filter)
    if kind_filter:
        qs = qs.filter(kind=kind_filter)

    page     = Paginator(qs, 50).get_page(request.GET.get('page', 1))
    vehicles = Vehicle.objects.filter(organisation=org, is_active=True).order_by('registration')

    return render(request, 'compliance/document_list.html', {
        'page_obj':      page,
        'vehicles':      vehicles,
        'kind_choices':  DocumentKind.choices,
        'vehicle_filter': vehicle_filter,
        'kind_filter':   kind_filter,
    })


@login_required
def document_upload(request):
    org      = request.user.organisation
    vehicles = Vehicle.objects.filter(organisation=org, is_active=True).order_by('registration')
    errors   = []

    if request.method == 'POST':
        vehicle_id  = request.POST.get('vehicle', '').strip()
        kind        = request.POST.get('kind', '').strip()
        label       = request.POST.get('label', '').strip()
        expiry_raw  = request.POST.get('expiry_date', '').strip()
        notes       = request.POST.get('notes', '').strip()
        file        = request.FILES.get('file')

        if not vehicle_id:
            errors.append('Vehicle is required.')
        if not kind:
            errors.append('Document type is required.')
        if not file:
            errors.append('File is required.')

        vehicle = None
        if not errors:
            try:
                vehicle = vehicles.get(pk=vehicle_id)
            except Vehicle.DoesNotExist:
                errors.append('Invalid vehicle.')

        expiry_date = None
        if not errors and expiry_raw:
            expiry_date = parse_date(expiry_raw)
            if not expiry_date:
                errors.append('Invalid expiry date.')

        if not errors:
            VehicleDocument.objects.create(
                vehicle=vehicle,
                kind=kind,
                label=label,
                file=file,
                expiry_date=expiry_date,
                notes=notes,
            )
            return redirect('document-list')

    return render(request, 'compliance/document_upload.html', {
        'vehicles':     vehicles,
        'kind_choices': DocumentKind.choices,
        'errors':       errors,
        'post':         request.POST if request.method == 'POST' else {},
    })


@login_required
def document_delete(request, doc_id):
    org = request.user.organisation
    doc = get_object_or_404(VehicleDocument, pk=doc_id, vehicle__organisation=org)
    if request.method == 'POST':
        doc.file.delete(save=False)
        doc.delete()
    return redirect('document-list')


@login_required
def inspection_detail(request, log_id):
    org = request.user.organisation
    log = get_object_or_404(InspectionLog, pk=log_id, vehicle__organisation=org)
    checklist_display = [
        (key, label, log.checklist.get(key, False))
        for key, label in CHECKLIST_ITEMS
    ]
    return render(request, 'compliance/inspection_detail.html', {
        'log': log,
        'checklist_display': checklist_display,
    })


# ─── Service schedules ────────────────────────────────────────────────────────

_SERVICE_WARNING_KM = 1500


@login_required
def service_list(request):
    org = request.user.organisation
    schedules = list(
        ServiceSchedule.objects
        .filter(vehicle__organisation=org)
        .select_related('vehicle')
    )

    # Latest odometer per vehicle: MAX(odometer_km) is safe because odometers
    # are monotonically increasing, so the max is also the most recent.
    from django.db.models import Max
    vehicle_ids = list({s.vehicle_id for s in schedules})
    odo_map = dict(
        InspectionLog.objects
        .filter(vehicle_id__in=vehicle_ids, odometer_km__isnull=False)
        .values('vehicle_id')
        .annotate(odo=Max('odometer_km'))
        .values_list('vehicle_id', 'odo')
    )

    rows = []
    for s in schedules:
        current_odo = odo_map.get(s.vehicle_id)
        next_due = s.next_due_km
        if next_due is None or current_odo is None:
            remaining = None
            status = 'unknown'
        else:
            remaining = next_due - current_odo
            if remaining < 0:
                status = 'overdue'
            elif remaining <= _SERVICE_WARNING_KM:
                status = 'warning'
            else:
                status = 'ok'
        rows.append({
            'schedule': s,
            'current_odo': current_odo,
            'remaining': remaining,
            'abs_remaining': abs(remaining) if remaining is not None else None,
            'status': status,
        })

    _order = {'overdue': 0, 'warning': 1, 'ok': 2, 'unknown': 3}
    rows.sort(key=lambda r: (
        _order[r['status']],
        r['remaining'] if r['remaining'] is not None else 999_999_999,
    ))

    overdue_count = sum(1 for r in rows if r['status'] == 'overdue')
    warning_count = sum(1 for r in rows if r['status'] == 'warning')

    return render(request, 'compliance/service_list.html', {
        'rows': rows,
        'overdue_count': overdue_count,
        'warning_count': warning_count,
    })


@login_required
def service_create(request):
    org = request.user.organisation
    vehicles = Vehicle.objects.filter(organisation=org, is_active=True).order_by('registration')
    errors = []
    post = {}

    if request.method == 'POST':
        post = request.POST
        vehicle_id  = post.get('vehicle', '').strip()
        name        = post.get('name', '').strip()
        interval_raw = post.get('interval_km', '').strip()
        last_km_raw  = post.get('last_service_km', '').strip()
        last_date_raw = post.get('last_service_date', '').strip()
        interval_days_raw = post.get('interval_days', '').strip()
        last_serviced_at_raw = post.get('last_serviced_at', '').strip()
        notes = post.get('notes', '').strip()

        if not vehicle_id:
            errors.append('Vehicle is required.')
        if not name:
            errors.append('Service name is required.')

        interval_km = None
        if not interval_raw:
            errors.append('Interval (km) is required.')
        else:
            try:
                interval_km = int(interval_raw)
                if interval_km <= 0:
                    errors.append('Interval must be a positive number.')
            except ValueError:
                errors.append('Interval must be a whole number.')

        vehicle = None
        if not errors:
            try:
                vehicle = vehicles.get(pk=vehicle_id)
            except Vehicle.DoesNotExist:
                errors.append('Invalid vehicle.')

        last_service_km = None
        if not errors and last_km_raw:
            try:
                last_service_km = float(last_km_raw)
            except ValueError:
                errors.append('Last service odometer must be a number.')

        last_service_date = None
        if not errors and last_date_raw:
            last_service_date = parse_date(last_date_raw)
            if not last_service_date:
                errors.append('Invalid last service date.')

        interval_days = None
        if interval_days_raw:
            try:
                interval_days = int(interval_days_raw)
                if interval_days <= 0:
                    errors.append('Time interval must be a positive number.')
            except ValueError:
                errors.append('Time interval must be a whole number.')

        last_serviced_at = None
        if last_serviced_at_raw:
            last_serviced_at = parse_date(last_serviced_at_raw)
            if not last_serviced_at:
                errors.append('Invalid last serviced date.')

        if not errors:
            ServiceSchedule.objects.create(
                vehicle=vehicle,
                name=name,
                interval_km=interval_km,
                last_service_km=last_service_km,
                last_service_date=last_service_date,
                interval_days=interval_days,
                last_serviced_at=last_serviced_at,
                notes=notes,
            )
            return redirect('service-list')

    return render(request, 'compliance/service_form.html', {
        'vehicles': vehicles,
        'errors': errors,
        'post': post,
        'title': 'Add Service Schedule',
        'submit_label': 'Add Schedule',
    })


@login_required
def service_edit(request, pk):
    org = request.user.organisation
    schedule = get_object_or_404(ServiceSchedule, pk=pk, vehicle__organisation=org)
    errors = []

    if request.method == 'POST':
        post = request.POST
        name         = post.get('name', '').strip()
        interval_raw = post.get('interval_km', '').strip()
        last_km_raw  = post.get('last_service_km', '').strip()
        last_date_raw = post.get('last_service_date', '').strip()
        interval_days_raw = post.get('interval_days', '').strip()
        last_serviced_at_raw = post.get('last_serviced_at', '').strip()
        notes = post.get('notes', '').strip()

        if not name:
            errors.append('Service name is required.')

        interval_km = None
        if not interval_raw:
            errors.append('Interval (km) is required.')
        else:
            try:
                interval_km = int(interval_raw)
                if interval_km <= 0:
                    errors.append('Interval must be a positive number.')
            except ValueError:
                errors.append('Interval must be a whole number.')

        last_service_km = None
        if last_km_raw:
            try:
                last_service_km = float(last_km_raw)
            except ValueError:
                errors.append('Last service odometer must be a number.')

        last_service_date = None
        if last_date_raw:
            last_service_date = parse_date(last_date_raw)
            if not last_service_date:
                errors.append('Invalid last service date.')

        interval_days = None
        if interval_days_raw:
            try:
                interval_days = int(interval_days_raw)
                if interval_days <= 0:
                    errors.append('Time interval must be a positive number.')
            except ValueError:
                errors.append('Time interval must be a whole number.')

        last_serviced_at = None
        if last_serviced_at_raw:
            last_serviced_at = parse_date(last_serviced_at_raw)
            if not last_serviced_at:
                errors.append('Invalid last serviced date.')

        if not errors:
            schedule.name = name
            schedule.interval_km = interval_km
            schedule.last_service_km = last_service_km
            schedule.last_service_date = last_service_date
            schedule.interval_days = interval_days
            schedule.last_serviced_at = last_serviced_at
            schedule.notes = notes
            schedule.save()
            return redirect('service-list')
    else:
        post = {
            'name': schedule.name,
            'interval_km': schedule.interval_km,
            'last_service_km': schedule.last_service_km if schedule.last_service_km is not None else '',
            'last_service_date': schedule.last_service_date or '',
            'interval_days': schedule.interval_days or '',
            'last_serviced_at': schedule.last_serviced_at or '',
            'notes': schedule.notes,
        }

    return render(request, 'compliance/service_form.html', {
        'schedule': schedule,
        'errors': errors,
        'post': post,
        'title': f'Edit — {schedule.name}',
        'submit_label': 'Save Changes',
    })


@login_required
def service_mark_done(request, pk):
    org = request.user.organisation
    schedule = get_object_or_404(ServiceSchedule, pk=pk, vehicle__organisation=org)
    errors = []

    if request.method == 'POST':
        odo_raw  = request.POST.get('odometer_km', '').strip()
        date_raw = request.POST.get('service_date', '').strip()

        odo = None
        if not odo_raw:
            errors.append('Odometer reading is required.')
        else:
            try:
                odo = float(odo_raw)
            except ValueError:
                errors.append('Odometer must be a number.')

        service_date = parse_date(date_raw) if date_raw else timezone.now().date()

        if not errors:
            schedule.last_service_km = odo
            schedule.last_service_date = service_date
            schedule.save()
            return redirect('service-list')

    # Pre-fill odometer from the latest inspection with a reading
    latest_log = (
        InspectionLog.objects
        .filter(vehicle=schedule.vehicle, odometer_km__isnull=False)
        .order_by('-submitted_at')
        .first()
    )
    current_odo = latest_log.odometer_km if latest_log else None

    return render(request, 'compliance/service_done_form.html', {
        'schedule': schedule,
        'current_odo': current_odo,
        'errors': errors,
        'today': timezone.now().date(),
        'post': request.POST if request.method == 'POST' else {},
    })


@login_required
def service_delete(request, pk):
    org = request.user.organisation
    schedule = get_object_or_404(ServiceSchedule, pk=pk, vehicle__organisation=org)
    if request.method == 'POST':
        schedule.delete()
    return redirect('service-list')
