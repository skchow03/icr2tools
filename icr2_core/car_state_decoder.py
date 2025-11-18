"""Decode the 0x214 car-state structure emitted by the game."""
from __future__ import annotations

from typing import Dict, List

from icr2_core.model import CarState
from icr2timing.core.config import Config


def _read_u32(blob: bytes, offset: int) -> int:
    chunk = blob[offset:offset + 4]
    if len(chunk) < 4:
        return 0
    return int.from_bytes(chunk, "little", signed=False)


def _read_i32(blob: bytes, offset: int) -> int:
    chunk = blob[offset:offset + 4]
    if len(chunk) < 4:
        return 0
    return int.from_bytes(chunk, "little", signed=True)


SENTINEL_UNSIGNED = 0xFF000000
SENTINEL_SIGNED = -16777216


def decode_car_states(raw_blob: bytes, cfg: Config, total_laps: int) -> Dict[int, CarState]:
    """Return ``struct_index -> CarState`` decoded from ``raw_blob``."""

    car_state_size = cfg.car_state_size
    if car_state_size <= 0:
        return {}

    raw_count = len(raw_blob) // car_state_size
    out: Dict[int, CarState] = {}

    for struct_idx in range(raw_count):
        base = struct_idx * car_state_size

        laps_left = _read_u32(raw_blob, base + cfg.field_laps_left)
        laps_completed = total_laps - laps_left
        if laps_completed < 0:
            laps_completed = 0
        elif laps_completed > total_laps:
            laps_completed = total_laps

        start_clock = _read_u32(raw_blob, base + cfg.field_lap_clock_start)
        signed_start = _read_i32(raw_blob, base + cfg.field_lap_clock_start)
        if start_clock == SENTINEL_UNSIGNED or signed_start == SENTINEL_SIGNED:
            start_clock = None

        end_clock = _read_u32(raw_blob, base + cfg.field_lap_clock_end)
        signed_end = _read_i32(raw_blob, base + cfg.field_lap_clock_end)
        if end_clock == SENTINEL_UNSIGNED or signed_end == SENTINEL_SIGNED:
            end_clock = None

        if start_clock is None or end_clock is None:
            last_lap_ms = 0
            last_lap_valid = False
        else:
            last_lap_ms = (end_clock - start_clock) & 0xFFFFFFFF
            last_lap_valid = True

        laps_down = _read_u32(raw_blob, base + cfg.field_laps_down)
        if laps_down > 100:
            laps_down = 0

        current_lp = _read_u32(raw_blob, base + cfg.current_lp)
        fuel_laps_remaining = _read_u32(raw_blob, base + cfg.fuel_laps_remaining)
        car_status = _read_u32(raw_blob, base + cfg.car_status)
        if car_status > 16:
            car_status = 0

        dlat = _read_i32(raw_blob, base + cfg.dlat)
        dlong = _read_i32(raw_blob, base + cfg.dlong)

        values: List[int] = [
            _read_i32(raw_blob, base + i * 4)
            for i in range(car_state_size // 4)
        ]

        out[struct_idx] = CarState(
            struct_index=struct_idx,
            laps_left=laps_left,
            laps_completed=laps_completed,
            last_lap_ms=last_lap_ms,
            last_lap_valid=last_lap_valid,
            laps_down=laps_down,
            lap_end_clock=end_clock,
            lap_start_clock=start_clock,
            car_status=car_status,
            current_lp=current_lp,
            fuel_laps_remaining=fuel_laps_remaining,
            dlat=dlat,
            dlong=dlong,
            values=values,
        )

    return out
