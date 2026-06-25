from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms_admin import StaffUserCreateForm, StaffUserEditForm
from .models import Organisation, User


def _staff_required(request):
    if not (request.user.is_authenticated and request.user.is_staff):
        raise Http404


@login_required
def admin_applications(request):
    _staff_required(request)
    orgs = (
        Organisation.objects.annotate(
            user_count=Count("users", distinct=True),
            vehicle_count=Count("vehicles", distinct=True),
            device_count=Count("devices", distinct=True),
            licensed_count=Count("users", filter=Q(users__consumes_license=True), distinct=True),
        )
        .order_by("name")
    )
    return render(request, "tenancy/admin_applications.html", {"orgs": orgs})


@login_required
def admin_user_search(request):
    _staff_required(request)
    q = request.GET.get("q", "").strip()
    users = User.objects.select_related("organisation").order_by("organisation__name", "username")
    if q:
        users = users.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
        )
    return render(request, "tenancy/admin_users.html", {"users": users, "q": q})


@login_required
def admin_user_create(request):
    _staff_required(request)
    org_pk = request.GET.get("organisation")
    initial_org = None
    if org_pk:
        initial_org = get_object_or_404(Organisation, pk=org_pk)
    if request.method == "POST":
        form = StaffUserCreateForm(request.POST, initial_org=initial_org)
        if form.is_valid():
            form.save()
            messages.success(request, f"User “{form.instance.username}” was created.")
            return redirect("admin-user-search")
    else:
        form = StaffUserCreateForm(initial_org=initial_org)
    return render(
        request,
        "tenancy/admin_user_form.html",
        {"form": form, "creating": True, "target_user": None},
    )


@login_required
def admin_user_edit(request, pk):
    _staff_required(request)
    user = get_object_or_404(User, pk=pk)
    can_edit_staff = request.user.is_superuser
    if request.method == "POST":
        form = StaffUserEditForm(
            request.POST,
            instance=user,
            can_edit_staff=can_edit_staff,
        )
        if form.is_valid():
            form.save()
            messages.success(request, f"User “{user.username}” was updated.")
            return redirect("admin-user-search")
    else:
        form = StaffUserEditForm(instance=user, can_edit_staff=can_edit_staff)
    return render(
        request,
        "tenancy/admin_user_form.html",
        {"form": form, "creating": False, "target_user": user},
    )


@login_required
def admin_org_detail(request, pk):
    _staff_required(request)
    org = get_object_or_404(Organisation, pk=pk)

    if request.method == "POST" and "save_settings" in request.POST:
        try:
            org.seat_limit = int(request.POST.get("seat_limit", org.seat_limit))
            org.speed_limit_kmh = int(request.POST.get("speed_limit_kmh", org.speed_limit_kmh))
            org.road_speed_limits_enabled = request.POST.get("road_speed_limits_enabled") == "on"
            org.speeding_grace_kmh = float(request.POST.get("speeding_grace_kmh", org.speeding_grace_kmh) or 0)
            org.fuel_price_zar = request.POST.get("fuel_price_zar", org.fuel_price_zar)
            org.idle_burn_rate_lph = request.POST.get("idle_burn_rate_lph", org.idle_burn_rate_lph)
            org.save(
                update_fields=[
                    "seat_limit",
                    "speed_limit_kmh",
                    "road_speed_limits_enabled",
                    "speeding_grace_kmh",
                    "fuel_price_zar",
                    "idle_burn_rate_lph",
                ]
            )
        except (ValueError, TypeError):
            pass
        return redirect("admin-org-detail", pk=pk)

    if request.method == "POST" and "toggle_license" in request.POST:
        uid = request.POST.get("user_id")
        try:
            u = User.objects.get(pk=uid, organisation=org)
            u.consumes_license = not u.consumes_license
            u.save(update_fields=["consumes_license"])
        except User.DoesNotExist:
            pass
        return redirect("admin-org-detail", pk=pk)

    from mytrack.vehicles.models import Device
    users = org.users.order_by("username")
    devices = Device.objects.filter(organisation=org).select_related("vehicle").order_by("-last_activity")
    licensed_count = users.filter(consumes_license=True).count()

    return render(request, "tenancy/admin_org_detail.html", {
        "org": org,
        "users": users,
        "devices": devices,
        "licensed_count": licensed_count,
        "tab": request.GET.get("tab", "users"),
    })
