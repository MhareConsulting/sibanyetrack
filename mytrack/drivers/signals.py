from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Driver


@receiver(post_save, sender=Driver)
def sync_driver_to_myroutes(sender, instance, **kwargs):
    from mytrack.tracking.sync import push_driver
    push_driver(instance)
