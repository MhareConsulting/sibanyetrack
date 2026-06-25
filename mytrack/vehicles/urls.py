from django.urls import path

from .views import (
    AssignmentEndView,
    DepotCreateView,
    DepotDetailView,
    DepotListView,
    DepotUpdateView,
    VehicleAssignView,
    VehicleListView,
    VehicleUpdateView,
)
from .views_devices import device_list, device_detail, device_add

urlpatterns = [
    path("", VehicleListView.as_view(), name="vehicle-list"),
    path("<int:pk>/edit/", VehicleUpdateView.as_view(), name="vehicle-edit"),

    path("depots/", DepotListView.as_view(), name="depot-list"),
    path("depots/add/", DepotCreateView.as_view(), name="depot-add"),
    path("depots/<int:pk>/", DepotDetailView.as_view(), name="depot-detail"),
    path("depots/<int:pk>/edit/", DepotUpdateView.as_view(), name="depot-edit"),
    path("depots/<int:depot_pk>/assign/", VehicleAssignView.as_view(), name="depot-assign"),
    path("assignments/<int:pk>/end/", AssignmentEndView.as_view(), name="assignment-end"),

    path("devices/", device_list, name="device-list"),
    path("devices/add/", device_add, name="device-add"),
    path("devices/<int:pk>/", device_detail, name="device-detail"),
]
