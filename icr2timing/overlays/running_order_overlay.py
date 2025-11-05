"""
running_order_overlay.py

Controller: renders RaceState into an OverlayTableWindow.
Applies lap formatting, gaps, best-lap colors, abbreviations, etc.
"""

from typing import Optional, List, Tuple
import math
from PyQt5 import QtCore, QtWidgets, QtGui

import logging
log = logging.getLogger(__name__)

from icr2_core.model import RaceState
from analysis.best_laps import BestLapTracker
from analysis.name_utils import compute_compact_names, compute_abbreviations
from analysis.gap_utils import compute_gaps_display
from core.config import Config
from overlays.overlay_table_window import OverlayTableWindow
from overlays.base_overlay import BaseOverlay



cfg = Config()
PLAYER_STRUCT_IDX = 1

CAR_STATE_INDEX_QUALIFYING_TIME = 34
CAR_STATE_INDEX_LAPS_LEAD = 36
CAR_STATE_INDEX_LAPS_SINCE_PIT = 38
CAR_STATE_INDEX_PIT_RELEASE_TIMER = 98


AVAILABLE_FIELDS = [
    ("Pos", "position"),
    ("Car#", "car_number"),
    ("Driver", "driver"),
    ("Laps", "laps"),
    ("Gap", "gap"),
    ("Last", "last"),
    ("Best", "best"),
    ("BestGap", "best_gap"),
    ("LP", "lp"),
    ("Fuel", "fuel_laps"),
    ("DLONG", "dlong"),
    ("DLAT", "dlat"),
    ("Lead", "laps_lead"),
    ("SincePit", "laps_since_pit"),
    ("PitRel", "pit_release_timer"),
    ("Qual", "qualifying_time"),
]


