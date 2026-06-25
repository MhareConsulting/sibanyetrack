from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from .models import WebhookDelivery, WebhookEndpoint

KNOWN_EVENTS = [
    "alert.critical",
    "trip.ended",
    "geofence.entry",
    "fuel.theft",
]


@login_required
def webhook_list(request):
    org = request.user.organisation
    endpoints = WebhookEndpoint.objects.filter(organisation=org).order_by('-created_at')
    recent_deliveries = (
        WebhookDelivery.objects
        .filter(endpoint__organisation=org)
        .select_related('endpoint')
        .order_by('-created_at')[:50]
    )
    return render(request, 'tenancy/webhooks.html', {
        'endpoints': endpoints,
        'recent_deliveries': recent_deliveries,
        'known_events': KNOWN_EVENTS,
    })


@login_required
def webhook_create(request):
    if request.method != 'POST':
        return redirect('webhook-list')
    org = request.user.organisation
    url = request.POST.get('url', '').strip()
    if not url:
        return redirect('webhook-list')
    events = request.POST.getlist('events')
    WebhookEndpoint.objects.create(organisation=org, url=url, events=events)
    return redirect('webhook-list')


@login_required
def webhook_delete(request, pk):
    org = request.user.organisation
    ep = get_object_or_404(WebhookEndpoint, pk=pk, organisation=org)
    if request.method == 'POST':
        ep.delete()
    return redirect('webhook-list')


@login_required
def webhook_toggle(request, pk):
    org = request.user.organisation
    ep = get_object_or_404(WebhookEndpoint, pk=pk, organisation=org)
    if request.method == 'POST':
        ep.is_active = not ep.is_active
        ep.save(update_fields=['is_active'])
    return redirect('webhook-list')
