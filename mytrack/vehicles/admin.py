from django.contrib import admin

from .models import Vehicle, VehicleDepotAssignment, VehicleState


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("registration", "label", "organisation", "home_depot", "is_active")
    list_filter = ("organisation", "home_depot", "is_active")
    search_fields = ("registration", "label")


@admin.register(VehicleDepotAssignment)
class VehicleDepotAssignmentAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "depot", "kind", "start_date", "end_date")
    list_filter = ("kind", "depot")
    raw_id_fields = ("vehicle",)


admin.site.register(VehicleState)
