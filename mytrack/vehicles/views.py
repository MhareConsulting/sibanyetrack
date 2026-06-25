from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import FloatField, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View
from django.urls import reverse_lazy

from mytrack.fuel.models import FuelReading
from mytrack.tenancy.mixins import DepotScopedMixin
from mytrack.tenancy.models import Depot, Role

from .forms import DepotForm, VehicleDepotAssignmentForm, VehicleForm
from .models import Vehicle, VehicleDepotAssignment


# ─── Vehicles ────────────────────────────────────────────────────────────────

class VehicleListView(LoginRequiredMixin, DepotScopedMixin, ListView):
    template_name = "vehicles/list.html"
    context_object_name = "vehicles"

    def get_queryset(self):
        latest_fuel_sq = (
            FuelReading.objects.filter(vehicle=OuterRef("pk"))
            .order_by("-device_timestamp")
            .values("fuel_level_litres")[:1]
        )
        return (
            Vehicle.objects.filter(
                organisation=self.request.user.organisation,
                is_active=True,
            )
            .filter(
                Q(home_depot__in=self.accessible_depots) | Q(home_depot__isnull=True)
            )
            .select_related("state", "home_depot")
            .annotate(latest_fuel_litres=Subquery(latest_fuel_sq, output_field=FloatField()))
            .order_by("registration")
        )


class VehicleUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "vehicles/form.html"
    form_class = VehicleForm
    success_url = reverse_lazy("vehicle-list")

    def get_queryset(self):
        return Vehicle.objects.filter(organisation=self.request.user.organisation)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organisation"] = self.request.user.organisation
        return kwargs


# ─── Depots ──────────────────────────────────────────────────────────────────

class DepotListView(LoginRequiredMixin, DepotScopedMixin, ListView):
    template_name = "depots/list.html"
    context_object_name = "depots"

    def get_queryset(self):
        return (
            self.accessible_depots
            .filter(is_active=True)
            .prefetch_related("vehicles", "vehicle_assignments__vehicle")
            .order_by("name")
        )


class DepotCreateView(LoginRequiredMixin, CreateView):
    template_name = "depots/form.html"
    form_class = DepotForm
    success_url = reverse_lazy("depot-list")

    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in (Role.ADMIN,) and not request.user.is_superuser:
            messages.error(request, "Only admins can create depots.")
            return redirect("depot-list")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.organisation = self.request.user.organisation
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action"] = "Add"
        return ctx


class DepotUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "depots/form.html"
    form_class = DepotForm
    success_url = reverse_lazy("depot-list")

    def get_queryset(self):
        return Depot.objects.filter(organisation=self.request.user.organisation)

    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in (Role.ADMIN,) and not request.user.is_superuser:
            messages.error(request, "Only admins can edit depots.")
            return redirect("depot-list")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action"] = "Edit"
        return ctx


class DepotDetailView(LoginRequiredMixin, DepotScopedMixin, DetailView):
    template_name = "depots/detail.html"
    context_object_name = "depot"

    def get_queryset(self):
        return self.accessible_depots.prefetch_related(
            "vehicles__state",
            "vehicle_assignments__vehicle__state",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        depot = self.object
        org = self.request.user.organisation

        today = timezone.now().date()
        active_assignments = depot.vehicle_assignments.filter(
            start_date__lte=today
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        ).select_related("vehicle")

        ctx["home_vehicles"] = depot.vehicles.filter(is_active=True).select_related("state")
        ctx["active_assignments"] = active_assignments
        ctx["assign_form"] = VehicleDepotAssignmentForm(organisation=org, depot=depot)
        ctx["today"] = today
        return ctx


# ─── Assignments ─────────────────────────────────────────────────────────────

class VehicleAssignView(LoginRequiredMixin, View):
    """POST: create a borrow or transfer assignment for a vehicle."""

    def post(self, request, depot_pk):
        depot = get_object_or_404(Depot, pk=depot_pk, organisation=request.user.organisation)
        form = VehicleDepotAssignmentForm(request.POST, organisation=request.user.organisation, depot=depot)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.depot = depot
            if assignment.kind == "transfer":
                # Update home_depot on the vehicle and close any open borrows
                vehicle = assignment.vehicle
                vehicle.home_depot = depot
                vehicle.save(update_fields=["home_depot"])
                vehicle.depot_assignments.filter(
                    end_date__isnull=True
                ).update(end_date=assignment.start_date)
            assignment.save()
            messages.success(request, f"{assignment.vehicle} assigned to {depot} ({assignment.get_kind_display()}).")
        else:
            messages.error(request, "Assignment could not be saved — check the form.")
        return redirect("depot-detail", pk=depot_pk)


class AssignmentEndView(LoginRequiredMixin, View):
    """POST: close an open assignment (end a borrow or transfer)."""

    def post(self, request, pk):
        assignment = get_object_or_404(
            VehicleDepotAssignment,
            pk=pk,
            depot__organisation=request.user.organisation,
        )
        assignment.end_date = timezone.now().date()
        assignment.save(update_fields=["end_date"])
        messages.success(request, f"Assignment for {assignment.vehicle} ended.")
        return redirect("depot-detail", pk=assignment.depot_id)


