from django.shortcuts import redirect

from mytrack.tenancy.models import Depot, Role

SESSION_KEY = "active_depot_id"


class Require2FAMixin:
    """
    Redirect users to 2FA setup/verify if their org requires it and they
    haven't completed TOTP verification for this session.
    """

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            org = getattr(request.user, "organisation", None)
            if org and getattr(org, "require_2fa", False):
                from django_otp.plugins.otp_totp.models import TOTPDevice
                from django_otp import user_is_verified
                has_device = TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()
                if not has_device:
                    return redirect("/tenancy/2fa/setup/")
                if not user_is_verified(request.user):
                    return redirect(f"/tenancy/2fa/verify/?next={request.path}")
        return super().dispatch(request, *args, **kwargs)


class DepotScopedMixin:
    """
    Restrict list/detail views to the depots a user can access.
    Also manages the active depot stored in the session.
    """

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if request.user.is_authenticated:
            self._accessible_depots = request.user.accessible_depots()
            self._active_depot = self._resolve_active_depot(request)

    def _resolve_active_depot(self, request):
        is_admin = request.user.role == Role.ADMIN or request.user.is_superuser
        depot_id = request.session.get(SESSION_KEY)

        if depot_id is None:
            if is_admin:
                return None  # Admin default: all depots
            first = self._accessible_depots.first()
            if first:
                request.session[SESSION_KEY] = first.pk
            return first

        if depot_id == "all":
            return None  # Explicit "all depots" selection

        try:
            depot = self._accessible_depots.get(pk=depot_id)
            return depot
        except Depot.DoesNotExist:
            # Session has a depot they no longer have access to — reset
            request.session.pop(SESSION_KEY, None)
            return self._accessible_depots.first()

    @property
    def accessible_depots(self):
        return self._accessible_depots

    @property
    def active_depot(self):
        return self._active_depot

    def active_depot_vehicle_filter(self):
        """Returns a dict suitable for **filter() to scope vehicles by active depot."""
        if self._active_depot is None:
            return {}
        return {"vehicle__home_depot": self._active_depot}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["accessible_depots"] = self._accessible_depots
        ctx["active_depot"] = self._active_depot
        ctx["is_admin"] = (
            self.request.user.role == Role.ADMIN or self.request.user.is_superuser
        )
        return ctx
