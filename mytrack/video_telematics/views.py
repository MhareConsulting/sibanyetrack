import json
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Case, IntegerField, Value, When
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from mytrack.tenancy.mixins import SESSION_KEY
from mytrack.tenancy.models import Depot, Role
from mytrack.video_telematics.models import ClipRequest, VideoAsset, VideoChannel, VideoTrigger
from mytrack.video_telematics.storage import playback_redirect



def _depot_context(request):
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
    return active_depot, ctx


@login_required
def video_list(request):
    org = request.user.organisation
    active_depot, depot_ctx = _depot_context(request)

    qs = (
        VideoAsset.objects.filter(organisation=org)
        .select_related("vehicle", "alert", "tracked_trip")
        .order_by("-occurred_at")
    )
    if active_depot:
        qs = qs.filter(vehicle__home_depot=active_depot)

    vehicle_filter = request.GET.get("vehicle", "")
    trigger_filter = request.GET.get("trigger", "")
    if vehicle_filter:
        qs = qs.filter(vehicle_id=vehicle_filter)
    trigger_values = tuple(v for v, _ in VideoTrigger.choices)
    if trigger_filter and trigger_filter in trigger_values:
        qs = qs.filter(trigger_type=trigger_filter)

    page = Paginator(qs, 30).get_page(request.GET.get("page", 1))

    from mytrack.vehicles.models import Vehicle

    vehicles = Vehicle.objects.filter(organisation=org, is_active=True)
    if active_depot:
        vehicles = vehicles.filter(home_depot=active_depot)
    vehicles = vehicles.order_by("registration")

    return render(
        request,
        "video_telematics/video_list.html",
        {
            "page_obj": page,
            "vehicles": vehicles,
            "vehicle_filter": vehicle_filter,
            "trigger_filter": trigger_filter,
            "trigger_choices": VideoTrigger.choices,
            **depot_ctx,
        },
    )


@login_required
def video_detail(request, pk):
    org = request.user.organisation
    asset = get_object_or_404(
        VideoAsset.objects.select_related("vehicle", "alert", "tracked_trip", "channel"),
        pk=pk,
        organisation=org,
    )
    play_url = None
    if asset.playback_url or asset.storage_key:
        play_url = reverse("video-play", args=[asset.pk])

    return render(
        request,
        "video_telematics/video_detail.html",
        {"asset": asset, "play_url": play_url},
    )


@login_required
def video_play(request, pk):
    org = request.user.organisation
    asset = get_object_or_404(VideoAsset, pk=pk, organisation=org)
    response = playback_redirect(asset)
    if isinstance(response, HttpResponseBadRequest):
        return response
    return response


@login_required
def channel_live(request, pk):
    org = request.user.organisation
    channel = get_object_or_404(
        VideoChannel.objects.select_related("vehicle"),
        pk=pk,
        vehicle__organisation=org,
        is_active=True,
    )
    return render(request, "video_telematics/channel_live.html", {"channel": channel})


def _channel_status(channel, stale_cutoff):
    if channel.camera_last_seen is None:
        return "never"
    if channel.camera_last_seen < stale_cutoff:
        return "stale"
    return "ok"


@login_required
def camera_health(request):
    org = request.user.organisation
    active_depot, depot_ctx = _depot_context(request)

    stale_hours = int(getattr(settings, "VIDEO_CAMERA_STALE_HOURS", 24))
    stale_cutoff = timezone.now() - timedelta(hours=stale_hours)

    qs = (
        VideoChannel.objects.filter(vehicle__organisation=org, is_active=True)
        .select_related("vehicle")
        .order_by("vehicle__registration", "name")
    )
    if active_depot:
        qs = qs.filter(vehicle__home_depot=active_depot)

    rows = [{"channel": ch, "status": _channel_status(ch, stale_cutoff)} for ch in qs]

    return render(
        request,
        "video_telematics/camera_health.html",
        {"rows": rows, "stale_hours": stale_hours, **depot_ctx},
    )


