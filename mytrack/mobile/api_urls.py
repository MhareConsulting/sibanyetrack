from django.urls import path

from . import api

urlpatterns = [
    path("bootstrap/", api.bootstrap, name="mobile-api-bootstrap"),
    path("vehicles/", api.vehicle_list, name="mobile-api-vehicles"),
    path("vehicles/<int:vehicle_id>/", api.vehicle_detail, name="mobile-api-vehicle-detail"),
    path("vehicles/<int:vehicle_id>/last-trip/", api.vehicle_last_trip, name="mobile-api-vehicle-last-trip"),
    path("trips/", api.trip_list, name="mobile-api-trips"),
    path("trips/<int:trip_id>/replay/", api.trip_replay, name="mobile-api-trip-replay"),
    path("trips/<int:trip_id>/classification/", api.trip_classification, name="mobile-api-trip-classification"),
    path("share/location/", api.share_location, name="mobile-api-share-location"),
    path("insights/", api.insights, name="mobile-api-insights"),
]
