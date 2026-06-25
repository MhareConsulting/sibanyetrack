from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="mytrack_compliance.InspectionLog")
def on_inspection_saved(sender, instance, created, **kwargs):
    if not created:
        return
    from mytrack.compliance.models import InspectionLog
    if instance.result in (InspectionLog.Result.DEFECT, InspectionLog.Result.FAIL):
        from mytrack.notifications.emails import send_inspection_alert
        send_inspection_alert(instance)
        import threading
        from mytrack.notifications.whatsapp import notify_driver
        detail = f"Result: {instance.get_result_display()}"
        threading.Thread(
            target=notify_driver,
            args=(instance.driver_name, instance.vehicle.organisation, "Inspection Failure", instance.vehicle.registration, detail),
            daemon=True,
        ).start()
