from __future__ import annotations

import math


def _quantize_directional_step(raw_delta: float) -> int:
    if raw_delta >= 1.0:
        return math.floor(raw_delta)
    if raw_delta <= -1.0:
        return math.ceil(raw_delta)
    return 0


def quantize_trackside_drag_delta(
    delta_x: float,
    delta_y: float,
    remainder: tuple[float, float],
) -> tuple[int, int, tuple[float, float]]:
    raw_delta_x = float(delta_x) + float(remainder[0])
    raw_delta_y = float(delta_y) + float(remainder[1])
    step_x = _quantize_directional_step(raw_delta_x)
    step_y = _quantize_directional_step(raw_delta_y)
    return step_x, step_y, (raw_delta_x - step_x, raw_delta_y - step_y)
