from django.contrib import admin

from mytrack.video_telematics.models import VideoAsset, VideoChannel, VideoUploadIntent


@admin.register(VideoChannel)
class VideoChannelAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "name", "source", "external_channel_id", "stream_url", "is_active")
    list_filter = ("source", "is_active")
    search_fields = ("vehicle__registration", "name")
    fields = ("vehicle", "name", "source", "external_channel_id", "stream_url", "is_active")


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "occurred_at", "trigger_type", "ingest_source", "created_at")
    list_filter = ("trigger_type", "ingest_source")
    search_fields = ("vehicle__registration", "external_id", "storage_key")
    raw_id_fields = ("vehicle", "organisation", "channel", "alert", "tracked_trip")


@admin.register(VideoUploadIntent)
class VideoUploadIntentAdmin(admin.ModelAdmin):
    list_display = ("id", "vehicle", "organisation", "expires_at", "uploaded_at")
    list_filter = ("uploaded_at",)
