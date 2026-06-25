from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Device, Vehicle

DEVICE_FAMILIES = [
    ("teltonika_fmb", "Teltonika FMB series (FMB920, FMB140, FMB640, FMT100)"),
    ("teltonika_fmc", "Teltonika FMC series (FMC125, FMC234)"),
    ("queclink_gl",   "Queclink GL series (GL200, GL300)"),
    ("queclink_gv",   "Queclink GV series (GV300, GV55)"),
    ("streamax",      "Streamax AD Plus 2.0"),
    ("other",         "Other / Unknown"),
]

# Map family key → Traccar protocol port (Streamax uses HTTP alarm push, not Traccar)
FAMILY_PORT = {
    "teltonika_fmb": 5027,
    "teltonika_fmc": 5027,
    "queclink_gl":   5023,
    "queclink_gv":   5093,
    "streamax":      8001,
    "other":         5055,  # OsmAnd HTTP fallback
}


@login_required
def device_list(request):
    org = request.user.organisation
    qs = Device.objects.filter(organisation=org).select_related("vehicle")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(imei__icontains=q) | Device.objects.filter(
            organisation=org, vehicle__registration__icontains=q
        ).select_related("vehicle")
        qs = qs.distinct()

    return render(request, "vehicles/device_list.html", {"devices": qs, "q": q, "families": DEVICE_FAMILIES})


@login_required
def device_detail(request, pk):
    org = request.user.organisation
    device = get_object_or_404(Device, pk=pk, organisation=org)

    if request.method == "POST":
        device.model_name = request.POST.get("model_name", "").strip()
        device.phone_number = request.POST.get("phone_number", "").strip()
        vehicle_id = request.POST.get("vehicle_id", "").strip()
        if vehicle_id:
            device.vehicle = get_object_or_404(Vehicle, pk=vehicle_id, organisation=org)
        else:
            device.vehicle = None
        device.save(update_fields=["model_name", "phone_number", "vehicle"])
        return redirect("device-list")

    vehicles = Vehicle.objects.filter(organisation=org, is_active=True).order_by("registration")

    # Ping activity stats (last 24h via linked vehicle)
    ping_count_24h = 0
    if device.vehicle_id:
        from mytrack.tracking.models import GPSPing
        cutoff = timezone.now() - timezone.timedelta(hours=24)
        ping_count_24h = GPSPing.objects.filter(
            vehicle=device.vehicle, received_at__gte=cutoff
        ).count()

    traccar_host = getattr(settings, "TRACCAR_PUBLIC_HOST", "your-server-ip")
    family = _family_for_model(device.model_name)
    port = FAMILY_PORT.get(family, 5055)

    # Pre-build SMS strings so the template doesn't need complex filter chaining
    sms_commands = _sms_commands(family, traccar_host, port)

    # Streamax alarm-push settings shown in device setup card
    streamax_config_rows = []
    if family == "streamax":
        import re
        base_url = getattr(settings, "STREAMAX_PUSH_BASE_URL", "").rstrip("/")
        push_url = f"{base_url}/api/video/streamax/event/" if base_url else ""
        token = getattr(settings, "STREAMAX_WEBHOOK_TOKEN", "")
        host_match = re.match(r"https?://([^:/]+)", base_url) if base_url else None
        host = host_match.group(1) if host_match else ""
        streamax_config_rows = [
            {"label": "Server / Host",          "value": host or "(configure STREAMAX_PUSH_BASE_URL)"},
            {"label": "Port",                    "value": "8001"},
            {"label": "Path / URL",              "value": "/api/video/streamax/event/"},
            {"label": "Protocol",                "value": "HTTP POST"},
            {"label": "Data Format",             "value": "JSON"},
            {"label": "Push Password / Token",   "value": token or "(configure STREAMAX_WEBHOOK_TOKEN)"},
            {"label": "Full Push URL",           "value": push_url or "(configure STREAMAX_PUSH_BASE_URL)"},
        ]

    return render(request, "vehicles/device_detail.html", {
        "device": device,
        "vehicles": vehicles,
        "ping_count_24h": ping_count_24h,
        "traccar_host": traccar_host,
        "device_family": family,
        "device_port": port,
        "sms_commands": sms_commands,
        "streamax_config_rows": streamax_config_rows,
        "families": DEVICE_FAMILIES,
    })


def _sms_commands(family, host, port):
    """Return list of (label, sms_text) tuples for device_detail template."""
    if family in ("teltonika_fmb", "teltonika_fmc"):
        return [
            ("Set APN", "setparam 2001:[YOUR_APN]"),
            ("Set server (primary)", f"setparam 2004:{host} 2005:{port} 2006:0"),
            ("Verify server", "getparam 2004"),
            ("Restart tracker", "setparam 10001:1"),
        ]
    if family in ("queclink_gl", "queclink_gv"):
        return [
            ("Configure server + APN", f"AT+GTSRI=queclink,[YOUR_APN],,,{host},{port},0,0,0,0,,FFFF$"),
            ("Verify configuration", "AT+GTSRI=queclink,,,,,,,,,,,,FFFF$"),
        ]
    return []


def _family_for_model(model_name):
    """Guess device family from free-text model name."""
    m = (model_name or "").lower()
    if "streamax" in m or "ad plus" in m or "adplus" in m:
        return "streamax"
    if "fmc" in m:
        return "teltonika_fmc"
    if "fm" in m or "teltonika" in m or "fmt" in m:
        return "teltonika_fmb"
    if "gl" in m and "queclink" not in m:
        return "queclink_gl"
    if "gv" in m:
        return "queclink_gv"
    if "queclink" in m or "at+gt" in m:
        return "queclink_gl"
    return "other"


@login_required
def device_add(request):
    org = request.user.organisation
    vehicles = Vehicle.objects.filter(organisation=org, is_active=True).order_by("registration")

    error = None
    if request.method == "POST":
        imei = request.POST.get("imei", "").strip()
        model_name = request.POST.get("model_name", "").strip()
        phone_number = request.POST.get("phone_number", "").strip()
        vehicle_id = request.POST.get("vehicle_id", "").strip()

        if not imei:
            error = "IMEI is required."
        elif not imei.isdigit() or not (14 <= len(imei) <= 17):
            error = "IMEI must be 14–17 digits."
        elif Device.objects.filter(imei=imei).exists():
            error = f"Device with IMEI {imei} is already registered."

        if not org:
            error = "Your account is not linked to an organisation. Contact your administrator."

        if not error:
            vehicle = None
            if vehicle_id:
                vehicle = get_object_or_404(Vehicle, pk=vehicle_id, organisation=org)
            device = Device.objects.create(
                organisation=org,
                imei=imei,
                model_name=model_name,
                phone_number=phone_number,
                vehicle=vehicle,
            )
            return redirect("device-detail", pk=device.pk)

    traccar_host = getattr(settings, "TRACCAR_PUBLIC_HOST", "your-server-ip")
    streamax_base = getattr(settings, "STREAMAX_PUSH_BASE_URL", "").rstrip("/")
    streamax_push_url = f"{streamax_base}/api/video/streamax/event/" if streamax_base else ""
    streamax_token = getattr(settings, "STREAMAX_WEBHOOK_TOKEN", "")
    return render(request, "vehicles/device_add.html", {
        "vehicles": vehicles,
        "families": DEVICE_FAMILIES,
        "traccar_host": traccar_host,
        "streamax_push_url": streamax_push_url,
        "streamax_token": streamax_token,
        "error": error,
        "post": request.POST,
    })
