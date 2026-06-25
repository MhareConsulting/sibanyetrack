from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Vehicle


@receiver(post_save, sender=Vehicle)
def sync_vehicle_to_myroutes(sender, instance, **kwargs):
    from mytrack.tracking.sync import push_vehicle
    push_vehicle(instance)


@receiver(post_delete, sender=Vehicle)
def delete_vehicle_from_myroutes(sender, instance, **kwargs):
    from mytrack.tracking.sync import delete_vehicle
    delete_vehicle(instance.pk, instance.organisation.slug)
