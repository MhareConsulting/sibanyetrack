from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, OuterRef, Subquery, PositiveSmallIntegerField
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import DriverForm
from .models import Driver, DriverScore


class DriverListView(LoginRequiredMixin, ListView):
    template_name = "drivers/list.html"
    context_object_name = "drivers"

    def get_queryset(self):
        latest_score_sq = (
            DriverScore.objects.filter(driver=OuterRef("pk"))
            .order_by("-scored_date")
            .values("score")[:1]
        )
        return (
            Driver.objects.filter(organisation=self.request.user.organisation)
            .select_related("default_vehicle")
            .annotate(score_today=Subquery(latest_score_sq, output_field=PositiveSmallIntegerField()))
            .order_by("full_name")
        )


class DriverDetailView(LoginRequiredMixin, DetailView):
    template_name = "drivers/detail.html"
    context_object_name = "driver"

    def get_queryset(self):
        return Driver.objects.filter(organisation=self.request.user.organisation)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["recent_pings"] = (
            self.object.default_vehicle.pings.all()[:20]
            if self.object.default_vehicle
            else []
        )
        return ctx


class DriverCreateView(LoginRequiredMixin, CreateView):
    template_name = "drivers/form.html"
    form_class = DriverForm
    success_url = reverse_lazy("driver-list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organisation"] = self.request.user.organisation
        return kwargs

    def form_valid(self, form):
        form.instance.organisation = self.request.user.organisation
        return super().form_valid(form)


class DriverUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "drivers/form.html"
    form_class = DriverForm
    success_url = reverse_lazy("driver-list")

    def get_queryset(self):
        return Driver.objects.filter(organisation=self.request.user.organisation)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organisation"] = self.request.user.organisation
        return kwargs


# ─── Driver Self-Service Portal ───────────────────────────────────────────────

def _require_driver_role(request):
    """Return the linked driver or HttpResponseForbidden if not a DRIVER-role user."""
    from mytrack.tenancy.models import Role
    if request.user.role != Role.DRIVER or not request.user.linked_driver_id:
        return None, HttpResponseForbidden("Driver portal access only.")
    driver = get_object_or_404(Driver, pk=request.user.linked_driver_id)
    return driver, None


@login_required
def driver_portal_home(request):
    driver, err = _require_driver_role(request)
    if err:
        return err

    today = timezone.localtime(timezone.now()).date()
    week_ago = today - timedelta(days=6)

    scores = list(driver.scores.filter(scored_date__gte=week_ago).order_by("scored_date"))
    latest_score = scores[-1] if scores else None

    # Top alert kinds for this driver over the last 7 days
    from mytrack.tracking.models import Alert
    alert_summary = (
        Alert.objects.filter(
            driver_name=driver.full_name,
            vehicle__organisation=driver.organisation,
            occurred_at__date__gte=week_ago,
        )
        .values("kind")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )

    # Today's trips
    from datetime import datetime as _dt, time as _time
    from mytrack.tracking.models import TrackedTrip
    today_trips = []
    if driver.default_vehicle:
        today_start = timezone.make_aware(_dt.combine(today, _time.min))
        today_trips = list(
            TrackedTrip.objects.filter(
                vehicle=driver.default_vehicle,
                started_at__gte=today_start,
            ).order_by("-started_at")[:10]
        )

    grade = _score_to_grade(latest_score.score if latest_score else None)
    score_data = [{"date": s.scored_date.isoformat(), "score": s.score} for s in scores]

    return render(request, "drivers/portal_home.html", {
        "driver": driver,
        "latest_score": latest_score,
        "grade": grade,
        "score_data": score_data,
        "today_trips": today_trips,
    })


@login_required
def driver_portal_trips(request):
    driver, err = _require_driver_role(request)
    if err:
        return err

    from mytrack.tracking.models import TrackedTrip
    qs = []
    if driver.default_vehicle:
        qs = (
            TrackedTrip.objects.filter(vehicle=driver.default_vehicle)
            .order_by("-started_at")[:50]
        )

    return render(request, "drivers/portal_trips.html", {
        "driver": driver,
        "trips": qs,
    })


def _score_to_grade(score):
    if score is None:
        return "N/A"
    if score >= 90: return "A"
    if score >= 75: return "B"
    if score >= 60: return "C"
    if score >= 45: return "D"
    return "F"
