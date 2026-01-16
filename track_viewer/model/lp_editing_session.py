"""Domain object for AI line (LP) editing state and mutations."""
from __future__ import annotations

from dataclasses import replace
from enum import Enum, auto
from icr2_core.lp.loader import papy_speed_to_mph
from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.model.track_preview_model import TrackPreviewModel


class LPChange(Enum):
    DATA = auto()
    SELECTION = auto()
    VISIBILITY = auto()


class LPEditingSession:
    """Pure-Python session for LP editing state and mutations."""

    def __init__(self, model: TrackPreviewModel) -> None:
        self._model = model
        self._active_lp_line = "center-line"
        self._selected_lp_line: str | None = None
        self._selected_lp_index: int | None = None
        self._lp_shortcut_active = False
        self._lp_dlat_step = 0
        self._lp_editing_tab_active = False
        self._replay_generation = 0

    @property
    def active_lp_line(self) -> str:
        return self._active_lp_line

    @property
    def selected_lp_line(self) -> str | None:
        return self._selected_lp_line

    @property
    def selected_lp_index(self) -> int | None:
        return self._selected_lp_index

    def selected_lp_record(self) -> tuple[str, int] | None:
        if self._selected_lp_line is None or self._selected_lp_index is None:
            return None
        return self._selected_lp_line, self._selected_lp_index

    @property
    def lp_shortcut_active(self) -> bool:
        return self._lp_shortcut_active

    @property
    def lp_dlat_step(self) -> int:
        return self._lp_dlat_step

    @property
    def lp_editing_tab_active(self) -> bool:
        return self._lp_editing_tab_active

    @property
    def replay_generation(self) -> int:
        return self._replay_generation

    def reset(self) -> None:
        self._active_lp_line = "center-line"
        self._selected_lp_line = None
        self._selected_lp_index = None
        self._lp_shortcut_active = False
        self._lp_dlat_step = 0
        self._lp_editing_tab_active = False
        self._replay_generation = 0

    def sync_available_lines(self) -> set[LPChange]:
        changes: set[LPChange] = set()
        if self._active_lp_line not in {"center-line", *self._model.available_lp_files}:
            self._active_lp_line = "center-line"
            changes.add(LPChange.SELECTION)
        if (
            self._selected_lp_line is not None
            and self._selected_lp_line not in self._model.available_lp_files
        ):
            self._selected_lp_line = None
            self._selected_lp_index = None
            changes.add(LPChange.SELECTION)
        return changes

    def set_active_lp_line(self, name: str) -> set[LPChange]:
        target = "center-line"
        if name in self._model.available_lp_files:
            target = name
        elif name == "center-line":
            target = name
        if target == self._active_lp_line:
            return set()
        self._active_lp_line = target
        self._selected_lp_line = None
        self._selected_lp_index = None
        if target != "center-line":
            self._model.ai_line_records(target)
        return {LPChange.SELECTION}

    def set_selected_lp_record(
        self, name: str | None, index: int | None
    ) -> set[LPChange]:
        if name is None or index is None:
            if self._selected_lp_line is None and self._selected_lp_index is None:
                return set()
            self._selected_lp_line = None
            self._selected_lp_index = None
            return {LPChange.SELECTION}
        if name not in self._model.available_lp_files:
            return set()
        records = self._model.ai_line_records(name)
        if index < 0 or index >= len(records):
            return set()
        if self._selected_lp_line == name and self._selected_lp_index == index:
            return set()
        self._selected_lp_line = name
        self._selected_lp_index = index
        return {LPChange.SELECTION}

    def set_lp_shortcut_active(self, active: bool) -> set[LPChange]:
        active = bool(active)
        if self._lp_shortcut_active == active:
            return set()
        self._lp_shortcut_active = active
        return {LPChange.VISIBILITY}

    def set_lp_editing_tab_active(self, active: bool) -> set[LPChange]:
        active = bool(active)
        if self._lp_editing_tab_active == active:
            return set()
        self._lp_editing_tab_active = active
        return {LPChange.VISIBILITY}

    def set_lp_dlat_step(self, step: int) -> set[LPChange]:
        clamped = max(0, int(step))
        if self._lp_dlat_step == clamped:
            return set()
        self._lp_dlat_step = clamped
        if self._lp_shortcut_active:
            return {LPChange.VISIBILITY}
        return set()

    def should_track_hover(self) -> bool:
        if self._active_lp_line == "center-line":
            return False
        return self._active_lp_line in self._model.visible_lp_files

    def records(self, name: str) -> list[LpPoint]:
        return [replace(record) for record in self._model.ai_line_records(name)]

    def record_count(self, name: str) -> int:
        return len(self._model.ai_line_records(name))

    def record_snapshot(self, name: str, index: int) -> LpPoint | None:
        records = self._model.ai_line_records(name)
        if index < 0 or index >= len(records):
            return None
        return replace(records[index])

    def step_selection(self, delta: int) -> set[LPChange]:
        if self._selected_lp_line is None or self._selected_lp_index is None:
            return set()
        records = self._model.ai_line_records(self._selected_lp_line)
        if not records:
            return set()
        target = max(0, min(len(records) - 1, self._selected_lp_index + delta))
        return self.set_selected_lp_record(self._selected_lp_line, target)

    def adjust_selected_dlat(self, delta: int) -> set[LPChange]:
        selected = self.selected_lp_record()
        if selected is None:
            return set()
        lp_name, index = selected
        record = self._record_for_edit(lp_name, index)
        if record is None:
            return set()
        record.dlat = float(record.dlat) + float(delta)
        if self._model.update_lp_record(lp_name, index):
            return {LPChange.DATA}
        return set()

    def adjust_selected_speed(self, delta_mph: float) -> set[LPChange]:
        selected = self.selected_lp_record()
        if selected is None:
            return set()
        lp_name, index = selected
        record = self._record_for_edit(lp_name, index)
        if record is None:
            return set()
        record.speed_mph = record.speed_mph + delta_mph
        record.speed_raw = int(round(record.speed_mph * (5280 / 9)))
        if self._model.update_lp_record(lp_name, index):
            return {LPChange.DATA}
        return set()

    def copy_selected_fields(self, delta: int) -> set[LPChange]:
        selected = self.selected_lp_record()
        if selected is None:
            return set()
        lp_name, index = selected
        records = self._model.ai_line_records(lp_name)
        if not records:
            return set()
        target = max(0, min(len(records) - 1, index + delta))
        if target == index:
            return set()
        source_record = records[index]
        target_record = records[target]
        target_record.dlat = source_record.dlat
        target_record.speed_raw = source_record.speed_raw
        target_record.speed_mph = source_record.speed_mph
        target_record.lateral_speed = source_record.lateral_speed
        changes: set[LPChange] = set()
        if self._model.update_lp_record(lp_name, target):
            changes.add(LPChange.DATA)
        changes.update(self.set_selected_lp_record(lp_name, target))
        return changes

    def update_record_dlat(
        self, lp_name: str, index: int, dlat_value: float
    ) -> set[LPChange]:
        record = self._record_for_edit(lp_name, index)
        if record is None:
            return set()
        record.dlat = float(dlat_value)
        if self._model.update_lp_record(lp_name, index):
            return {LPChange.DATA}
        return set()

    def update_record_speed(
        self, lp_name: str, index: int, value: float, *, raw_mode: bool
    ) -> set[LPChange]:
        record = self._record_for_edit(lp_name, index)
        if record is None:
            return set()
        if raw_mode:
            speed_raw = int(round(value))
            record.speed_raw = speed_raw
            record.speed_mph = papy_speed_to_mph(speed_raw)
        else:
            record.speed_mph = float(value)
            record.speed_raw = int(round(record.speed_mph * (5280 / 9)))
        if self._model.update_lp_record(lp_name, index):
            return {LPChange.DATA}
        return set()

    def update_record_lateral_speed(
        self, lp_name: str, index: int, value: float
    ) -> set[LPChange]:
        record = self._record_for_edit(lp_name, index)
        if record is None:
            return set()
        record.lateral_speed = float(value)
        if self._model.update_lp_record(lp_name, index):
            return {LPChange.DATA}
        return set()

    def recalculate_lateral_speeds(self, lp_name: str) -> set[LPChange]:
        records = self._model.ai_line_records(lp_name)
        if len(records) < 3:
            return set()
        total_records = len(records)
        recalculated = [0.0] * total_records
        lateral_factor = 31680000 / 54000
        for index in range(total_records):
            prev_record = records[(index - 1) % total_records]
            next_record = records[(index + 1) % total_records]
            record = records[index]
            dlong_delta = next_record.dlong - prev_record.dlong
            if dlong_delta == 0:
                lateral_speed = 0.0
            else:
                lateral_speed = (
                    (next_record.dlat - prev_record.dlat)
                    / dlong_delta
                    * (record.speed_mph * lateral_factor)
                )
            recalculated[(index - 2) % total_records] = lateral_speed
        for index, lateral_speed in enumerate(recalculated):
            records[index].lateral_speed = lateral_speed
        self._model.mark_lp_line_dirty(lp_name)
        return {LPChange.DATA}

    def is_dirty(self, lp_name: str) -> bool:
        return self._model.lp_line_dirty(lp_name)

    def mark_dirty(self, lp_name: str) -> set[LPChange]:
        before = self._model.lp_line_dirty(lp_name)
        self._model.mark_lp_line_dirty(lp_name)
        if before != self._model.lp_line_dirty(lp_name):
            return {LPChange.DATA}
        return set()

    def generate_lp_line_from_replay(
        self,
        lp_name: str,
        rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[bool, str, set[LPChange]]:
        success, message = self._model.generate_lp_line_from_replay(
            lp_name, rpy, car_id, start_frame, end_frame
        )
        if success:
            self._replay_generation = self._model.replay_line_generation
            return True, message, {LPChange.DATA}
        return False, message, set()

    def copy_lp_speeds_from_replay(
        self,
        lp_name: str,
        rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[bool, str, set[LPChange]]:
        success, message = self._model.copy_lp_speeds_from_replay(
            lp_name, rpy, car_id, start_frame, end_frame
        )
        if success:
            self._replay_generation = self._model.replay_line_generation
            return True, message, {LPChange.DATA}
        return False, message, set()

    def generate_lp_line(
        self, lp_name: str, speed_mph: float, dlat: float
    ) -> tuple[bool, str, set[LPChange]]:
        success, message = self._model.generate_lp_line(lp_name, speed_mph, dlat)
        if success:
            return True, message, {LPChange.DATA}
        return False, message, set()

    def select_record_at_point(
        self,
        point: tuple[float, float],
        *,
        cursor_track: tuple[float, float] | None,
        transform: tuple[float, tuple[float, float]] | None,
        viewport_height: int,
    ) -> tuple[set[LPChange], tuple[str, int] | None]:
        if not self.should_track_hover():
            return set(), None
        if transform is None or cursor_track is None:
            return set(), None
        lp_name = self._active_lp_line
        lp_index = self._record_index_at_point(
            lp_name,
            cursor_track,
            transform,
            viewport_height,
            point,
        )
        if lp_index is None:
            return set(), None
        changes = self.set_selected_lp_record(lp_name, lp_index)
        selection = (lp_name, lp_index) if LPChange.SELECTION in changes else None
        return changes, selection

    def _record_for_edit(self, lp_name: str, index: int) -> LpPoint | None:
        if lp_name not in self._model.available_lp_files:
            return None
        records = self._model.ai_line_records(lp_name)
        if index < 0 or index >= len(records):
            return None
        return records[index]

    def _record_index_at_point(
        self,
        lp_name: str,
        cursor_track: tuple[float, float],
        transform: tuple[float, tuple[float, float]],
        viewport_height: int,
        screen_point: tuple[float, float],
    ) -> int | None:
        records = self._model.ai_line_records(lp_name)
        if not records:
            return None
        cursor_x, cursor_y = cursor_track
        best_point: tuple[float, float] | None = None
        best_distance_sq = float("inf")
        best_start_index: int | None = None
        best_end_index: int | None = None
        for idx in range(len(records)):
            p0 = records[idx]
            p1 = records[(idx + 1) % len(records)]
            seg_dx = p1.x - p0.x
            seg_dy = p1.y - p0.y
            seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len_sq == 0:
                continue
            t = ((cursor_x - p0.x) * seg_dx + (cursor_y - p0.y) * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            proj_x = p0.x + seg_dx * t
            proj_y = p0.y + seg_dy * t
            dist_sq = (cursor_x - proj_x) ** 2 + (cursor_y - proj_y) ** 2
            if dist_sq < best_distance_sq:
                best_distance_sq = dist_sq
                best_point = (proj_x, proj_y)
                best_start_index = idx
                best_end_index = (idx + 1) % len(records)
        if best_point is None or best_start_index is None or best_end_index is None:
            return None
        mapped_point = _map_point(
            best_point[0], best_point[1], transform, viewport_height
        )
        if (
            abs(mapped_point[0] - screen_point[0])
            + abs(mapped_point[1] - screen_point[1])
            > 16
        ):
            return None
        start_record = records[best_start_index]
        end_record = records[best_end_index]
        dist_start = (cursor_x - start_record.x) ** 2 + (cursor_y - start_record.y) ** 2
        dist_end = (cursor_x - end_record.x) ** 2 + (cursor_y - end_record.y) ** 2
        return best_start_index if dist_start <= dist_end else best_end_index


def _map_point(
    x: float,
    y: float,
    transform: tuple[float, tuple[float, float]],
    viewport_height: int,
) -> tuple[float, float]:
    scale, offsets = transform
    px = x * scale + offsets[0]
    py = y * scale + offsets[1]
    return px, viewport_height - py
