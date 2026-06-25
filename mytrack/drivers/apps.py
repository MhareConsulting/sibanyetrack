from django.apps import AppConfig


class DriversConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mytrack.drivers"

    def ready(self):
        import mytrack.drivers.signals  # noqa: F401
