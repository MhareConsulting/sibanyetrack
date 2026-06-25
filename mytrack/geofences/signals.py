from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="geofences.GeofenceEvent")
def on_geofence_event(sender, instance, created, **kwargs):
    if not created:
        return
    from mytrack.notifications.emails import send_geofence_alert
    send_geofence_alert(instance)
    import threading
    from mytrack.notifications.whatsapp import notify_driver
    detail = f"{instance.get_kind_display()} {instance.geofence.name}"
    threading.Thread(
        target=notify_driver,
        args=(instance.driver_name, instance.vehicle.organisation, "Geofence Violation", instance.vehicle.registration, detail),
        daemon=True,
    ).start()
