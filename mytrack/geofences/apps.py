from django.apps import AppConfig


class GeofencesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mytrack.geofences'

    def ready(self):
        import mytrack.geofences.signals  # noqa: F401
