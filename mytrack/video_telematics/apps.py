from django.apps import AppConfig


class VideoTelematicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mytrack.video_telematics"
    verbose_name = "Video telematics"

    def ready(self):
        import mytrack.video_telematics.signals  # noqa: F401
