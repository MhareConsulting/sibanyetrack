from __future__ import annotations

import re
from typing import Any

from mytrack.tracking.models import AlertKind


_TOKEN_KIND_MAP = (
    (("harsh_braking", "hard_braking", "hard_brake", "sudden_brake", "rapid_deceleration"), AlertKind.HARSH_BRAKING),
    (("harsh_accel", "hard_accel", "harsh_acceleration", "hard_acceleration", "rapid_acceleration", "sudden_acceleration"), AlertKind.HARSH_ACCEL),
    (("harsh_cornering", "hard_cornering", "cornering"), AlertKind.HARSH_CORNERING),
    (("lane_departure", "ldw", "lane_departure"), AlertKind.LANE_DEPARTURE),
    (("fatigue", "drowsy", "yawn", "sleep"), AlertKind.FATIGUE),
    (("phone_use", "phone", "distracted"), AlertKind.PHONE_USE),
    (("seatbelt", "seat_belt", "no_seatbelt"), AlertKind.SEATBELT),
    (("speeding", "over_speed", "overspeed"), AlertKind.SPEEDING),
    (("idle", "idling"), AlertKind.IDLE),
)

_EVENT_KEY_CANDIDATES = (
    "alarm",
    "alarm_type",
    "alarmType",
    "event",
    "event_type",
    "eventType",
    "type",
    "notificationType",
)

_BOOLEAN_EVENT_FLAG_TO_KIND = (
    ("harshBraking", AlertKind.HARSH_BRAKING),
    ("harsh_braking", AlertKind.HARSH_BRAKING),
    ("hardBraking", AlertKind.HARSH_BRAKING),
    ("hardBrake", AlertKind.HARSH_BRAKING),
    ("hard_brake", AlertKind.HARSH_BRAKING),
    ("harshAcceleration", AlertKind.HARSH_ACCEL),
    ("harsh_accel", AlertKind.HARSH_ACCEL),
    ("hardAcceleration", AlertKind.HARSH_ACCEL),
    ("harshCornering", AlertKind.HARSH_CORNERING),
    ("hardCornering", AlertKind.HARSH_CORNERING),
    ("harsh_cornering", AlertKind.HARSH_CORNERING),
    ("laneDeparture", AlertKind.LANE_DEPARTURE),
    ("lane_departure", AlertKind.LANE_DEPARTURE),
    ("fatigue", AlertKind.FATIGUE),
    ("drowsiness", AlertKind.FATIGUE),
    ("phoneUse", AlertKind.PHONE_USE),
    ("phone_use", AlertKind.PHONE_USE),
    ("seatbelt", AlertKind.SEATBELT),
    ("seat_belt", AlertKind.SEATBELT),
)


def _normalized_tokens(raw: Any) -> list[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    # Split camelCase: "hardAcceleration" → "hard_Acceleration" → lower → "hard_acceleration"
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text).lower()
    text = text.replace("-", "_").replace(" ", "_")
    return [tok for tok in text.split("_") if tok]


def normalize_traccar_alert_kind(attributes: dict[str, Any] | None) -> str | None:
    """Map Traccar attributes to the closest AlertKind.

    Returns CAMERA_EVENT for detectable-but-unmapped categories so they are still visible
    in myTrack.
    """
    if not isinstance(attributes, dict):
        return None

    for key, kind in _BOOLEAN_EVENT_FLAG_TO_KIND:
        value = attributes.get(key)
        if value in (True, 1, "1", "true", "True", "YES", "yes"):
            return kind

    for field in _EVENT_KEY_CANDIDATES:
        raw = attributes.get(field)
        if raw is None:
            continue
        joined = "_".join(_normalized_tokens(raw))
        if not joined:
            continue
        for aliases, kind in _TOKEN_KIND_MAP:
            if any(alias in joined for alias in aliases):
                return kind
        return AlertKind.CAMERA_EVENT

    return None

