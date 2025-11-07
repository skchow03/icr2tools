"""
gap_utils.py

Helpers for computing gap/interval/retirement display strings.
Now returns plain strings and optional color hints instead of HTML.
"""

from typing import Dict, Optional, Tuple

from icr2_core.model import RaceState, CarState
from icr2timing.core.config import Config


cfg = Config() 

# Retirement reason mapping
RETIREMENT_REASONS = {
    0: None,
    1: "Accident",
    2: "Engine",
    3: "Electrical",
    4: "Gearbox",
    5: "Oil pump",
    6: "Wheel Bearing",
    7: "Header",
    8: "Fuel pump",
    9: "Suspension",
    10: "Fire",
    11: "Water pump",
    12: "Mechanical",
    13: "Wastegate",
    14: "Halfshaft",
    15: "Turbo",
    16: "DNF"
}

COLOR_PITTING = cfg.pitting
COLOR_RETIRED = cfg.retired


def format_time_diff(diff_ms: int) -> str:
    if diff_ms == 0:
        return ""
    total_seconds = abs(diff_ms) / 1000.0
    sign = "+" if diff_ms > 0 else "-"
    if total_seconds < 60:
        return f"{sign}{total_seconds:.3f}"
    else:
        minutes = int(total_seconds // 60)
        seconds = total_seconds - (minutes * 60)
        return f"{sign}{minutes}:{seconds:06.3f}"


def get_retirement_reason(car_status: int) -> Optional[str]:
    return RETIREMENT_REASONS.get(car_status)


def compute_gaps_display(state: RaceState) -> Dict[int, Tuple[str, Optional[str]]]:
    """
    Return mapping struct_idx -> (text, color_hex).
    """
    gaps: Dict[int, Tuple[str, Optional[str]]] = {}

    try:
        leader_idx = None
        leader_state: Optional[CarState] = None
        for idx in state.order:
            if idx is not None:
                car_state = state.car_states.get(idx)
                if car_state and car_state.car_status == 0:
                    leader_idx = idx
                    leader_state = car_state
                    break

        if leader_idx is None or leader_state is None:
            return {idx: ("", None) for idx in state.car_states.keys()}

        leader_laps = leader_state.laps_completed
        leader_end_clock = leader_state.lap_end_clock
        leader_start_clock = leader_state.lap_start_clock

        for struct_idx, car_state in state.car_states.items():
            if not car_state:
                gaps[struct_idx] = ("", None)
                continue

            if getattr(car_state, "current_lp", None) == 3 and car_state.car_status == 0:
                gaps[struct_idx] = ("Pitting", COLOR_PITTING)
                continue

            retirement_reason = get_retirement_reason(car_state.car_status)
            if retirement_reason:
                gaps[struct_idx] = (retirement_reason, COLOR_RETIRED)
                continue

            if struct_idx == leader_idx:
                gaps[struct_idx] = ("", None)
                continue

            if car_state.laps_down > 0:
                gaps[struct_idx] = (f"-{car_state.laps_down}L", None)
                continue

            if car_state.laps_completed == leader_laps:
                if car_state.lap_end_clock is not None and leader_end_clock is not None:
                    diff_clock = (car_state.lap_end_clock - leader_end_clock) & 0xFFFFFFFF
                    if diff_clock > 0x7FFFFFFF:
                        diff_clock -= 0x100000000
                    gaps[struct_idx] = (format_time_diff(diff_clock), None)
                else:
                    gaps[struct_idx] = ("", None)
            elif car_state.laps_completed == leader_laps - 1:
                if car_state.lap_end_clock is not None and leader_start_clock is not None:
                    diff_clock = (car_state.lap_end_clock - leader_start_clock) & 0xFFFFFFFF
                    if diff_clock > 0x7FFFFFFF:
                        diff_clock -= 0x100000000
                    gaps[struct_idx] = (format_time_diff(diff_clock), None)
                else:
                    gaps[struct_idx] = ("", None)
            else:
                gaps[struct_idx] = ("", None)

        return gaps

    except Exception as e:
        print(f"[gap_utils] Error in compute_gaps_display: {e}")
        return {idx: ("", None) for idx in getattr(state, "car_states", {}).keys()}


def compute_intervals_display(state: RaceState, _last_intervals_cache: dict = {}) -> Dict[int, Tuple[str, Optional[str]]]:
    """
    Return mapping struct_idx -> (interval_to_car_ahead_text, color).
    Now holds each car's previous interval until that car crosses the line (laps_completed changes),
    preventing flicker between -1L and time gaps as cars straddle the finish line.
    """
    intervals: Dict[int, Tuple[str, Optional[str]]] = {}
    prev_active: Optional[CarState] = None

    for struct_idx in state.order:
        car = state.car_states.get(struct_idx)
        if not car:
            continue

        text, color = "", None

        # reuse cached value if we haven't finished a new lap yet
        last_entry = _last_intervals_cache.get(struct_idx)
        last_lap = last_entry[2] if last_entry else None
        if last_lap is not None and last_lap == car.laps_completed:
            # keep showing old interval text and color
            intervals[struct_idx] = (last_entry[0], last_entry[1])
            if car.car_status == 0 and getattr(car, "current_lp", 0) != 3:
                prev_active = car
            continue

        # pitting/retired logic
        if getattr(car, "current_lp", 0) == 3 and car.car_status == 0:
            text, color = "Pitting", COLOR_PITTING
        else:
            retired = get_retirement_reason(car.car_status)
            if retired:
                text, color = retired, COLOR_RETIRED
            elif prev_active is not None:
                ahead = prev_active
                lap_diff = ahead.laps_completed - car.laps_completed

                if lap_diff == 0:
                    if car.lap_end_clock is not None and ahead.lap_end_clock is not None:
                        diff = (car.lap_end_clock - ahead.lap_end_clock) & 0xFFFFFFFF
                        if diff > 0x7FFFFFFF:
                            diff -= 0x100000000
                        if diff < 0:
                            diff = 0
                        text = format_time_diff(diff)
                elif lap_diff > 0:
                    text = f"-{lap_diff}L"

        intervals[struct_idx] = (text, color)
        # store for next frame (text, color, laps_completed)
        _last_intervals_cache[struct_idx] = (text, color, car.laps_completed)

        # update ahead reference
        if car.car_status == 0 and getattr(car, "current_lp", 0) != 3:
            prev_active = car

    return intervals
