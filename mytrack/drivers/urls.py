from django.urls import path

from .views import (
    DriverCreateView, DriverDetailView, DriverListView, DriverUpdateView,
    driver_portal_home, driver_portal_trips,
)

urlpatterns = [
    path("", DriverListView.as_view(), name="driver-list"),
    path("add/", DriverCreateView.as_view(), name="driver-add"),
    path("portal/", driver_portal_home, name="driver-portal-home"),
    path("portal/trips/", driver_portal_trips, name="driver-portal-trips"),
    path("<int:pk>/", DriverDetailView.as_view(), name="driver-detail"),
    path("<int:pk>/edit/", DriverUpdateView.as_view(), name="driver-edit"),
]
