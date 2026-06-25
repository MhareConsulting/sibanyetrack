from django.contrib import admin

from .models import Driver


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ["full_name", "licence_code", "licence_expiry", "pdp_expiry", "is_active"]
    list_filter = ["organisation", "licence_code", "is_active"]
    search_fields = ["full_name", "id_number", "phone_e164"]
