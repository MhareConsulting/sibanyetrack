from django.db.models.signals import post_save
from django.dispatch import receiver

# Alert kinds that trigger a proactive clip request from the camera vendor
_CLIP_REQUEST_KINDS = frozenset([
    "speeding", "harsh_braking", "harsh_accel",
    "lane_departure", "fatigue", "phone_use", "seatbelt", "camera_event",
])

# Alert kinds that send a WhatsApp notification to the driver
_WHATSAPP_NOTIFY_KINDS = frozenset([
    "speeding", "harsh_braking", "harsh_accel", "harsh_cornering",
])


@receiver(post_save, sender="tracking.Alert")
def on_alert_created(sender, instance, created, **kwargs):
    if not created:
        return
    from mytrack.tracking.models import AlertKind
    if instance.kind == AlertKind.SPEEDING:
        from mytrack.notifications.emails import send_speeding_alert
        send_speeding_alert(instance)

    if instance.kind in _WHATSAPP_NOTIFY_KINDS:
        import threading
        from mytrack.notifications.whatsapp import notify_driver
        if instance.kind == AlertKind.SPEEDING:
            detail = f"{instance.value:.0f} km/h in a {instance.threshold:.0f} km/h zone" if instance.value and instance.threshold else ""
        else:
            detail = ""
        threading.Thread(
            target=notify_driver,
            args=(instance.driver_name, instance.vehicle.organisation, instance.get_kind_display(), instance.vehicle.registration, detail),
            kwargs={"vehicle": instance.vehicle},
            daemon=True,
        ).start()

    if instance.kind in _CLIP_REQUEST_KINDS:
        try:
            from mytrack.video_telematics.clip_request import request_clip_for_alert
            request_clip_for_alert(instance)
        except Exception:
            pass
