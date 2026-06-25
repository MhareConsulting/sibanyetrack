from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from mytrack.tracking.models import DeliveryShare
from mytrack.vehicles.models import Vehicle


class DeliveryShareForm(forms.ModelForm):
    expires_hours = forms.ChoiceField(
        choices=[(4, "4 hours"), (8, "8 hours"), (24, "24 hours"), (48, "48 hours"), (72, "72 hours")],
        initial=8,
        label="Link valid for",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    class Meta:
        model = DeliveryShare
        fields = ["vehicle", "customer_name", "customer_email", "note", "destination_address", "destination_lat", "destination_lon", "stop_number", "total_stops"]
        widgets = {
            "vehicle": forms.Select(attrs={"class": "form-control"}),
            "customer_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. John Smith"}),
            "customer_email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "customer@example.com"}),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Order #1234 — 3x boxes"}),
            "destination_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 14 Main Street, Sandton"}),
            "destination_lat": forms.NumberInput(attrs={"class": "form-control", "step": "any", "placeholder": "-26.1234"}),
            "destination_lon": forms.NumberInput(attrs={"class": "form-control", "step": "any", "placeholder": "28.0456"}),
            "stop_number": forms.NumberInput(attrs={"class": "form-control", "min": "1", "placeholder": "e.g. 3"}),
            "total_stops": forms.NumberInput(attrs={"class": "form-control", "min": "1", "placeholder": "e.g. 5"}),
        }
        labels = {
            "destination_address": "Destination address",
            "destination_lat": "Destination latitude (optional)",
            "destination_lon": "Destination longitude (optional)",
            "stop_number": "This customer's stop number",
            "total_stops": "Total stops on this run",
        }

    def __init__(self, org, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(organisation=org, is_active=True).order_by("registration")


@login_required
def delivery_share_list(request):
    org = request.user.organisation
    shares = (
        DeliveryShare.objects
        .filter(vehicle__organisation=org)
        .select_related("vehicle", "created_by")
        .order_by("-created_at")
    )
    from mytrack.tenancy.mixins import SESSION_KEY
    from mytrack.tenancy.models import Depot, Role
    active_depot_id = request.session.get(SESSION_KEY)
    is_admin = request.user.role == Role.ADMIN or request.user.is_superuser
    accessible = request.user.accessible_depots()
    active_depot = None
    if active_depot_id and active_depot_id != "all":
        try:
            active_depot = accessible.get(pk=active_depot_id)
            shares = shares.filter(vehicle__home_depot=active_depot)
        except Depot.DoesNotExist:
            pass

    return render(request, "tracking/delivery_shares.html", {
        "shares": shares,
        "accessible_depots": accessible,
        "active_depot": active_depot,
        "is_admin": is_admin,
    })


@login_required
def delivery_share_create(request):
    org = request.user.organisation
    from mytrack.tenancy.models import Role
    is_admin = request.user.role == Role.ADMIN or request.user.is_superuser
    accessible = request.user.accessible_depots()

    if request.method == "POST":
        form = DeliveryShareForm(org, request.POST)
        if form.is_valid():
            share = form.save(commit=False)
            share.created_by = request.user
            hours = int(form.cleaned_data["expires_hours"])
            share.expires_at = timezone.now() + timezone.timedelta(hours=hours)
            share.save()
            try:
                from mytrack.notifications.emails import send_delivery_link
                send_delivery_link(share)
            except Exception:
                pass  # Don't fail the create if email fails
            return redirect("delivery-share-list")
    else:
        form = DeliveryShareForm(org)

    return render(request, "tracking/delivery_share_create.html", {
        "form": form,
        "accessible_depots": accessible,
        "is_admin": is_admin,
    })


@login_required
def delivery_share_complete(request, share_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    share = get_object_or_404(
        DeliveryShare,
        pk=share_id,
        vehicle__organisation=request.user.organisation,
    )
    if share.completed_at is None:
        share.completed_at = timezone.now()
        share.save(update_fields=["completed_at"])
    return redirect("delivery-share-list")