@login_required
def surveillance_room(request):
    from mytrack.tracking.models import Alert

    org = request.user.organisation
    active_depot, depot_ctx = _depot_context(request)

    stale_hours = int(getattr(settings, "VIDEO_CAMERA_STALE_HOURS", 24))
    stale_cutoff = timezone.now() - timedelta(hours=stale_hours)

    channels_qs = (
        VideoChannel.objects.filter(vehicle__organisation=org, is_active=True)
        .select_related("vehicle")
        .order_by("vehicle__registration", "name")
    )
    if active_depot:
        channels_qs = channels_qs.filter(vehicle__home_depot=active_depot)

    channels_dict = {}
    vehicle_channels = {}
    rows = []
    for ch in channels_qs:
        status = _channel_status(ch, stale_cutoff)
        rows.append({"channel": ch, "status": status, "alert_count": 0})
        channels_dict[str(ch.pk)] = {
            "vehicle_id": ch.vehicle_id,
            "vehicle_reg": ch.vehicle.registration,
            "channel_name": ch.name,
            "stream_url": ch.stream_url,
            "status": status,
        }
        vk = str(ch.vehicle_id)
        vehicle_channels.setdefault(vk, []).append(ch.pk)

    recent_alerts = (
        Alert.objects.filter(vehicle__organisation=org, resolved_at__isnull=True)
        .select_related("vehicle")
        .annotate(
            sev_order=Case(
                When(severity="critical", then=Value(0)),
                When(severity="warning", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("sev_order", "-occurred_at")[:20]
    )

    alert_vehicle_ids = {a.vehicle_id for a in recent_alerts}
    for row in rows:
        if row["channel"].vehicle_id in alert_vehicle_ids:
            row["alert_count"] = 1

    initial_alerts_json = json.dumps([
        {
            "id": a.id,
            "kind": a.kind,
            "kind_label": a.get_kind_display(),
            "severity": a.severity,
            "vehicle_id": a.vehicle_id,
            "vehicle_reg": a.vehicle.registration,
            "driver_name": a.driver_name,
            "value": round(float(a.value), 1),
            "occurred_at": a.occurred_at.isoformat(),
        }
        for a in recent_alerts
    ])

    stats = {
        "total": len(rows),
        "ok": sum(1 for r in rows if r["status"] == "ok"),
        "stale": sum(1 for r in rows if r["status"] == "stale"),
        "never": sum(1 for r in rows if r["status"] == "never"),
    }

    return render(
        request,
        "video_telematics/surveillance_room.html",
        {
            "rows": rows,
            "stats": stats,
            "recent_alerts": recent_alerts,
            "stale_hours": stale_hours,
            "channels_json": json.dumps(channels_dict),
            "vehicle_channels_json": json.dumps(vehicle_channels),
            "initial_alerts_json": initial_alerts_json,
            **depot_ctx,
        },
    )


@login_required
@require_GET
def surveillance_alert_stream(request):
    """SSE: pushes new alerts + telematics snapshot for channelled vehicles every 8 s."""
    from mytrack.tracking.models import Alert
    from mytrack.vehicles.models import Vehicle

    org = request.user.organisation
    active_depot, _ = _depot_context(request)

    def event_stream():
        channel_qs = VideoChannel.objects.filter(vehicle__organisation=org, is_active=True)
        if active_depot:
            channel_qs = channel_qs.filter(vehicle__home_depot=active_depot)
        vehicle_ids_with_cams = set(channel_qs.values_list("vehicle_id", flat=True))

        last_alert_id = (
            Alert.objects.filter(vehicle__organisation=org)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        ) or 0

        while True:
            time.sleep(8)

            new_qs = (
                Alert.objects.filter(vehicle__organisation=org, id__gt=last_alert_id)
                .select_related("vehicle")
                .order_by("id")
            )
            new_alerts = []
            for a in new_qs:
                new_alerts.append({
                    "id": a.id,
                    "kind": a.kind,
                    "kind_label": a.get_kind_display(),
                    "severity": a.severity,
                    "vehicle_id": a.vehicle_id,
                    "vehicle_reg": a.vehicle.registration,
                    "driver_name": a.driver_name,
                    "value": round(float(a.value), 1),
                    "occurred_at": a.occurred_at.isoformat(),
                })
                last_alert_id = a.id

            vehicles = Vehicle.objects.filter(
                organisation=org, id__in=vehicle_ids_with_cams,
            ).prefetch_related("state")
            states = []
            for v in vehicles:
                s = getattr(v, "state", None)
                states.append({
                    "vehicle_id": v.id,
                    "reg": v.registration,
                    "speed_kmh": (s.speed_kmh if s else None),
                    "lat": (s.lat if s else None),
                    "lon": (s.lon if s else None),
                    "heading": (s.heading if s else None),
                    "address": ((s.last_address or "") if s else ""),
                    "driver": ((s.driver_name or "") if s else ""),
                    "last_seen": (s.last_seen.isoformat() if (s and s.last_seen) else None),
                })

            payload = json.dumps({"alerts": new_alerts, "states": states})
            yield f"event: surveillance\ndata: {payload}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def surveillance_save_clip(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    org = request.user.organisation
    channel_id = request.POST.get("channel_id")
    alert_id = request.POST.get("alert_id")

    channel = get_object_or_404(
        VideoChannel, pk=channel_id, vehicle__organisation=org, is_active=True
    )
    alert_obj = None
    if alert_id:
        from mytrack.tracking.models import Alert
        try:
            alert_obj = Alert.objects.get(pk=alert_id, vehicle__organisation=org)
        except Alert.DoesNotExist:
            pass

    clip_req = ClipRequest.objects.create(
        organisation=org,
        vehicle=channel.vehicle,
        channel=channel,
        alert=alert_obj,
    )
    return JsonResponse({"ok": True, "clip_request_id": clip_req.id})
