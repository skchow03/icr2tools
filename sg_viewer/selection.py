from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from typing import Callable, List, Tuple

from PyQt5 import QtCore

from track_viewer.geometry import CenterlineIndex, project_point_to_centerline

from sg_viewer.sg_model import SectionPreview

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]

logger = logging.getLogger(__name__)


@dataclass
class SectionSelection:
    index: int
    type_name: str
    start_dlong: float
    end_dlong: float
    length: float
    previous_id: int
    next_id: int
    start_point: Point | None = None
    end_point: Point | None = None
    start_heading: tuple[float, float] | None = None
    end_heading: tuple[float, float] | None = None
    center: Point | None = None
    radius: float | None = None
    sg_start_heading: tuple[int, int] | None = None
    sg_end_heading: tuple[int, int] | None = None
    sg_radius: int | None = None
    sg_sang1: int | None = None
    sg_sang2: int | None = None
    sg_eang1: int | None = None
    sg_eang2: int | None = None


@dataclass
class SectionHeadingData:
    index: int
    start_heading: tuple[float, float] | None
    end_heading: tuple[float, float] | None
    delta_to_next: float | None


class SelectionManager(QtCore.QObject):
    selectionChanged = QtCore.pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._sections: list[SectionPreview] = []
        self._track_length: float | None = None
        self._centerline_index: CenterlineIndex | None = None
        self._sampled_dlongs: List[float] = []
        self._selected_section_index: int | None = None
        self._selected_section_points: list[Point] = []
        self._selected_curve_index: int | None = None
        self._section_ranges: list[tuple[float, float]] = []

    @property
    def selected_section_index(self) -> int | None:
        return self._selected_section_index

    @property
    def selected_section_points(self) -> list[Point]:
        return self._selected_section_points

    @property
    def selected_curve_index(self) -> int | None:
        return self._selected_curve_index

    @property
    def sections(self) -> list[SectionPreview]:
        return self._sections

    def update_context(
        self,
        sections: list[SectionPreview],
        track_length: float | None,
        centerline_index: CenterlineIndex | None,
        sampled_dlongs: List[float],
    ) -> None:
        self._sections = sections
        self._track_length = self._compute_track_length(track_length, sampled_dlongs)
        self._centerline_index = centerline_index
        self._sampled_dlongs = sampled_dlongs
        self._section_ranges = self._compute_section_ranges(sections)

        if self._selected_section_index is not None:
            if self._selected_section_index >= len(sections):
                self.set_selected_section(None)
            else:
                self.set_selected_section(self._selected_section_index)

    def reset(
        self,
        sections: list[SectionPreview],
        track_length: float | None,
        centerline_index: CenterlineIndex | None,
        sampled_dlongs: List[float],
    ) -> None:
        self._sections = sections
        self._track_length = track_length
        self._centerline_index = centerline_index
        self._sampled_dlongs = sampled_dlongs
        self._section_ranges = []
        self._selected_section_index = None
        self._selected_section_points = []
        self._selected_curve_index = None
        self.selectionChanged.emit(None)

    def handle_click(
        self,
        pos: QtCore.QPoint,
        map_to_track: Callable[[QtCore.QPointF], Point | None],
        transform: Transform | None,
    ) -> None:
        selection = self.find_section_at_point(pos, map_to_track, transform)
        if selection is None:
            return

        self.set_selected_section(selection)

    def find_section_at_point(
        self,
        pos: QtCore.QPoint,
        map_to_track: Callable[[QtCore.QPointF], Point | None],
        transform: Transform | None,
    ) -> int | None:
        if transform is None:
            logger.debug("Selection.handle_click skipped: no transform for %s", pos)
            return

        track_point = map_to_track(QtCore.QPointF(pos))
        if track_point is None:
            logger.debug("Selection.handle_click skipped: track map failed for %s", pos)
            return

        logger.debug(
            "Selection.handle_click mapped screen %s to track %s with transform scale %.3f",
            pos,
            track_point,
            transform[0],
        )

        selection = self._find_section_by_dlong(track_point, transform)
        logger.debug(
            "Selection.handle_click resolved selection index %s (total sections=%d)",
            selection,
            len(self._sections),
        )
        return selection

    def set_selected_section(self, index: int | None) -> None:
        if index is None:
            self._selected_section_index = None
            self._selected_section_points = []
            self._selected_curve_index = None
            logger.debug("Selection cleared")
            self.selectionChanged.emit(None)
            return

        if not self._sections or index < 0 or index >= len(self._sections):
            logger.debug(
                "Selection.set_selected_section ignored invalid index %s (sections=%d)",
                index,
                len(self._sections),
            )
            return

        self._selected_section_index = index
        section = self._sections[index]
        self._selected_section_points = list(section.polyline)
        self._selected_curve_index = index if section.center is not None else None
        logger.debug(
            "Selection set to index %d type=%s start_dlong=%.3f length=%.3f", 
            index,
            section.type_name,
            float(section.start_dlong),
            float(section.length),
        )
        selection = self._build_section_selection(section)
        self.selectionChanged.emit(selection)

    def _find_section_by_dlong(self, track_point: Point, transform: Transform) -> int | None:
        if not self._sections:
            return None

        polylines: list[tuple[int, list[Point]]] = [
            (idx, sect.polyline) for idx, sect in enumerate(self._sections) if len(sect.polyline) >= 2
        ]

        if polylines:
            best_index: int | None = None
            best_distance = float("inf")

            for idx, polyline in polylines:
                distance = self._distance_to_polyline(track_point, polyline)
                if distance < best_distance:
                    best_distance = distance
                    best_index = idx

            scale, _ = transform
            screen_distance = best_distance * max(scale, 0.0)
            logger.debug(
                "Selection._find_section_by_dlong nearest polyline idx=%s distance=%.3fpx (scale=%.3f)",
                best_index,
                screen_distance,
                scale,
            )
            if best_index is not None and screen_distance <= 10.0:
                return best_index
            return None

        if not self._centerline_index or not self._sampled_dlongs or not self._track_length:
            return None

        _, nearest_dlong, distance_sq = project_point_to_centerline(
            track_point, self._centerline_index, self._sampled_dlongs, self._track_length
        )

        if nearest_dlong is None:
            return None

        scale, _ = transform
        screen_distance = math.sqrt(distance_sq) * max(scale, 0.0)
        logger.debug(
            "Selection._find_section_by_dlong centerline projection dlong=%.3f distance=%.3fpx",
            nearest_dlong,
            screen_distance,
        )
        if screen_distance > 10.0:
            return None

        return self._section_index_for_dlong(nearest_dlong)

    def _section_index_for_dlong(self, dlong: float) -> int | None:
        if not self._sections or self._track_length is None:
            return None

        if self._section_ranges:
            track_length = self._track_length or 0
            for idx, (start, end) in enumerate(self._section_ranges):
                if start <= dlong <= end:
                    return idx
                if track_length > 0 and end > track_length and (dlong >= start or dlong <= end - track_length):
                    return idx
            return None

        track_length = self._track_length or 0
        for idx, sect in enumerate(self._sections):
            start = float(sect.start_dlong)
            end = start + float(sect.length)
            if track_length > 0 and end > track_length:
                if dlong >= start or dlong <= end - track_length:
                    return idx
            elif start <= dlong <= end:
                return idx
        return None

    @staticmethod
    def _distance_to_polyline(point: Point, polyline: list[Point]) -> float:
        best_distance_sq = float("inf")
        for start, end in zip(polyline, polyline[1:]):
            distance_sq = point_to_segment_distance_sq(point, start, end)
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
        return math.sqrt(best_distance_sq)

    def _compute_track_length(self, track_length: float | None, sampled_dlongs: list[float]) -> float | None:
        if sampled_dlongs:
            return sampled_dlongs[-1]
        return track_length

    def _compute_section_ranges(self, sections: list[SectionPreview]) -> list[tuple[float, float]]:
        ranges: list[tuple[float, float]] = []
        cursor = 0.0

        for sect in sections:
            if not sect.polyline or len(sect.polyline) < 2:
                continue

            length = self._section_length(sect.polyline)

            start_dlong = cursor
            cursor += length
            ranges.append((start_dlong, cursor))

        return ranges

    def _build_section_selection(self, section: SectionPreview) -> SectionSelection:
        length = float(section.length)
        sg_values = self._compute_sg_save_values(section)
        return SectionSelection(
            index=section.section_id,
            type_name=section.type_name,
            start_dlong=section.start_dlong,
            end_dlong=section.start_dlong + section.length,
            length=length,
            previous_id=section.previous_id,
            next_id=section.next_id,
            start_point=section.start,
            end_point=section.end,
            center=section.center,
            radius=section.radius,
            start_heading=section.start_heading,
            end_heading=section.end_heading,
            sg_start_heading=sg_values.start_heading,
            sg_end_heading=sg_values.end_heading,
            sg_radius=sg_values.radius,
            sg_sang1=sg_values.sang1,
            sg_sang2=sg_values.sang2,
            sg_eang1=sg_values.eang1,
            sg_eang2=sg_values.eang2,
        )

    @staticmethod
    def _section_length(polyline: list[Point]) -> float:
        length = 0.0
        for start, end in zip(polyline, polyline[1:]):
            length += math.hypot(end[0] - start[0], end[1] - start[1])
        return length

    @staticmethod
    def _compute_sg_save_values(section: SectionPreview) -> _SGSaveValues:
        def _as_int(value: float | int | None) -> int | None:
            if value is None:
                return None
            return int(round(value))

        start_heading = (
            (section.sang1, section.sang2)
            if section.sang1 is not None and section.sang2 is not None
            else section.start_heading
        )
        end_heading = (
            (section.eang1, section.eang2)
            if section.eang1 is not None and section.eang2 is not None
            else section.end_heading
        )

        sang1 = sang2 = eang1 = eang2 = None
        if section.type_name == "curve" and section.center is not None and section.radius is not None:
            sang1, sang2, eang1, eang2 = _curve_angles(
                section.start,
                section.end,
                section.center,
                section.radius,
            )
        else:
            if start_heading is not None:
                sang1, sang2 = start_heading
            if end_heading is not None:
                eang1, eang2 = end_heading

        def _as_heading(value: tuple[float, float] | None) -> tuple[int, int] | None:
            if value is None:
                return None
            return (_as_int(value[0]) or 0, _as_int(value[1]) or 0)

        return _SGSaveValues(
            sang1=_as_int(sang1),
            sang2=_as_int(sang2),
            eang1=_as_int(eang1),
            eang2=_as_int(eang2),
            radius=_as_int(section.radius),
            start_heading=_as_heading(start_heading),
            end_heading=_as_heading(end_heading),
        )

    def get_section_headings(self) -> list[SectionHeadingData]:
        if not self._sections:
            return []

        headings: list[SectionHeadingData] = []
        total = len(self._sections)
        for idx, sect in enumerate(self._sections):
            start = sect.start_heading
            end = sect.end_heading
            next_start = self._sections[(idx + 1) % total].start_heading if total else None
            delta = heading_delta(end, next_start)
            headings.append(
                SectionHeadingData(
                    index=idx,
                    start_heading=start,
                    end_heading=end,
                    delta_to_next=delta,
                )
            )

        return headings


