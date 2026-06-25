from django.apps import AppConfig


class TrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mytrack.tracking"

    def ready(self):
        import mytrack.tracking.signals  # noqa: F401
