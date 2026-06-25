from django.contrib import admin
from .models import Geofence, GeofenceEvent, VehicleGeofenceState


@admin.register(Geofence)
class GeofenceAdmin(admin.ModelAdmin):
    list_display = ("name", "organisation", "is_active", "created_at")
    list_filter = ("organisation", "is_active")


@admin.register(GeofenceEvent)
class GeofenceEventAdmin(admin.ModelAdmin):
    list_display = ("geofence", "vehicle", "kind", "driver_name", "occurred_at")
    list_filter = ("kind", "geofence")
    ordering = ("-occurred_at",)


admin.site.register(VehicleGeofenceState)
