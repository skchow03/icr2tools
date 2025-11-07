"""
running_order_overlay.py

Controller: renders RaceState into an OverlayTableWindow.
Applies lap formatting, gaps, best-lap colors, abbreviations, etc.
"""

from typing import Optional, List, Tuple, NamedTuple, Dict
import math
import time
from PyQt5 import QtCore, QtWidgets, QtGui

import logging
log = logging.getLogger(__name__)

from icr2_core.model import RaceState
from icr2timing.analysis.best_laps import BestLapTracker
from icr2timing.analysis.name_utils import compute_compact_names, compute_abbreviations
from icr2timing.analysis.gap_utils import (
    compute_gaps_display,
    compute_intervals_display,
)
from icr2timing.core.config import Config
from icr2timing.overlays.overlay_table_window import OverlayTableWindow
from icr2timing.overlays.base_overlay import BaseOverlay



cfg = Config()
PLAYER_STRUCT_IDX = 1

CAR_STATE_INDEX_QUALIFYING_TIME = 34
CAR_STATE_INDEX_LAPS_LEAD = 36
CAR_STATE_INDEX_LAPS_SINCE_YELLOW = 38
CAR_STATE_INDEX_PIT_RELEASE_TIMER = 98


class OverlayField(NamedTuple):
    label: str
    key: str
    tooltip: str


POSITION_INDICATOR_LABEL = "Δ"


AVAILABLE_FIELDS = [
    OverlayField("Pos", "position", "Calculated 1-based position in running order."),
    OverlayField(
        POSITION_INDICATOR_LABEL,
        "position_indicator",
        "Shows recent position gains/losses (Δ column).",
    ),
    OverlayField("Car#", "car_number", "Driver entry number (not from car data struct)."),
    OverlayField("Driver", "driver", "Driver name (not from car data struct)."),
    OverlayField(
        "Laps",
        "laps",
        "Calculated from total laps minus struct index 32 (laps left).",
    ),
    OverlayField("Gap", "gap", "Calculated gap to leader."),
    OverlayField("Int", "interval", "Calculated interval to car ahead."),
    OverlayField(
        "Last",
        "last",
        "Calculated from lap clock start (index 23) and end (index 22).",
    ),
    OverlayField("Best", "best", "Calculated personal-best lap."),
    OverlayField("BestGap", "best_gap", "Calculated delta to overall best lap."),
    OverlayField("LP", "lp", "Struct index 52 (current LP line)."),
    OverlayField("Fuel", "fuel_laps", "Struct index 35 (fuel laps remaining)."),
    OverlayField("DLONG", "dlong", "Struct index 31 (distance along track)."),
    OverlayField("DLAT", "dlat", "Struct index 11 (distance from track center)."),
    OverlayField("Lead", "laps_lead", "Struct index 36 (laps led)."),
    OverlayField("SinceYL", "laps_since_yellow", "Struct index 38 (laps since last yellow)."),
    OverlayField("PitRel", "pit_release_timer", "Struct index 98 (pit release timer)."),
    OverlayField("Qual", "qualifying_time", "Struct index 34 (qualifying time)."),
]


AVAILABLE_KEYS = {field.key for field in AVAILABLE_FIELDS}
AVAILABLE_FIELDS_BY_KEY = {field.key: field for field in AVAILABLE_FIELDS}


