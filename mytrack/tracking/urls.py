from django.urls import path

from . import views
from .views_delivery import delivery_share_complete, delivery_share_create, delivery_share_list

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("live/stream/", views.live_stream, name="live-stream"),
    path("alerts/stream/", views.alert_stream, name="alert-stream"),
    path("deliveries/", delivery_share_list, name="delivery-share-list"),
    path("deliveries/create/", delivery_share_create, name="delivery-share-create"),
    path("deliveries/<int:share_id>/complete/", delivery_share_complete, name="delivery-share-complete"),
]
