"""Compute LP lateral speed (the field historically named Coriolis).

Lateral speed is forward speed multiplied by d(DLAT)/d(DLONG), with
Papyrus longitudinal speed units of 5280/9 per mph. The closing LP
record is a duplicate track station, not an additional sample.
"""
from __future__ import annotations

import math
from typing import Sequence


_SPEED_UNITS_PER_MPH = 5280.0 / 9.0


def calculate_lp_lateral_speeds(
    records: Sequence[object], *, track_length: float | None = None
) -> list[float]:
    """Return one lateral-speed value per LP record.

    Use the centered lateral-position derivative at interior records and
    periodic neighbors across the start/finish line when track length is
    available. Without a known period, use one-sided endpoint derivatives.
    A terminal record at the track length receives the same geometric
    derivative as the first station, evaluated at its own forward speed.
    """
    count = len(records)
    if count < 2:
        raise ValueError("At least two LP records are required.")
    dlongs = [float(record.dlong) for record in records]
    dlats = [float(record.dlat) for record in records]
    speeds = [float(record.speed_mph) for record in records]
    if not all(math.isfinite(v) for v in (*dlongs, *dlats, *speeds)):
        raise ValueError("LP positions and speeds must be finite.")
    if any(right <= left for left, right in zip(dlongs, dlongs[1:])):
        raise ValueError("LP DLONG stations must be strictly increasing.")

    length = float(track_length) if track_length is not None else 0.0
    periodic = math.isfinite(length) and length > dlongs[0]
    # Real LPs generally carry a redundant final sample at track length.
    terminal = (
        periodic
        and count >= 4
        and abs(dlongs[0]) < 1.0
        and abs(dlongs[-1] - length) < 1.0
    )
    unique_count = count - 1 if terminal else count

    derivatives: list[float] = []
    for i in range(unique_count):
        if unique_count == 2:
            prev_index, next_index = 0, 1
            prev_long, next_long = dlongs[0], dlongs[1]
        elif not periodic and i == 0:
            prev_index, next_index = 0, 1
            prev_long, next_long = dlongs[0], dlongs[1]
        elif not periodic and i == unique_count - 1:
            prev_index, next_index = i - 1, i
            prev_long, next_long = dlongs[i - 1], dlongs[i]
        else:
            prev_index = (i - 1) % unique_count
            next_index = (i + 1) % unique_count
            prev_long = dlongs[prev_index]
            next_long = dlongs[next_index]
            if i == 0:
                prev_long -= length
            if i == unique_count - 1:
                next_long += length

        delta = next_long - prev_long
        if delta <= 0:
            raise ValueError(
                "LP stations are incompatible with track length; "
                "lateral speed cannot be calculated."
            )
        derivatives.append(
            (dlats[next_index] - dlats[prev_index]) / delta
        )

    result = [
        derivative * speed * _SPEED_UNITS_PER_MPH
        for derivative, speed in zip(derivatives, speeds)
    ]
    if terminal:
        result.append(
            derivatives[0] * speeds[-1] * _SPEED_UNITS_PER_MPH
        )
    return result
