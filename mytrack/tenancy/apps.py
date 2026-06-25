from django.apps import AppConfig


class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mytrack.tenancy"

    def ready(self):
        import mytrack.tenancy.signals  # noqa: F401
