def alert_badge(request):
    if not request.user.is_authenticated:
        return {}
    try:
        org_id = request.user.organisation_id
    except AttributeError:
        return {}
    if not org_id:
        return {}
    cache_key = f"mytrack:unresolved_alert_count:{org_id}"
    from django.core.cache import cache
    count = cache.get(cache_key)
    if count is None:
        from mytrack.tracking.models import Alert
        count = Alert.objects.filter(
            vehicle__organisation_id=org_id,
            resolved_at__isnull=True,
        ).count()
        cache.set(cache_key, count, timeout=30)
    return {"unresolved_alert_count": count}
