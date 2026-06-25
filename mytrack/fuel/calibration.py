"""
Fuel probe calibration: converts raw sensor N-value to litres.

Two methods are supported per vehicle, in priority order:
  1. Polynomial   — coefficients fitted from the strapping table (highest power first).
                    Evaluated using Horner's method. Active when poly_coefficients is set.
  2. Piecewise    — classic strapping-table lookup with linear interpolation between
                    adjacent CalibrationPoint rows (GpsGate nonLinear() equivalent).

The ingest pipeline calls calibrate(vehicle, raw_value) and gets back litres or None.
"""


def _horner(coeffs, x):
    """Evaluate a polynomial at x using Horner's method. coeffs = [a_n, ..., a_1, a_0]."""
    result = 0.0
    for c in coeffs:
        result = result * x + c
    return result


def interpolate_polynomial(calibration, raw_value: float) -> float:
    """
    Evaluate the fitted polynomial for raw_value.
    Clamps the input to [0, poly_max_n] to avoid extrapolation blow-up.
    Returns calibrated litres (float, clamped to >= 0).
    """
    coeffs = calibration.poly_coefficients
    max_n = calibration.poly_max_n or max(raw_value, 1.0)
    x = max(0.0, min(float(raw_value), float(max_n)))
    litres = _horner(coeffs, x)
    return max(0.0, litres)


def interpolate(calibration, raw_value: float) -> float:
    """
    Convert raw_value to litres using piecewise linear interpolation
    over the vehicle's CalibrationPoint strapping table.

    Raises ValueError if fewer than 2 points are configured.
    """
    points = list(
        calibration.points.order_by('raw_value').values_list('raw_value', 'litres')
    )

    if len(points) < 2:
        raise ValueError(
            f"TankCalibration for vehicle '{calibration.vehicle}' needs at least 2 points "
            f"(currently has {len(points)})."
        )

    bottom = float(calibration.bottom_blind_litres)

    if raw_value <= points[0][0]:
        return points[0][1] + bottom

    if raw_value >= points[-1][0]:
        return points[-1][1]

    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= raw_value <= x1:
            t = (raw_value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0) + bottom

    return points[-1][1]


def has_calibration(vehicle) -> bool:
    """Return True if the vehicle has a usable calibration (polynomial or >= 2 points)."""
    try:
        cal = vehicle.tank_calibration
    except Exception:
        return False
    if cal.poly_coefficients:
        return True
    return cal.points.count() >= 2


def calibrate(vehicle, raw_value: float) -> float | None:
    """
    Return calibrated litres for raw_value, or None if no calibration is configured.
    Prefers polynomial over piecewise linear when both are present.
    """
    if not has_calibration(vehicle):
        return None
    cal = vehicle.tank_calibration
    if cal.poly_coefficients:
        return round(interpolate_polynomial(cal, raw_value), 2)
    return interpolate(cal, raw_value)
