"""Populate start/end address labels when a trip is closed."""

import threading


def finalize_trip_labels(trip_id):
    """Reverse-geocode trip start/end in a background thread."""
    threading.Thread(target=_finalize_trip_labels_sync, args=(trip_id,), daemon=True).start()


def _finalize_trip_labels_sync(trip_id):
    from mytrack.tracking.ingest import _geocode_address
    from mytrack.tracking.models import TrackedTrip

    try:
        trip = TrackedTrip.objects.get(pk=trip_id)
    except TrackedTrip.DoesNotExist:
        return
    if not trip.ended_at:
        return

    updates = {}
    if not trip.start_label and trip.start_lat and trip.start_lon:
        label = _geocode_address(trip.start_lat, trip.start_lon)
        if label:
            updates["start_label"] = label[:300]
    if not trip.end_label and trip.end_lat and trip.end_lon:
        label = _geocode_address(trip.end_lat, trip.end_lon)
        if label:
            updates["end_label"] = label[:300]
    if updates:
        TrackedTrip.objects.filter(pk=trip_id).update(**updates)
