from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

SG_GRADE_SCALE = 8192.0


@dataclass(frozen=True)
class ElevationCurve:
    value: Callable[[float], float]
    slope: Callable[[float], float]


CURVE_SHAPES: dict[str, ElevationCurve] = {
    "linear": ElevationCurve(
        value=lambda t: t,
        slope=lambda t: 1.0,
    ),
    "convex": ElevationCurve(
        value=lambda t: t * t,
        slope=lambda t: 2.0 * t,
    ),
    "concave": ElevationCurve(
        value=lambda t: 1.0 - (1.0 - t) * (1.0 - t),
        slope=lambda t: 2.0 - 2.0 * t,
    ),
    "s_curve": ElevationCurve(
        value=lambda t: 3.0 * t * t - 2.0 * t * t * t,
        slope=lambda t: 6.0 * t - 6.0 * t * t,
    ),
}


def normalized_curve_position(distances: list[float]) -> list[float]:
    if len(distances) < 2:
        raise ValueError("At least two distance samples are required.")

    normalized = [max(0.0, float(distance)) for distance in distances]
    for idx in range(1, len(normalized)):
        if normalized[idx] < normalized[idx - 1]:
            raise ValueError("Distances must be non-decreasing.")

    total = normalized[-1]
    if total <= 0.0:
        raise ValueError("Total section length must be positive.")

    return [distance / total for distance in normalized]


def evaluate_curve(
    *,
    start_elevation: float,
    end_elevation: float,
    normalized_position: float,
    curve: ElevationCurve,
    total_length: float,
) -> tuple[int, int]:
    t = min(1.0, max(0.0, normalized_position))
    altitude_delta = float(end_elevation) - float(start_elevation)

    altitude = int(round(float(start_elevation) + altitude_delta * curve.value(t)))
    slope_per_dlong = (altitude_delta * curve.slope(t)) / total_length
    grade = int(round(slope_per_dlong * SG_GRADE_SCALE))
    return altitude, grade