class RunningOrderOverlayTable(QtCore.QObject):
    def __init__(self, font_family=cfg.font_family, font_size=cfg.font_size, n_columns: int = 2):
        super().__init__()
        self._overlay = OverlayTableWindow(font_family, font_size, n_columns=n_columns)
        self._best_tracker = BestLapTracker()
        self._last_state: Optional[RaceState] = None
        self._enabled_fields: List[str] = [field.key for field in AVAILABLE_FIELDS]
        self._use_abbrev: bool = False
        self._sort_by_best: bool = False
        self._display_mode: str = "time"   # or "speed"
        self._track_length: Optional[float] = None
        self._custom_fields: List[Tuple[str, int]] = []
        self._autosize_enabled: bool = True
        self._showing_error: bool = False
        self._last_error_msg: Optional[str] = None

        # NEW: track last resize time for throttling
        self._last_resize_time = QtCore.QTime.currentTime()
        self._resize_throttle_ms = cfg.resize_throttle_ms

        # Track recent position changes for indicator arrows
        self._last_positions: Dict[int, int] = {}
        self._position_changes: Dict[int, Tuple[str, float]] = {}
        self._position_indicator_duration: float = 5.0
        self._indicator_icons: Dict[str, QtGui.QIcon] = {}

        self._rebuild_headers()

    # --- BaseOverlay API ---
    def widget(self):
        return self._overlay

    def _get_or_create_item(self, table: QtWidgets.QTableWidget, row: int, col: int) -> QtWidgets.QTableWidgetItem:
        """Return an existing table item or create one if missing."""
        item = table.item(row, col)
        if item is None:
            item = QtWidgets.QTableWidgetItem("")
            table.setItem(row, col, item)
        return item

    def on_state_updated(self, state: RaceState, update_bests: bool = True):
        if self._showing_error:
            self._rebuild_headers()
            self._showing_error = False
            self._last_error_msg = None

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
        intervals_display = compute_intervals_display(state)

        order = list(state.order)
        now_monotonic = time.monotonic()

        new_positions: Dict[int, int] = {}
        for pos, struct_idx in enumerate(order, start=1):
            if struct_idx is None:
                continue
            new_positions[struct_idx] = pos

        indicator_enabled = "position_indicator" in self._enabled_fields

        if indicator_enabled and self._last_positions:
            for struct_idx, new_pos in new_positions.items():
                prev_pos = self._last_positions.get(struct_idx)
                if prev_pos is None or prev_pos == new_pos:
                    continue
                direction = "gain" if new_pos < prev_pos else "loss"
                self._position_changes[struct_idx] = (direction, now_monotonic)
        elif not indicator_enabled:
            self._position_changes.clear()

        self._last_positions = new_positions

        if indicator_enabled:
            expiry = self._position_indicator_duration
            to_remove = [
                struct_idx
                for struct_idx, (_, ts) in self._position_changes.items()
                if struct_idx not in new_positions or (now_monotonic - ts) > expiry
            ]
            for struct_idx in to_remove:
                self._position_changes.pop(struct_idx, None)
        else:
            self._position_changes.clear()

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
                                from icr2timing.analysis.gap_utils import format_time_diff
                                best_gap_txt = format_time_diff(diff)
                        else:
                            best_gap_txt = ""
                else:
                    best_txt = ""
                    best_gap_txt = ""


                # gap and interval
                gap_txt, gap_color = gaps_display.get(struct_idx, ("", None))
                interval_txt, interval_color = intervals_display.get(
                    struct_idx, ("", None)
                )

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

                laps_since_yellow_val = ""
                if car_state and len(car_state.values) > CAR_STATE_INDEX_LAPS_SINCE_YELLOW:
                    laps_since_yellow_val = car_state.values[CAR_STATE_INDEX_LAPS_SINCE_YELLOW]

                position_indicator_icon = self._get_position_indicator_icon(
                    struct_idx, now_monotonic
                )

                values = {
                    "position": (global_row + 1, None),
                    "position_indicator": ("", None, position_indicator_icon),
                    "car_number": (driver.car_number if driver else "", None),
                    "driver": (names_map.get(struct_idx, driver.name if driver else ""), None),
                    "laps": (car_state.laps_completed if car_state else "", None),
                    "gap": (gap_txt, gap_color),
                    "interval": (interval_txt, interval_color),
                    "last": (last_txt, last_color),
                    "best": (best_txt, None),
                    "best_gap": (best_gap_txt, None),
                    "lp": (getattr(car_state, "current_lp", ""), None) if car_state else ("", None),
                    "fuel_laps": (getattr(car_state, "fuel_laps_remaining", ""), None) if car_state else ("", None),
                    "dlong": (getattr(car_state, "dlong", ""), None) if car_state else ("", None),
                    "dlat": (getattr(car_state, "dlat", ""), None) if car_state else ("", None),
                    "laps_lead": (laps_lead_val, None),
                    "laps_since_yellow": (laps_since_yellow_val, None),
                    "pit_release_timer": (pit_release_txt, None),
                    "qualifying_time": (qualifying_txt, None),
                }

                for lbl, idx in self._custom_fields:
                    val = ""
                    if car_state and 0 <= idx < len(car_state.values):
                        val = car_state.values[idx]
                    values[lbl] = (val, None)

                col = 0

                for key in self._enabled_fields:
                    field = AVAILABLE_FIELDS_BY_KEY.get(key)
                    if not field:
                        continue
                    value_entry = values[field.key]
                    if len(value_entry) == 3:
                        txt, color, icon = value_entry
                    else:
                        txt, color = value_entry
                        icon = None
                    item = self._get_or_create_item(table, row, col)
                    item.setText("" if txt is None else str(txt))
                    if color:
                        item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                    else:
                        item.setForeground(QtGui.QBrush())
                    if icon:
                        item.setIcon(icon)
                    else:
                        item.setIcon(QtGui.QIcon())
                    if struct_idx == PLAYER_STRUCT_IDX:
                        item.setBackground(QtGui.QBrush(QtGui.QColor(cfg.player_row)))
                    else:
                        item.setBackground(QtGui.QBrush())
                    col += 1

                for lbl, idx in self._custom_fields:
                    txt, color = values[lbl]
                    item = self._get_or_create_item(table, row, col)
                    item.setText("" if txt is None else str(txt))
                    if color:
                        item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                    else:
                        item.setForeground(QtGui.QBrush())
                    item.setIcon(QtGui.QIcon())
                    if struct_idx == PLAYER_STRUCT_IDX:
                        item.setBackground(QtGui.QBrush(QtGui.QColor("#444")))
                    else:
                        item.setBackground(QtGui.QBrush())
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
        self._showing_error = True



    # --- Extended API ---
    def reset_pbs(self):
        self._best_tracker.reset()
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def set_enabled_fields(self, fields: List[str]):
        normalized: List[str] = []
        seen = set()
        for key in fields:
            if key == "laps_since_pit":
                key = "laps_since_yellow"
            if key in AVAILABLE_KEYS and key not in seen:
                normalized.append(key)
                seen.add(key)
        self._enabled_fields = normalized
        if "position_indicator" not in self._enabled_fields:
            self._position_changes.clear()
        self._rebuild_headers()
        if self._last_state:
            self.on_state_updated(self._last_state, update_bests=False)

    def set_sort_by_best(self, enabled: bool):
        self._sort_by_best = enabled
        self._rebuild_headers()
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
        base_fields = []
        for key in self._enabled_fields:
            field = AVAILABLE_FIELDS_BY_KEY.get(key)
            if field:
                base_fields.append(field)

        labels = []
        for field in base_fields:
            labels.append((field.label, field.key))
        for lbl, _ in self._custom_fields:
            labels.append((lbl, None))

        for t in self._overlay.tables:
            t.setColumnCount(len(labels))
            header = t.horizontalHeader()
            header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            for i, (base_label, key) in enumerate(labels):
                display_label = base_label
                if key == "best" and self._sort_by_best:
                    display_label = f"{base_label} ▲"
                elif key == "position" and not self._sort_by_best:
                    display_label = f"{base_label} ▲"
                header_item = QtWidgets.QTableWidgetItem(display_label)
                t.setHorizontalHeaderItem(i, header_item)
                width = cfg.col_widths.get(base_label, cfg.col_widths.get("default", 50))
                t.setColumnWidth(i, width)

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

    def set_position_indicator_duration(self, seconds: float):
        seconds = max(1.0, min(15.0, float(seconds)))
        self._position_indicator_duration = seconds

    def get_position_indicator_duration(self) -> float:
        return self._position_indicator_duration

    def _get_position_indicator_icon(self, struct_idx: int, now_monotonic: float) -> Optional[QtGui.QIcon]:
        if "position_indicator" not in self._enabled_fields:
            return None

        change = self._position_changes.get(struct_idx)
        if not change:
            return None
        direction, timestamp = change
        if (now_monotonic - timestamp) > self._position_indicator_duration:
            self._position_changes.pop(struct_idx, None)
            return None
        return self._build_indicator_icon(direction)

    def set_position_indicators_enabled(self, enabled: bool):
        enabled = bool(enabled)
        currently_enabled = "position_indicator" in self._enabled_fields
        if enabled == currently_enabled:
            return

        if enabled:
            fields = list(self._enabled_fields)
            if "position_indicator" not in fields:
                if "position" in fields:
                    insert_at = fields.index("position") + 1
                else:
                    insert_at = len(fields)
                fields.insert(insert_at, "position_indicator")
            self.set_enabled_fields(fields)
        else:
            self.set_enabled_fields(
                [key for key in self._enabled_fields if key != "position_indicator"]
            )

    def are_position_indicators_enabled(self) -> bool:
        return "position_indicator" in self._enabled_fields

    def _build_indicator_icon(self, direction: str) -> QtGui.QIcon:
        if direction in self._indicator_icons:
            return self._indicator_icons[direction]

        size = 12
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        if direction == "gain":
            color = QtGui.QColor(0, 200, 0)
            points = [
                QtCore.QPointF(size / 2, size * 0.15),
                QtCore.QPointF(size * 0.85, size * 0.85),
                QtCore.QPointF(size * 0.15, size * 0.85),
            ]
        else:
            color = QtGui.QColor(220, 40, 40)
            points = [
                QtCore.QPointF(size * 0.15, size * 0.15),
                QtCore.QPointF(size * 0.85, size * 0.15),
                QtCore.QPointF(size / 2, size * 0.85),
            ]
        painter.setBrush(QtGui.QBrush(color))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawPolygon(QtGui.QPolygonF(points))
        painter.end()

        icon = QtGui.QIcon(pixmap)
        self._indicator_icons[direction] = icon
        return icon

# Register class as a virtual subclass of BaseOverlay
BaseOverlay.register(RunningOrderOverlayTable)
