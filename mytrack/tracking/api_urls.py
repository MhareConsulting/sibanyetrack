from django.urls import path

from .ingest import ingest_ping, ingest_traccar
from .api_upsert import upsert_vehicle, upsert_driver, upsert_depot
from .views import trip_pings_api, trip_alerts_api, vehicle_trail_api, vehicle_trips_api
from mytrack.video_telematics.ingest_api import (
    video_presign_upload,
    video_upload_complete,
    video_upload_intent_put,
    video_webhook,
)
from mytrack.video_telematics.streamax_ingest import streamax_event_push
from mytrack.notifications.cron_api import cron_email_jobs, cron_flush_outbox

urlpatterns = [
    path("ingest/ping/", ingest_ping, name="ingest-ping"),
    path("ingest/traccar/", ingest_traccar, name="ingest-traccar"),
    path("vehicles/upsert/", upsert_vehicle, name="api-vehicle-upsert"),
    path("drivers/upsert/", upsert_driver, name="api-driver-upsert"),
    path("depots/upsert/", upsert_depot, name="api-depot-upsert"),
    path("trips/<int:trip_id>/pings/", trip_pings_api, name="api-trip-pings"),
    path("trips/<int:trip_id>/alerts/", trip_alerts_api, name="api-trip-alerts"),
    path("vehicles/<int:vehicle_id>/trips/", vehicle_trips_api, name="api-vehicle-trips"),
    path("tracking/trail/", vehicle_trail_api, name="api-vehicle-trail"),
    path("video/webhook/", video_webhook, name="api-video-webhook"),
    path("video/presign-upload/", video_presign_upload, name="api-video-presign-upload"),
    path("video/upload/complete/", video_upload_complete, name="api-video-upload-complete"),
    path("video/upload/intent/<uuid:intent_id>/", video_upload_intent_put, name="api-video-upload-intent"),
    path("video/streamax/event/", streamax_event_push, name="api-video-streamax-event"),
    path("cron/email-jobs/", cron_email_jobs, name="api-cron-email-jobs"),
    path("cron/flush-outbox/", cron_flush_outbox, name="api-cron-flush-outbox"),
]
