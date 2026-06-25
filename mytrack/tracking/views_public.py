import math

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from mytrack.tracking.models import DeliveryShare, GPSPing


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def delivery_demo(request):
    return render(request, "tracking/delivery_demo.html")


def delivery_track(request, token):
    share = get_object_or_404(DeliveryShare, token=token)
    if share.status == "expired":
        return render(request, "tracking/delivery_expired.html")
    return render(request, "tracking/delivery_track.html", {"share": share})


@never_cache
def delivery_location_api(request, token):
    share = get_object_or_404(DeliveryShare, token=token)

    if share.status == "delivered":
        return JsonResponse({
            "status": "delivered",
            "completed_at": timezone.localtime(share.completed_at).isoformat(),
            "trail": [],
        })

    if share.status == "expired":
        return JsonResponse({"error": "expired"}, status=410)

    ping = GPSPing.objects.filter(vehicle=share.vehicle).order_by("-received_at").first()
    if not ping:
        return JsonResponse({"error": "no_location"}, status=404)

    trail_rows = (
        GPSPing.objects.filter(vehicle=share.vehicle, received_at__gte=share.created_at)
        .exclude(lat__isnull=True)
        .exclude(lon__isnull=True)
        .order_by("device_timestamp", "received_at")
        .values("lat", "lon", "speed_kmh", "heading", "device_timestamp", "received_at")[:800]
    )
    trail = []
    for row in trail_rows:
        ts = row["device_timestamp"] or row["received_at"]
        trail.append(
            {
                "lat": row["lat"],
                "lon": row["lon"],
                "speed_kmh": row["speed_kmh"],
                "heading": row["heading"],
                "ts": ts.isoformat() if ts else None,
            }
        )

    distance_km = None
    eta_minutes = None
    if share.destination_lat and share.destination_lon:
        distance_km = round(_haversine_km(ping.lat, ping.lon, share.destination_lat, share.destination_lon), 2)
        speed = ping.speed_kmh if (ping.speed_kmh and ping.speed_kmh > 5) else 50.0
        eta_minutes = round((distance_km / speed) * 60)

    destination = None
    if share.destination_lat and share.destination_lon:
        destination = {
            "lat": share.destination_lat,
            "lon": share.destination_lon,
            "address": share.destination_address,
        }

    stops_ahead = None
    if share.stop_number and share.total_stops:
        stops_ahead = share.stop_number - 1

    return JsonResponse({
        "status": "active",
        "lat": ping.lat,
        "lon": ping.lon,
        "speed_kmh": ping.speed_kmh,
        "updated_at": timezone.localtime(ping.received_at).isoformat(),
        "vehicle": str(share.vehicle),
        "distance_km": distance_km,
        "eta_minutes": eta_minutes,
        "destination": destination,
        "stop_number": share.stop_number,
        "total_stops": share.total_stops,
        "stops_ahead": stops_ahead,
        "trail": trail,
    })
