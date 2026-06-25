from django.apps import AppConfig


class VehiclesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mytrack.vehicles"

    def ready(self):
        import mytrack.vehicles.signals  # noqa: F401
