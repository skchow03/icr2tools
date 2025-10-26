"""
best_laps.py

Tracks personal bests and global bests across drivers.
Formats lap times into text + color for overlay.
"""

from typing import Dict, Optional
from core.config import Config

cfg = Config()   

class BestLapTracker:
    def __init__(self):
        self.personal_bests: Dict[int, int] = {}  # struct_idx -> ms
        self.global_best_ms: Optional[int] = None

    def reset(self):
        self.personal_bests.clear()
        self.global_best_ms = None

    def update_from_snapshot(self, state):
        for idx, car_state in state.car_states.items():
            if not car_state.last_lap_valid:
                continue
            ms = car_state.last_lap_ms
            if ms <= 0:
                continue

            # personal best
            prev = self.personal_bests.get(idx)
            if prev is None or ms < prev:
                self.personal_bests[idx] = ms

            # global best
            if self.global_best_ms is None or ms < self.global_best_ms:
                self.global_best_ms = ms

    def get_personal_best_ms(self, struct_idx: int) -> Optional[int]:
        return self.personal_bests.get(struct_idx)

    def format_ms(self, ms: int) -> str:
        # Format milliseconds into M:SS.sss
        total_seconds = ms / 1000.0
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:06.3f}"

    def classify_last_lap(
        self,
        struct_idx: int,
        last_ms: int,
        valid: bool,
        display_mode: str = "time",
        track_length: Optional[float] = None,
    ):
        """
        Return (text, color) for the last lap.
        - Purple (#a0f) if it's the global best
        - Green (#0f0) if it's the driver's personal best
        - White (None) otherwise
        """
        if not valid or not last_ms:
            return "", None

        if display_mode == "speed" and track_length:
            txt = f"{track_length * 3_600_000 / last_ms:.3f}"
        else:
            txt = self.format_ms(last_ms)

        pb_ms = self.get_personal_best_ms(struct_idx)
        if pb_ms and last_ms == pb_ms:
            if self.global_best_ms and last_ms == self.global_best_ms:
                return txt, cfg.best_global
            return txt, cfg.best_personal


        return txt, None
