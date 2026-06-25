from django.urls import path
from . import views

urlpatterns = [
    path("", views.GeofenceListView.as_view(), name="geofence-list"),
    path("add/", views.GeofenceCreateView.as_view(), name="geofence-add"),
    path("<int:pk>/edit/", views.GeofenceUpdateView.as_view(), name="geofence-edit"),
    path("<int:pk>/delete/", views.geofence_delete, name="geofence-delete"),
    path("geojson/", views.geofences_geojson, name="geofences-geojson"),
    path("parse-file/", views.parse_geofence_file, name="geofence-parse-file"),
]
