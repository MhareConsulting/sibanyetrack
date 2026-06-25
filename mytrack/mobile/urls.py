from django.urls import path

from . import views

urlpatterns = [
    path("", views.MobileHomeView.as_view(), name="mobile-home"),
    path("map/", views.MobileMapView.as_view(), name="mobile-map"),
    path("trips/", views.MobileTripsView.as_view(), name="mobile-trips"),
    path("assets/", views.MobileAssetsView.as_view(), name="mobile-assets"),
    path("trips/<int:trip_id>/replay/", views.MobileReplayView.as_view(), name="mobile-replay"),
    path("offline/", views.MobileOfflineView.as_view(), name="mobile-offline"),
]
