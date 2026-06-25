from django.contrib import admin
from django.utils.html import format_html

from .models import GPSPing, TrackedTrip, Alert, DeliveryShare, RoadSpeedCache, SyncOutbox


@admin.register(SyncOutbox)
class SyncOutboxAdmin(admin.ModelAdmin):
    list_display = ["destination", "status_badge", "attempts", "last_attempted_at", "created_at", "error_snippet"]
    list_filter = ["destination", "succeeded_at"]
    ordering = ["-created_at"]
    readonly_fields = ["destination", "payload", "attempts", "last_attempted_at", "succeeded_at", "error", "created_at"]

    def error_snippet(self, obj):
        return (obj.error[:80] + "…") if len(obj.error) > 80 else obj.error
    error_snippet.short_description = "Error"

    def status_badge(self, obj):
        if obj.succeeded_at:
            return format_html('<span style="color:#16a34a;font-weight:600">✓ sent</span>')
        if obj.attempts >= 3:
            return format_html('<span style="color:#dc2626;font-weight:600">✗ dead</span>')
        return format_html('<span style="color:#d97706;font-weight:600">⏳ pending</span>')
    status_badge.short_description = "Status"


@admin.register(RoadSpeedCache)
class RoadSpeedCacheAdmin(admin.ModelAdmin):
    list_display = ["cell_key", "limit_kmh", "osm_way_id", "updated_at"]
    ordering = ["-updated_at"]


@admin.register(GPSPing)
class GPSPingAdmin(admin.ModelAdmin):
    list_display = [
        "vehicle",
        "lat",
        "lon",
        "road_speed_limit_kmh",
        "road_speed_source",
        "driver_name",
        "myroutes_trip_id",
        "received_at",
    ]
    list_filter = ["vehicle__organisation"]
    ordering = ["-received_at"]

@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["vehicle", "kind", "severity", "value", "threshold", "occurred_at", "resolved_at", "driver_name"]
    list_filter  = ["kind", "severity", "resolved_at"]
    ordering     = ["-occurred_at"]


@admin.register(DeliveryShare)
class DeliveryShareAdmin(admin.ModelAdmin):
    list_display = ["vehicle", "customer_email", "customer_name", "note", "is_active", "expires_at", "tracking_link"]
    list_filter = ["vehicle__organisation"]
    readonly_fields = ["token", "created_at", "tracking_link"]
    actions = ["send_tracking_link"]

    def tracking_link(self, obj):
        url = obj.get_public_url()
        return format_html('<a href="{}" target="_blank">Open</a>', url)
    tracking_link.short_description = "Link"

    @admin.action(description="Send tracking link to customer")
    def send_tracking_link(self, request, queryset):
        from mytrack.notifications.emails import send_delivery_link
        for share in queryset:
            if share.customer_email:
                send_delivery_link(share)
        self.message_user(request, f"Tracking link sent to {queryset.count()} customer(s).")
