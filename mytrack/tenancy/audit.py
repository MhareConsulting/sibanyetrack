"""Audit log helper — call log_audit() from views/signals to record changes."""


def log_audit(request_or_user, action: str, obj, delta: dict = None):
    """
    Record an audit event.

    action: 'create' | 'update' | 'delete' | 'resolve' | 'login'
    obj: the model instance being acted on
    delta: optional {field: [old, new]} dict
    """
    from mytrack.tenancy.models import AuditEvent

    try:
        user = getattr(request_or_user, "user", request_or_user)
        if not user or not user.pk:
            user = None
        org = getattr(user, "organisation", None) if user else None
        if org is None:
            org = getattr(obj, "organisation", None)
        if org is None:
            return

        AuditEvent.objects.create(
            organisation=org,
            user=user,
            action=action,
            target_model=obj.__class__.__name__,
            target_id=str(obj.pk),
            target_repr=str(obj)[:200],
            delta=delta or {},
        )
    except Exception:
        pass  # Never block the request on audit failure