class RunningOrderOverlayTable(QtCore.QObject):
    def __init__(self, font_family=cfg.font_family, font_size=cfg.font_size, n_columns: int = 2):
        super().__init__()
        self._overlay = OverlayTableWindow(font_family, font_size, n_columns=n_columns)
        self._best_tracker = BestLapTracker()
        self._last_state: Optional[RaceState] = None
        self._enabled_fields: List[str] = [k for _, k in AVAILABLE_FIELDS]
        self._use_abbrev: bool = False
        self._sort_by_best: bool = False
        self._display_mode: str = "time"   # or "speed"
        self._track_length: Optional[float] = None
        self._custom_fields: List[Tuple[str, int]] = []
        self._autosize_enabled: bool = True

        # NEW: track last resize time for throttling
        self._last_resize_time = QtCore.QTime.currentTime()
        self._resize_throttle_ms = cfg.resize_throttle_ms

        self._rebuild_headers()

    # --- BaseOverlay API ---
    def widget(self):
        return self._overlay

    def on_state_updated(self, state: RaceState, update_bests: bool = True):
        self._last_state = state
        self._track_length = state.track_length or None
        if update_bests:
            self._best_tracker.update_from_snapshot(state)

        names_map = (
            compute_abbreviations(state.drivers)
            if self._use_abbrev
            else compute_compact_names(state)
        )
        gaps_display = compute_gaps_display(state)

        order = list(state.order)

        # --- Safe sort by best lap ---
        if self._sort_by_best:
            def sort_key(idx):
                if idx is None:
                    return float("inf")
                ms = self._best_tracker.get_personal_best_ms(idx)
                return ms if ms is not None else float("inf")

            order.sort(key=sort_key)

            # Ensure player car stays visible, even with no PB
            if PLAYER_STRUCT_IDX not in order:
                order.insert(0, PLAYER_STRUCT_IDX)

        rows_per_table = math.ceil(len(order) / self._overlay.n_columns)
        chunks = [order[i * rows_per_table:(i + 1) * rows_per_table]
                  for i in range(self._overlay.n_columns)]

        for table_idx, chunk in enumerate(chunks):
            table = self._overlay.tables[table_idx]
            table.setRowCount(len(chunk))
            for row, struct_idx in enumerate(chunk):
                if struct_idx is None:
                    continue
                driver = state.drivers.get(struct_idx)
                car_state = state.car_states.get(struct_idx)

                # last lap with color (PB = green, overall best = purple)
                last_ms = int(car_state.last_lap_ms) if car_state and car_state.last_lap_valid else 0
                last_txt, last_color = self._best_tracker.classify_last_lap(
                    struct_idx,
                    last_ms,
                    getattr(car_state, "last_lap_valid", False),
                    display_mode=self._display_mode,
                    track_length=self._track_length,
                )

                # best lap (plain text only, no color)
                best_ms = self._best_tracker.get_personal_best_ms(struct_idx)
                if best_ms:
                    if self._display_mode == "speed" and self._track_length:
                        best_txt = f"{self._track_length * 3_600_000 / best_ms:.3f}"

                        # BestGap in speed (mph difference to leader’s best)
                        if self._best_tracker.global_best_ms and self._track_length:
                            global_speed = self._track_length * 3_600_000 / self._best_tracker.global_best_ms
                            my_speed = self._track_length * 3_600_000 / best_ms
                            diff = my_speed - global_speed
                            if abs(diff) < 0.001:
                                best_gap_txt = ""
                            else:
                                # format with sign, slower = negative
                                best_gap_txt = f"{diff:+.3f}"
                        else:
                            best_gap_txt = ""

                    else:
                        best_txt = self._best_tracker.format_ms(best_ms)

                        # NEW: BestGap in time (ms difference)
                        if self._best_tracker.global_best_ms is not None:
                            diff = best_ms - self._best_tracker.global_best_ms
                            if diff <= 0:
                                best_gap_txt = ""
                            else:
                                from analysis.gap_utils import format_time_diff
                                best_gap_txt = format_time_diff(diff)
                        else:
                            best_gap_txt = ""
                else:
                    best_txt = ""
                    best_gap_txt = ""


                # gap
                gap_txt, gap_color = gaps_display.get(struct_idx, ("", None))

                global_row = row + (table_idx * rows_per_table)

                pit_release_txt = ""
                if car_state and len(car_state.values) > CAR_STATE_INDEX_PIT_RELEASE_TIMER:
                    raw_pit_release = car_state.values[CAR_STATE_INDEX_PIT_RELEASE_TIMER]
                    if raw_pit_release != 0:
                        pit_release_txt = str(raw_pit_release)

                qualifying_txt = ""
                if car_state and len(car_state.values) > CAR_STATE_INDEX_QUALIFYING_TIME:
                    raw_qual = car_state.values[CAR_STATE_INDEX_QUALIFYING_TIME]
                    if raw_qual > 0:
                        if self._display_mode == "speed" and self._track_length:
                            speed = self._track_length * 3_600_000 / raw_qual
                            qualifying_txt = f"{speed:.3f}"
                        else:
                            qualifying_txt = self._best_tracker.format_ms(raw_qual)
                    elif raw_qual < 0:
                        qualifying_txt = str(raw_qual)

                laps_lead_val = ""
                if car_state and len(car_state.values) > CAR_STATE_INDEX_LAPS_LEAD:
                    laps_lead_val = car_state.values[CAR_STATE_INDEX_LAPS_LEAD]

                laps_since_pit_val = ""
                if car_state and len(car_state.values) > CAR_STATE_INDEX_LAPS_SINCE_PIT:
                    laps_since_pit_val = car_state.values[CAR_STATE_INDEX_LAPS_SINCE_PIT]

                values = {
                    "position": (global_row + 1, None),
                    "car_number": (driver.car_number if driver else "", None),
                    "driver": (names_map.get(struct_idx, driver.name if driver else ""), None),
                    "laps": (car_state.laps_completed if car_state else "", None),
                    "gap": (gap_txt, gap_color),
                    "last": (last_txt, last_color),
                    "best": (best_txt, None),
                    "best_gap": (best_gap_txt, None),
                    "lp": (getattr(car_state, "current_lp", ""), None) if car_state else ("", None),
                    "fuel_laps": (getattr(car_state, "fuel_laps_remaining", ""), None) if car_state else ("", None),
                    "dlong": (getattr(car_state, "dlong", ""), None) if car_state else ("", None),
                    "dlat": (getattr(car_state, "dlat", ""), None) if car_state else ("", None),
                    "laps_lead": (laps_lead_val, None),
                    "laps_since_pit": (laps_since_pit_val, None),
                    "pit_release_timer": (pit_release_txt, None),
                    "qualifying_time": (qualifying_txt, None),
                }

                for lbl, idx in self._custom_fields:
                    val = ""
                    if car_state and 0 <= idx < len(car_state.values):
                        val = car_state.values[idx]
                    values[lbl] = (val, None)

                col = 0
                for lbl, key in AVAILABLE_FIELDS:
                    if key not in self._enabled_fields:
                        continue
                    txt, color = values[key]
                    item = QtWidgets.QTableWidgetItem(str(txt))
                    if color:
                        item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                    if struct_idx == PLAYER_STRUCT_IDX:
                        item.setBackground(QtGui.QBrush(QtGui.QColor(cfg.player_row)))

                    table.setItem(row, col, item)
                    col += 1

                for lbl, _ in self._custom_fields:
                    txt, color = values[lbl]
                    item = QtWidgets.QTableWidgetItem(str(txt))
                    if struct_idx == PLAYER_STRUCT_IDX:
                        item.setBackground(QtGui.QBrush(QtGui.QColor("#444")))
                    table.setItem(row, col, item)
                    col += 1

        # --- Auto-size logic with throttling ---
        if self._autosize_enabled:
            now = QtCore.QTime.currentTime()
            if self._last_resize_time.msecsTo(now) >= self._resize_throttle_ms:
                # Use full content-based sizing (like the manual button)
                self._overlay.autosize_columns_to_contents()
                self._last_resize_time = now


    def on_error(self, msg: str):
        # Log each distinct message only once
        if getattr(self, "_last_error_msg", None) != msg:
            log.error(f"[RunningOrderOverlay] Error occurred: {msg}")
            self._last_error_msg = msg
        for t in self._overlay.tables:
            t.setRowCount(1)
            t.setColumnCount(1)
            t.setHorizontalHeaderLabels(["Error"])
            t.setItem(0, 0, QtWidgets.QTableWidgetItem(msg))
        self._overlay.resize_to_fit()



    # --- Extended API ---
    def reset_pbs(self):
        self._best_tracker.reset()
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def set_enabled_fields(self, fields: List[str]):
        self._enabled_fields = fields
        self._rebuild_headers()
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def set_sort_by_best(self, enabled: bool):
        self._sort_by_best = enabled
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def set_use_abbreviations(self, enabled: bool):
        self._use_abbrev = enabled
        self._rebuild_headers()
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def set_display_mode(self, mode: str):
        self._display_mode = mode
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def set_track_length(self, miles: Optional[float]):
        self._track_length = miles
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def add_custom_field(self, label: str, index: int):
        if not any(lbl == label for lbl, _ in self._custom_fields):
            self._custom_fields.append((label, index))
            self._rebuild_headers()
            if self._last_state:
                self.on_state_updated(self._last_state, update_bests=False)

    def remove_custom_field(self, label: str):
        self._custom_fields = [(lbl, idx) for lbl, idx in self._custom_fields if lbl != label]
        self._rebuild_headers()
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def _rebuild_headers(self):
        labels = [lbl for lbl, key in AVAILABLE_FIELDS if key in self._enabled_fields]
        labels.extend(lbl for lbl, _ in self._custom_fields)  # add customs
        for t in self._overlay.tables:
            t.setColumnCount(len(labels))
            t.setHorizontalHeaderLabels(labels)
            header = t.horizontalHeader()
            header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            for i, lbl in enumerate(labels):
                if lbl in cfg.col_widths:
                    w = cfg.col_widths[lbl]
                else:
                    w = cfg.col_widths["default"]
                t.setColumnWidth(i, w)

    def set_autosize_enabled(self, enabled: bool):
        """Toggle automatic window resizing after each update."""
        self._autosize_enabled = enabled
        if enabled:
            # Do one immediate fit so the user sees the effect right away
            self._overlay.resize_to_fit()
            self._last_resize_time = QtCore.QTime.currentTime()

    def resize_columns_now(self):
        """One-shot: autosize columns to contents and resize the window."""
        self._overlay.autosize_columns_to_contents()

    def get_enabled_fields(self) -> List[str]:
        """Return the active overlay field keys in order."""
        return list(self._enabled_fields)

# Register class as a virtual subclass of BaseOverlay
BaseOverlay.register(RunningOrderOverlayTable)
