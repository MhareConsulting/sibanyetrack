import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import CreateView, ListView, UpdateView
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .forms import GeofenceForm
from .models import Geofence, GeofenceEvent
from mytrack.tenancy.models import Depot
from mytrack.vehicles.models import Vehicle


class GeofenceListView(LoginRequiredMixin, ListView):
    template_name = "geofences/list.html"
    context_object_name = "geofences"

    def get_queryset(self):
        cutoff_24h = timezone.now() - timezone.timedelta(hours=24)
        return Geofence.objects.filter(
            organisation=self.request.user.organisation
        ).annotate(
            total_events=Count("events", distinct=True),
            events_24h=Count("events", filter=Q(events__occurred_at__gte=cutoff_24h), distinct=True),
            last_event_at=Max("events__occurred_at"),
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        organisation = self.request.user.organisation
        cutoff_24h = timezone.now() - timezone.timedelta(hours=24)

        vehicles = Vehicle.objects.filter(organisation=organisation)
        depots = Depot.objects.filter(organisation=organisation, is_active=True)

        ctx["recent_events"] = (
            GeofenceEvent.objects
            .filter(geofence__organisation=organisation)
            .select_related("geofence", "vehicle", "vehicle__home_depot")
            .order_by("-occurred_at")[:50]
        )
        ctx["fleet_stats"] = {
            "total_vehicles": vehicles.count(),
            "active_vehicles": vehicles.filter(is_active=True).count(),
            "active_depots": depots.count(),
            "crossings_24h": GeofenceEvent.objects.filter(
                geofence__organisation=organisation,
                occurred_at__gte=cutoff_24h,
            ).count(),
            "active_fences": Geofence.objects.filter(
                organisation=organisation,
                is_active=True,
            ).count(),
        }
        ctx["depot_breakdown"] = depots.annotate(
            vehicle_count=Count("vehicles", distinct=True),
            active_vehicle_count=Count("vehicles", filter=Q(vehicles__is_active=True), distinct=True),
        ).order_by("-active_vehicle_count", "name")[:8]
        return ctx


_DAYS_OF_WEEK = [
    ("0", "Mon"), ("1", "Tue"), ("2", "Wed"), ("3", "Thu"),
    ("4", "Fri"), ("5", "Sat"), ("6", "Sun"),
]


def _geofence_hours_context(active_days_str):
    return {
        "days_of_week": _DAYS_OF_WEEK,
        "active_days_list": [d.strip() for d in (active_days_str or "0,1,2,3,4").split(",")],
    }


class GeofenceCreateView(LoginRequiredMixin, CreateView):
    template_name = "geofences/map.html"
    form_class = GeofenceForm
    success_url = reverse_lazy("geofence-list")

    def post(self, request, *args, **kwargs):
        # Build active_days from checkboxes before form processing
        days = ",".join(request.POST.getlist("active_days_cb") or ["0","1","2","3","4"])
        data = request.POST.copy()
        data["active_days"] = days
        request._post = data
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.organisation = self.request.user.organisation
        messages.success(self.request, f"Geofence '{form.instance.name}' created.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action"] = "Add"
        ctx["existing_polygon"] = "null"
        ctx.update(_geofence_hours_context("0,1,2,3,4"))
        return ctx


class GeofenceUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "geofences/map.html"
    form_class = GeofenceForm
    success_url = reverse_lazy("geofence-list")

    def get_queryset(self):
        return Geofence.objects.filter(organisation=self.request.user.organisation)

    def post(self, request, *args, **kwargs):
        days = ",".join(request.POST.getlist("active_days_cb") or ["0","1","2","3","4"])
        data = request.POST.copy()
        data["active_days"] = days
        request._post = data
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, f"Geofence '{form.instance.name}' updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action"] = "Edit"
        ctx["existing_polygon"] = json.dumps(self.object.polygon)
        ctx.update(_geofence_hours_context(self.object.active_days))
        return ctx


@login_required
@require_POST
def geofence_delete(request, pk):
    fence = get_object_or_404(Geofence, pk=pk, organisation=request.user.organisation)
    name = fence.name
    fence.delete()
    messages.success(request, f"Geofence '{name}' deleted.")
    return redirect("geofence-list")


@login_required
def geofences_geojson(request):
    """GeoJSON FeatureCollection of all active polygon geofences."""
    fences = Geofence.objects.filter(
        organisation=request.user.organisation, is_active=True
    ).values("id", "name", "polygon")
    features = [
        {
            "type": "Feature",
            "properties": {"id": f["id"], "name": f["name"]},
            "geometry": {"type": "Polygon", "coordinates": [f["polygon"]]},
        }
        for f in fences
        if f["polygon"] and len(f["polygon"]) >= 3
    ]
    return JsonResponse({"type": "FeatureCollection", "features": features})


@login_required
def parse_geofence_file(request):
    """Parse a .kml or .geojson file and return the polygon coordinates."""
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"error": "No file uploaded."}, status=400)

    name = (f.name or "").lower()
    content = f.read().decode("utf-8", errors="replace")

    coords = None

    if name.endswith(".geojson") or name.endswith(".json"):
        try:
            data = json.loads(content)
            coords = _extract_geojson_coords(data)
        except (ValueError, KeyError):
            return JsonResponse({"error": "Invalid GeoJSON."}, status=400)

    elif name.endswith(".kml"):
        coords = _extract_kml_coords(content)

    else:
        return JsonResponse({"error": "Unsupported file type. Upload .kml or .geojson."}, status=400)

    if not coords or len(coords) < 3:
        return JsonResponse({"error": "Could not extract a valid polygon (need ≥ 3 points)."}, status=400)

    # Strip closing point if it equals the first
    if len(coords) > 3 and coords[0] == coords[-1]:
        coords = coords[:-1]

    return JsonResponse({"coordinates": coords})


def _extract_geojson_coords(data):
    """Return first polygon ring from GeoJSON (Feature, FeatureCollection, or Geometry)."""
    geom = None
    if data.get("type") == "FeatureCollection":
        for feat in data.get("features", []):
            geom = feat.get("geometry")
            if geom and geom.get("type") == "Polygon":
                break
    elif data.get("type") == "Feature":
        geom = data.get("geometry")
    else:
        geom = data  # bare geometry

    if not geom:
        return None
    if geom.get("type") == "Polygon":
        ring = geom["coordinates"][0]
        return [[c[0], c[1]] for c in ring]
    if geom.get("type") == "MultiPolygon":
        ring = geom["coordinates"][0][0]
        return [[c[0], c[1]] for c in ring]
    return None


def _extract_kml_coords(content):
    """Extract first Polygon's outer ring from KML text."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None

    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    # Try with and without namespace
    for tag in (".//{http://www.opengis.net/kml/2.2}coordinates",
                ".//coordinates"):
        elem = root.find(tag)
        if elem is not None and elem.text:
            coords = []
            for token in elem.text.strip().split():
                parts = token.split(",")
                if len(parts) >= 2:
                    try:
                        coords.append([float(parts[0]), float(parts[1])])
                    except ValueError:
                        pass
            if coords:
                return coords
    return None
