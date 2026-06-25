from django.urls import path
from . import views

urlpatterns = [
    path("",                                      views.fleet_dashboard,       name="intelligence-dashboard"),
    path("events/live/",                            views.events_live_dashboard, name="events-live-dashboard"),
    path("events/live/queue/",                      views.dispatcher_queue_fragment, name="dispatcher-queue-fragment"),
    path("events/dashboard/",                      views.events_dashboard,      name="events-dashboard"),
    path("events/",                               views.unified_event_list,    name="event-list"),
    path("alerts/",                               views.alert_list,            name="alert-list"),
    path("alerts/<int:alert_id>/resolve/",        views.alert_resolve,           name="alert-resolve"),
    path("alerts/bulk/",                          views.alerts_bulk_action,      name="alerts-bulk-action"),
    path("alerts/resolve-filtered/",             views.alerts_resolve_filtered,  name="alerts-resolve-filtered"),
    path("trips/",                                views.trip_list,             name="trip-list"),
    path("trips/<int:trip_id>/replay/",           views.trip_replay,           name="trip-replay"),
    path("geofence-events/",                      views.geofence_event_list,   name="geofence-event-list"),
    # Intelligence
    path("driver-scores/",                        views.driver_score_list,     name="driver-score-list"),
    path("driver-scores/<int:driver_id>/",        views.driver_score_detail,   name="driver-score-detail"),
    path("dwell-time/",                           views.dwell_time_report,     name="dwell-time-report"),
    path("fleet-cost/",                           views.fleet_cost_report,     name="fleet-cost-report"),
    path("trips/sars-logbook/",                      views.export_sars_logbook,   name="export-sars-logbook"),
    # Exports
    path("reports/trips/csv/",                    views.reports_trips_csv,     name="reports-trips-csv"),
    path("reports/trips/pdf/",                    views.reports_trips_pdf,     name="reports-trips-pdf"),
    path("reports/geofence-events/csv/",          views.reports_geofence_csv,  name="reports-geofence-csv"),
    path("reports/geofence-events/pdf/",          views.reports_geofence_pdf,  name="reports-geofence-pdf"),
    # Route dispatch console
    path("routes/live/",       views.route_dispatch,                name="route-dispatch"),
    path("routes/live/trips/", views.route_dispatch_trips_fragment, name="route-dispatch-trips"),
]
