from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mytrack.compliance"
    label = "mytrack_compliance"

    def ready(self):
        import mytrack.compliance.signals  # noqa: F401
