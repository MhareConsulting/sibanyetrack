from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render

from mytrack.tenancy.mixins import SESSION_KEY
from mytrack.tenancy.models import Organisation, Role


class RoleAwareLoginView(LoginView):
    """Redirect DRIVER-role users to their portal after login."""

    def get_success_url(self):
        user = self.request.user
        if getattr(user, "role", None) == Role.DRIVER:
            return "/drivers/portal/"
        if getattr(user, "role", None) in (Role.DISPATCHER, Role.VIEWER):
            if self.request.GET.get("desktop") == "1" or self.request.COOKIES.get("mytrack_desktop") == "1":
                return "/"
            return "/app/"
        return super().get_success_url()


@login_required
def depot_switch(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    depot_id = request.POST.get("depot_id", "")
    next_url = request.POST.get("next", "/")

    if depot_id == "all" and (
        request.user.role == Role.ADMIN or request.user.is_superuser
    ):
        request.session[SESSION_KEY] = "all"
    else:
        accessible = request.user.accessible_depots()
        try:
            depot = accessible.get(pk=int(depot_id))
            request.session[SESSION_KEY] = depot.pk
        except (ValueError, TypeError, accessible.model.DoesNotExist):
            pass  # Ignore invalid depot_id

    return redirect(next_url)


class OrgFuelSettingsForm(forms.ModelForm):
    class Meta:
        model = Organisation
        fields = [
            "fuel_price_zar",
            "idle_burn_rate_lph",
            "email_daily_digest_enabled",
            "email_weekly_summary_enabled",
            "email_monthly_summary_enabled",
            "email_expiry_warnings_enabled",
            "notification_cc_emails",
            "whatsapp_driver_notify_enabled",
        ]
        labels = {
            "fuel_price_zar": "Fuel price per litre (R)",
            "idle_burn_rate_lph": "Idle burn rate (litres/hour)",
            "email_daily_digest_enabled": "Daily alert digest",
            "email_weekly_summary_enabled": "Weekly fleet and safety summary",
            "email_monthly_summary_enabled": "Monthly fleet and safety summary",
            "email_expiry_warnings_enabled": "Document expiry warnings",
            "notification_cc_emails": "Extra CC addresses (optional)",
            "whatsapp_driver_notify_enabled": "Send WhatsApp alerts to drivers",
        }
        help_texts = {
            "notification_cc_emails": "Comma-separated. Copied on scheduled emails above (not on every instant alert).",
            "whatsapp_driver_notify_enabled": "Sends an instant WhatsApp message to the driver when a critical alert, speeding event, geofence violation, or inspection failure is triggered.",
        }
        widgets = {
            "fuel_price_zar": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
            "idle_burn_rate_lph": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
            "email_daily_digest_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_weekly_summary_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_monthly_summary_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_expiry_warnings_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notification_cc_emails": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "whatsapp_driver_notify_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


@login_required
def org_settings(request):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        return redirect("/")

    org = request.user.organisation
    if request.method == "POST":
        form = OrgFuelSettingsForm(request.POST, instance=org)
        if form.is_valid():
            form.save()
            return redirect("org-settings")
    else:
        form = OrgFuelSettingsForm(instance=org)

    return render(request, "tenancy/org_settings.html", {"form": form})


@login_required
def audit_log_view(request):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        return redirect("/")

    from mytrack.tenancy.models import AuditEvent
    from django.core.paginator import Paginator

    org = request.user.organisation
    qs = AuditEvent.objects.filter(organisation=org).select_related("user").order_by("-occurred_at")

    action_filter = request.GET.get("action", "")
    model_filter = request.GET.get("model", "")
    user_filter = request.GET.get("user", "")

    if action_filter:
        qs = qs.filter(action=action_filter)
    if model_filter:
        qs = qs.filter(target_model=model_filter)
    if user_filter:
        qs = qs.filter(user__username__icontains=user_filter)

    page = Paginator(qs, 50).get_page(request.GET.get("page", 1))
    distinct_actions = AuditEvent.objects.filter(organisation=org).values_list("action", flat=True).distinct()
    distinct_models = AuditEvent.objects.filter(organisation=org).values_list("target_model", flat=True).distinct()

    return render(request, "tenancy/audit_log.html", {
        "page_obj": page,
        "action_filter": action_filter,
        "model_filter": model_filter,
        "user_filter": user_filter,
        "distinct_actions": sorted(set(distinct_actions)),
        "distinct_models": sorted(set(distinct_models)),
    })


# ── Two-factor authentication ─────────────────────────────────────────────────

@login_required
def setup_2fa(request):
    import base64
    import io

    import qrcode
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = request.user

    def _qr_ctx(dev):
        uri = dev.config_url
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()
        # base32 secret for manual entry
        import base64 as _b64
        try:
            manual = _b64.b32encode(dev.bin_key).decode()
        except Exception:
            manual = ""
        return {"qr_b64": qr_b64, "manual_key": manual}

    if request.method == "POST":
        token = request.POST.get("token", "").strip()
        device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
        if device and device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            return redirect("2fa-verify")
        ctx = {"error": "Invalid code — try again."}
        if device:
            ctx.update(_qr_ctx(device))
        return render(request, "tenancy/2fa_setup.html", ctx)

    # Create or reuse unconfirmed device
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if not device:
        TOTPDevice.objects.filter(user=user).delete()
        device = TOTPDevice.objects.create(user=user, name="myTrack", confirmed=False)
    return render(request, "tenancy/2fa_setup.html", _qr_ctx(device))


@login_required
def verify_2fa(request):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = request.user
    if request.method == "POST":
        token = request.POST.get("token", "").strip()
        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if device and device.verify_token(token):
            from django_otp import login as otp_login
            otp_login(request, device)
            return redirect(request.POST.get("next", "/"))
        return render(request, "tenancy/2fa_verify.html", {
            "error": "Invalid code.", "next": request.POST.get("next", "/")
        })
    return render(request, "tenancy/2fa_verify.html", {"next": request.GET.get("next", "/")})


@login_required
def disable_2fa(request):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    if request.method == "POST":
        TOTPDevice.objects.filter(user=request.user).delete()
    return redirect("org-settings")