@dataclass
class _SGSaveValues:
    sang1: int | None
    sang2: int | None
    eang1: int | None
    eang2: int | None
    radius: int | None
    start_heading: tuple[int, int] | None
    end_heading: tuple[int, int] | None


def round_sg_value(value: float) -> float:
    return float(round(value))


def _curve_angles(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    radius: float,
) -> tuple[float, float, float, float]:
    """Compute SG curve angles based on geometry.

    The values match the SG format expectations:
    Sang1 = Center_Y - Start_Y
    Sang2 = Start_X - Center_X
    Eang1 = Center_Y - End_Y
    Eang2 = End_X - Center_X

    Each component is multiplied by the sign of ``radius`` (positive when the
    curve bends right, negative when it bends left).
    """

    cx, cy = center
    sx, sy = start
    ex, ey = end
    sign = 1 if radius >= 0 else -1

    sang1 = (cy - sy) * sign
    sang2 = (sx - cx) * sign
    eang1 = (cy - ey) * sign
    eang2 = (ex - cx) * sign

    return sang1, sang2, eang1, eang2


def point_to_segment_distance_sq(point: Point, start: Point, end: Point) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    vx = ex - sx
    vy = ey - sy
    if vx == 0 and vy == 0:
        dx = px - sx
        dy = py - sy
        return dx * dx + dy * dy

    t = ((px - sx) * vx + (py - sy) * vy) / (vx * vx + vy * vy)
    t = max(0.0, min(1.0, t))

    proj_x = sx + vx * t
    proj_y = sy + vy * t
    dx = px - proj_x
    dy = py - proj_y
    return dx * dx + dy * dy


def normalize_heading_vector(vector: tuple[float, float] | None) -> tuple[float, float] | None:
    if vector is None:
        return None

    length = (vector[0] * vector[0] + vector[1] * vector[1]) ** 0.5
    if length <= 0:
        return None

    return (vector[0] / length, vector[1] / length)


def round_heading_vector(vector: tuple[float, float] | None) -> tuple[float, float] | None:
    normalized = normalize_heading_vector(vector)
    if normalized is None:
        return None

    return (round(normalized[0], 5), round(normalized[1], 5))


def heading_delta(end: tuple[float, float] | None, next_start: tuple[float, float] | None) -> float | None:
    end_norm = normalize_heading_vector(end)
    next_norm = normalize_heading_vector(next_start)
    if end_norm is None or next_norm is None:
        return None

    dot = max(-1.0, min(1.0, end_norm[0] * next_norm[0] + end_norm[1] * next_norm[1]))
    cross = end_norm[0] * next_norm[1] - end_norm[1] * next_norm[0]
    angle_deg = math.degrees(math.atan2(cross, dot))
    return round(angle_deg, 4)
