from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, List, Tuple

from PyQt5 import QtCore

from track_viewer.geometry import CenterlineIndex, project_point_to_centerline

from sg_viewer.sg_model import SectionPreview

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass
class SectionSelection:
    index: int
    type_name: str
    start_dlong: float
    end_dlong: float
    start_heading: tuple[float, float] | None = None
    end_heading: tuple[float, float] | None = None
    center: Point | None = None
    radius: float | None = None


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
        self._track_length = track_length
        self._centerline_index = centerline_index
        self._sampled_dlongs = sampled_dlongs

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
        if not self._centerline_index or not self._sampled_dlongs or not self._track_length:
            return

        track_point = map_to_track(QtCore.QPointF(pos))
        if track_point is None or transform is None:
            return

        _, nearest_dlong, distance_sq = project_point_to_centerline(
            track_point, self._centerline_index, self._sampled_dlongs, self._track_length
        )

        if nearest_dlong is None:
            return

        scale, _ = transform
        tolerance_units = 10 / max(scale, 1e-6)
        if distance_sq > tolerance_units * tolerance_units:
            self.set_selected_section(None)
            return

        selection = self._find_section_by_dlong(nearest_dlong)
        self.set_selected_section(selection)

    def set_selected_section(self, index: int | None) -> None:
        if index is None:
            self._selected_section_index = None
            self._selected_section_points = []
            self._selected_curve_index = None
            self.selectionChanged.emit(None)
            return

        if not self._sections or index < 0 or index >= len(self._sections):
            return

        self._selected_section_index = index
        section = self._sections[index]
        self._selected_section_points = list(section.polyline)
        self._selected_curve_index = index if section.center is not None else None
        selection = self._build_section_selection(section)
        self.selectionChanged.emit(selection)

    def _find_section_by_dlong(self, dlong: float) -> int | None:
        if not self._sections or self._track_length is None:
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

    def _build_section_selection(self, section: SectionPreview) -> SectionSelection:
        return SectionSelection(
            index=section.section_id,
            type_name=section.type_name,
            start_dlong=section.start_dlong,
            end_dlong=section.start_dlong + section.length,
            center=section.center,
            radius=section.radius,
            start_heading=section.start_heading,
            end_heading=section.end_heading,
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


def round_sg_value(value: float) -> float:
    return float(round(value))


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
