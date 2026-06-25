from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .mixins import SESSION_KEY
from .models import Depot, Role


@receiver(post_save, sender=Depot)
def sync_depot_to_myroutes(sender, instance, **kwargs):
    from mytrack.tracking.sync import push_depot
    push_depot(instance)


@receiver(post_delete, sender=Depot)
def delete_depot_from_myroutes(sender, instance, **kwargs):
    from mytrack.tracking.sync import delete_depot
    delete_depot(instance.pk, instance.organisation.slug)


@receiver(user_logged_in)
def seed_active_depot(sender, request, user, **kwargs):
    if SESSION_KEY in request.session:
        return
    is_admin = user.role == Role.ADMIN or user.is_superuser
    if is_admin:
        request.session[SESSION_KEY] = "all"
    else:
        first = user.accessible_depots().first()
        request.session[SESSION_KEY] = first.pk if first else None


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    from mytrack.tenancy.audit import log_audit
    log_audit(user, "login", user)


@receiver(post_save)
def audit_model_save(sender, instance, created, **kwargs):
    """Log create/update for Vehicle, Driver, Depot models."""
    _AUDITED = ("Vehicle", "Driver", "Depot")
    if sender.__name__ not in _AUDITED:
        return
    if not hasattr(instance, "organisation"):
        return
    action = "create" if created else "update"
    from mytrack.tenancy.audit import log_audit
    log_audit(None, action, instance)
