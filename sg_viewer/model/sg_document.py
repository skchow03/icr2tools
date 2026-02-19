from __future__ import annotations

import logging
from typing import Callable, Iterable

from PyQt5 import QtCore

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.sg_document_fsects import (
    FSection,
    delete_fsection,
    insert_fsection,
    replace_fsections,
    update_fsection,
)

logger = logging.getLogger(__name__)


class SGDocument(QtCore.QObject):
    section_changed = QtCore.pyqtSignal(int)
    geometry_changed = QtCore.pyqtSignal()
    elevation_changed = QtCore.pyqtSignal(int)
    elevations_bulk_changed = QtCore.pyqtSignal()
    metadata_changed = QtCore.pyqtSignal()

    ELEVATION_MIN = -1_000_000
    ELEVATION_MAX = 1_000_000

    def __init__(self, sg_data: SGFile | None = None, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._sg_data = sg_data
        self._last_validation_warnings: list[str] = []
        self._suspend_elevation_signals = False
        self._pending_bulk_elevation_signal = False
        if self._sg_data is not None:
            self.validate()

    @property
    def elevation_signals_suspended(self) -> bool:
        return self._suspend_elevation_signals

    def set_elevation_signals_suspended(self, suspended: bool) -> None:
        next_state = bool(suspended)
        if self._suspend_elevation_signals == next_state:
            return
        self._suspend_elevation_signals = next_state
        if not self._suspend_elevation_signals and self._pending_bulk_elevation_signal:
            self._pending_bulk_elevation_signal = False
            self.elevations_bulk_changed.emit()

    def _emit_elevation_changed(self, section_id: int) -> None:
        if self._suspend_elevation_signals:
            self._pending_bulk_elevation_signal = True
            return
        self.elevation_changed.emit(section_id)

    def _emit_bulk_elevation_changed(self) -> None:
        if self._suspend_elevation_signals:
            self._pending_bulk_elevation_signal = True
            return
        self.elevations_bulk_changed.emit()

    @property
    def sg_data(self) -> SGFile | None:
        return self._sg_data

    def last_validation_warnings(self) -> list[str]:
        return list(self._last_validation_warnings)

    def set_sg_data(self, sg_data: SGFile | None, *, validate: bool = True) -> None:
        self._sg_data = sg_data
        if self._sg_data is not None and validate:
            self.validate()
        self.metadata_changed.emit()
        self.geometry_changed.emit()

    def set_section_elevation(
        self, section_id: int, new_value: float, *, validate: bool = True
    ) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if section_id < 0 or section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")

        section = self._sg_data.sects[section_id]
        if not section.alt:
            raise ValueError("Section has no elevation data.")

        updated = int(round(new_value))
        section.alt = [updated for _ in section.alt]

        if __debug__ and validate:
            self.validate()

        self._emit_elevation_changed(section_id)

    def set_section_xsect_altitude(
        self,
        section_id: int,
        xsect_index: int,
        new_value: float,
        *,
        validate: bool = True,
    ) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if section_id < 0 or section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")

        if xsect_index < 0 or xsect_index >= self._sg_data.num_xsects:
            raise IndexError("X-section index out of range.")

        section = self._sg_data.sects[section_id]
        if not section.alt or xsect_index >= len(section.alt):
            raise ValueError("Section has no elevation data.")

        updated = int(round(new_value))
        section.alt[xsect_index] = updated

        if __debug__ and validate:
            self.validate()

        self._emit_elevation_changed(section_id)

    def set_section_xsect_grade(
        self,
        section_id: int,
        xsect_index: int,
        new_value: float,
        *,
        validate: bool = True,
    ) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if section_id < 0 or section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")

        if xsect_index < 0 or xsect_index >= self._sg_data.num_xsects:
            raise IndexError("X-section index out of range.")

        section = self._sg_data.sects[section_id]
        if not section.grade or xsect_index >= len(section.grade):
            raise ValueError("Section has no grade data.")

        updated = int(round(new_value))
        section.grade[xsect_index] = updated

        if __debug__ and validate:
            self.validate()

        self._emit_elevation_changed(section_id)

    def copy_xsect_data_to_all(self, xsect_index: int) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if xsect_index < 0 or xsect_index >= self._sg_data.num_xsects:
            raise IndexError("X-section index out of range.")

        if not self._sg_data.sects:
            raise ValueError("No sections available to update.")

        for idx, section in enumerate(self._sg_data.sects):
            if not section.alt or xsect_index >= len(section.alt):
                raise ValueError(f"Section {idx} has no elevation data.")
            if not section.grade or xsect_index >= len(section.grade):
                raise ValueError(f"Section {idx} has no grade data.")

        num_xsects = self._sg_data.num_xsects
        for section in self._sg_data.sects:
            altitude = int(section.alt[xsect_index])
            grade = int(section.grade[xsect_index])
            section.alt = [altitude for _ in range(num_xsects)]
            section.grade = [grade for _ in range(num_xsects)]

        if __debug__:
            self.validate()

        self._emit_bulk_elevation_changed()

    def offset_all_elevations(self, delta: float, *, validate: bool = True) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if not self._sg_data.sects:
            raise ValueError("No sections available to update.")

        offset = int(round(delta))
        for idx, section in enumerate(self._sg_data.sects):
            if not section.alt:
                raise ValueError(f"Section {idx} has no elevation data.")
            section.alt = [int(value) + offset for value in section.alt]

        if __debug__ and validate:
            self.validate()

        self._emit_bulk_elevation_changed()

    def flatten_all_elevations_and_grade(
        self,
        elevation: float,
        *,
        grade: float = 0.0,
        validate: bool = True,
    ) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if not self._sg_data.sects:
            raise ValueError("No sections available to update.")

        target_altitude = int(round(elevation))
        target_grade = int(round(grade))
        for idx, section in enumerate(self._sg_data.sects):
            if not section.alt:
                raise ValueError(f"Section {idx} has no elevation data.")
            if not section.grade:
                raise ValueError(f"Section {idx} has no grade data.")
            section.alt = [target_altitude for _ in section.alt]
            section.grade = [target_grade for _ in section.grade]

        if __debug__ and validate:
            self.validate()

        self._emit_bulk_elevation_changed()

    def generate_elevation_change(
        self,
        *,
        start_section_id: int,
        end_section_id: int,
        xsect_index: int,
        start_elevation: float,
        end_elevation: float,
        curve_type: str,
        validate: bool = True,
    ) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if not self._sg_data.sects:
            raise ValueError("No sections available to update.")

        if start_section_id < 0 or end_section_id < 0:
            raise IndexError("Section index out of range.")
        if start_section_id >= len(self._sg_data.sects) or end_section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")
        if end_section_id <= start_section_id:
            raise ValueError("Ending section must be after starting section.")
        if xsect_index < 0 or xsect_index >= self._sg_data.num_xsects:
            raise IndexError("X-section index out of range.")

        section_span = end_section_id - start_section_id
        start_altitude = float(start_elevation)
        end_altitude = float(end_elevation)
        altitude_delta = end_altitude - start_altitude

        curve_shapes: dict[str, tuple[Callable[[float], float], Callable[[float], float]]] = {
            "linear": (
                lambda t: t,
                lambda t: 1.0,
            ),
            "convex": (
                lambda t: t * t,
                lambda t: 2.0 * t,
            ),
            "concave": (
                lambda t: 1.0 - (1.0 - t) * (1.0 - t),
                lambda t: 2.0 - 2.0 * t,
            ),
            "s_curve": (
                lambda t: 3.0 * t * t - 2.0 * t * t * t,
                lambda t: 6.0 * t - 6.0 * t * t,
            ),
        }
        if curve_type not in curve_shapes:
            raise ValueError("Unknown curve type.")

        shape_fn, slope_fn = curve_shapes[curve_type]

        for section_id in range(start_section_id, end_section_id + 1):
            section = self._sg_data.sects[section_id]
            if not section.alt or xsect_index >= len(section.alt):
                raise ValueError(f"Section {section_id} has no elevation data.")
            if not section.grade or xsect_index >= len(section.grade):
                raise ValueError(f"Section {section_id} has no grade data.")

            t = float(section_id - start_section_id) / float(section_span)
            section.alt[xsect_index] = int(round(start_altitude + altitude_delta * shape_fn(t)))
            slope = (altitude_delta * slope_fn(t)) / float(section_span)
            section.grade[xsect_index] = int(round(slope * 8192.0))

        if __debug__ and validate:
            self.validate()

        self._emit_bulk_elevation_changed()

    def set_xsect_definitions(self, entries: list[tuple[int | None, float]]) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if len(entries) < 2:
            raise ValueError("At least two X-sections are required.")
        if len(entries) > 10:
            raise ValueError("At most ten X-sections are supported.")

        num_existing = int(self._sg_data.num_xsects)
        used_indices: set[int] = set()
        index_map: list[int | None] = []
        dlats: list[int] = []

        for key, dlat in entries:
            if key is None:
                index_map.append(None)
            else:
                index = int(key)
                if index < 0 or index >= num_existing:
                    raise IndexError("X-section index out of range.")
                if index in used_indices:
                    raise ValueError("Duplicate X-section entries provided.")
                used_indices.add(index)
                index_map.append(index)
            dlats.append(int(round(dlat)))

        self._sg_data.xsect_dlats = self._convert_xsect_dlats(dlats)
        self._sg_data.num_xsects = len(dlats)
        if len(self._sg_data.header) > 5:
            self._sg_data.header[5] = len(dlats)

        for section in self._sg_data.sects:
            altitudes = list(getattr(section, "alt", []))
            grades = list(getattr(section, "grade", []))
            new_altitudes: list[int] = []
            new_grades: list[int] = []
            for source in index_map:
                if source is None:
                    new_altitudes.append(0)
                    new_grades.append(0)
                else:
                    if source >= len(altitudes) or source >= len(grades):
                        raise ValueError("Section elevation data is incomplete.")
                    new_altitudes.append(int(altitudes[source]))
                    new_grades.append(int(grades[source]))
            section.alt = new_altitudes
            section.grade = new_grades

        if __debug__:
            self.validate()

        self.metadata_changed.emit()
        self._emit_bulk_elevation_changed()

    def _convert_xsect_dlats(self, dlats: list[int]) -> object:
        existing = self._sg_data.xsect_dlats
        if not hasattr(existing, "dtype"):
            return list(dlats)

        dtype = getattr(existing, "dtype")
        container_type = type(existing)
        for constructor in (
            lambda values: container_type(values, dtype=dtype),
            lambda values: container_type(values),
        ):
            try:
                return constructor(dlats)
            except (TypeError, ValueError):
                continue

        return list(dlats)

    def rebuild_dlongs(self, start_index: int = 0, start_dlong: int = 0) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        self._sg_data.rebuild_dlongs(start_index, start_dlong)

        if __debug__:
            self.validate()

        self.geometry_changed.emit()

    def add_fsection(self, section_id: int, index: int, fsect: FSection) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        insert_fsection(self._sg_data, section_id, index, fsect)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def edit_fsection(self, section_id: int, index: int, **fields: object) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        update_fsection(self._sg_data, section_id, index, **fields)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def remove_fsection(self, section_id: int, index: int) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        delete_fsection(self._sg_data, section_id, index)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def replace_fsections(self, section_id: int, fsects: list[FSection]) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        replace_fsections(self._sg_data, section_id, fsects)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def validate(self) -> None:
        sg_data = self._sg_data
        if sg_data is None:
            return

        self._last_validation_warnings = []
        logger.debug(
            "Validating SG data: header_sects=%s actual_sects=%s num_xsects=%s",
            getattr(sg_data, "num_sects", None),
            len(sg_data.sects),
            getattr(sg_data, "num_xsects", None),
        )
        if sg_data.num_sects != len(sg_data.sects):
            raise ValueError("Section count does not match SG header.")

        self._validate_section_links(sg_data.sects, self._last_validation_warnings)
        self._validate_dlongs(sg_data.sects)
        self._validate_elevations(sg_data)

    def _validate_section_links(
        self, sections: Iterable[object], warnings: list[str] | None = None
    ) -> None:
        sections_list = list(sections)
        total = len(sections_list)
        if total == 0:
            return

        logger.debug("Validating section links: total=%d", total)

        for idx, section in enumerate(sections_list):
            sec_prev = int(getattr(section, "sec_prev", -1))
            sec_next = int(getattr(section, "sec_next", -1))

            expected_prev = idx - 1
            expected_next = idx + 1
            if idx == 0 and total > 1:
                expected_prev = total - 1
            if idx == total - 1 and total > 1:
                expected_next = 0

            valid_prev = {-1, expected_prev}
            valid_next = {-1, expected_next}
            if total > 0:
                if idx == 0:
                    valid_prev.add(total)
                if idx == total - 1:
                    valid_next.add(total)

            if sec_prev not in valid_prev:
                message = (
                    f"Section {idx} has invalid previous index {sec_prev} "
                    f"(expected one of {sorted(valid_prev)})."
                )
                logger.warning(
                    "Section link validation failed (prev): idx=%d total=%d sec_prev=%s "
                    "sec_next=%s expected_prev=%s expected_next=%s valid_prev=%s valid_next=%s",
                    idx,
                    total,
                    sec_prev,
                    sec_next,
                    expected_prev,
                    expected_next,
                    sorted(valid_prev),
                    sorted(valid_next),
                )
                if logger.isEnabledFor(logging.DEBUG):
                    link_snapshot = [
                        (i, int(getattr(sec, "sec_prev", -1)), int(getattr(sec, "sec_next", -1)))
                        for i, sec in enumerate(sections_list)
                    ]
                    logger.debug("Section link snapshot: %s", link_snapshot)
                if warnings is not None:
                    warnings.append(message)
            if sec_next not in valid_next:
                message = (
                    f"Section {idx} has invalid next index {sec_next} "
                    f"(expected one of {sorted(valid_next)})."
                )
                logger.warning(
                    "Section link validation failed (next): idx=%d total=%d sec_prev=%s "
                    "sec_next=%s expected_prev=%s expected_next=%s valid_prev=%s valid_next=%s",
                    idx,
                    total,
                    sec_prev,
                    sec_next,
                    expected_prev,
                    expected_next,
                    sorted(valid_prev),
                    sorted(valid_next),
                )
                if logger.isEnabledFor(logging.DEBUG):
                    link_snapshot = [
                        (i, int(getattr(sec, "sec_prev", -1)), int(getattr(sec, "sec_next", -1)))
                        for i, sec in enumerate(sections_list)
                    ]
                    logger.debug("Section link snapshot: %s", link_snapshot)
                if warnings is not None:
                    warnings.append(message)

    def _validate_dlongs(self, sections: Iterable[object]) -> None:
        last_start = None
        for idx, section in enumerate(sections):
            start_dlong = float(getattr(section, "start_dlong", 0.0))
            length = float(getattr(section, "length", 0.0))

            if last_start is not None and start_dlong < last_start:
                raise ValueError(
                    f"Section {idx} start_dlong {start_dlong} is less than previous {last_start}."
                )

            if length < 0:
                raise ValueError(f"Section {idx} has negative length {length}.")

            last_start = start_dlong

    def _validate_elevations(self, sg_data: SGFile) -> None:
        num_xsects = sg_data.num_xsects
        for idx, section in enumerate(sg_data.sects):
            altitudes = list(getattr(section, "alt", []))
            if len(altitudes) != num_xsects:
                raise ValueError(
                    f"Section {idx} elevation count {len(altitudes)} does not match {num_xsects}."
                )
            grades = list(getattr(section, "grade", []))
            if len(grades) != num_xsects:
                raise ValueError(
                    f"Section {idx} grade count {len(grades)} does not match {num_xsects}."
                )
