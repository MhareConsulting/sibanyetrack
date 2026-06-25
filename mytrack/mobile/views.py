from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views import View

from mytrack.mobile.scope import get_depot_context
from mytrack.tenancy.mixins import Require2FAMixin


def _mobile_context(request, tab):
    active_depot, accessible, is_admin = get_depot_context(request)
    return {
        "mobile_tab": tab,
        "active_depot": active_depot,
        "accessible_depots": accessible,
        "is_admin": is_admin,
    }


class MobilePageView(Require2FAMixin, LoginRequiredMixin, View):
    template_name = ""
    tab = "home"

    def get(self, request):
        ctx = _mobile_context(request, self.tab)
        return render(request, self.template_name, ctx)


class MobileHomeView(MobilePageView):
    template_name = "mobile/home.html"
    tab = "home"


class MobileMapView(MobilePageView):
    template_name = "mobile/map.html"
    tab = "map"


class MobileTripsView(MobilePageView):
    template_name = "mobile/trips.html"
    tab = "trips"


class MobileAssetsView(MobilePageView):
    template_name = "mobile/assets.html"
    tab = "assets"


class MobileReplayView(MobilePageView):
    template_name = "mobile/replay.html"
    tab = "map"

    def get(self, request, trip_id):
        ctx = _mobile_context(request, self.tab)
        ctx["trip_id"] = trip_id
        return render(request, self.template_name, ctx)


class MobileOfflineView(MobilePageView):
    template_name = "mobile/offline.html"
    tab = "home"
