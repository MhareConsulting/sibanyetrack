from django.urls import path

from mytrack.video_telematics import views

urlpatterns = [
    path("", views.video_list, name="video-list"),
    path("camera-health/", views.camera_health, name="video-camera-health"),
    path("surveillance-room/", views.surveillance_room, name="video-surveillance-room"),
    path("surveillance-room/stream/", views.surveillance_alert_stream, name="surveillance-stream"),
    path("surveillance-room/save-clip/", views.surveillance_save_clip, name="surveillance-save-clip"),
    path("<int:pk>/", views.video_detail, name="video-detail"),
    path("<int:pk>/play/", views.video_play, name="video-play"),
    path("channels/<int:pk>/live/", views.channel_live, name="channel-live"),
]
