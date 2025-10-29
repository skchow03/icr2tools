"""
model.py

Immutable data models representing drivers, car state, and the overall race state.
"""

from dataclasses import dataclass
from typing import Dict, Optional, List


@dataclass(frozen=True)
class Driver:
    """
    Single driver information keyed by struct index.
    - struct_index: index of the driver's struct in the car-state array
    - name: escaped display name (may be empty)
    - car_number: optional integer (None if missing)
    """
    struct_index: int
    name: str
    car_number: Optional[int]


@dataclass(frozen=True)
class CarState:
    """
    Per-struct car runtime state.
    - struct_index: struct index
    - laps_left: value read from memory (unsigned)
    - laps_completed: computed (total_laps - laps_left, clamped)
    - last_lap_ms: last lap time in milliseconds (0 if not available)
    - last_lap_valid: whether the last lap time is valid (not a sentinel)
    - laps_down: number of laps down from the leader (0 if on lead lap)
    - lap_end_clock: clock value at end of last completed lap (field 22)
    - lap_start_clock: clock value at start of current lap (field 23)
    - car_status: retirement reason (0 = running, 1+ = retired with reason)
    - values: full raw 0x214 block as signed 32-bit integers
    """
    struct_index: int
    laps_left: int
    laps_completed: int
    last_lap_ms: int
    last_lap_valid: bool
    laps_down: int
    lap_end_clock: Optional[int]
    lap_start_clock: Optional[int]
    car_status: int
    current_lp: int
    fuel_laps_remaining: int
    dlat: int
    dlong: int
    values: List[int]   # NEW: all 133 4-byte signed ints from the car state block


@dataclass(frozen=True)
class RaceState:
    """
    Snapshot of the race state used by the UI.
    - raw_count: number of slots present in memory (includes pace car)
    - display_count: number of racing cars shown (raw_count - 1)
    - total_laps: required total laps value
    - order: list of struct indices in running order (pace car excluded), length == display_count
    - drivers: mapping struct_index -> Driver for all struct indices 0..raw_count-1
    - car_states: mapping struct_index -> CarState for all struct indices 0..raw_count-1
    """
    raw_count: int
    display_count: int
    total_laps: int
    order: List[Optional[int]]
    drivers: Dict[int, Driver]
    car_states: Dict[int, CarState]
    track_length: float = 0.0   # miles, derived from memory
    track_name: str = ""   # e.g. "INDY500"
    session_timer_ms: Optional[int] = None  # session-wide clock in milliseconds

