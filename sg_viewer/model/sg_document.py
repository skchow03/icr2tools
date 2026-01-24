from __future__ import annotations

from typing import Iterable

from PyQt5 import QtCore
import numpy as np

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.sg_document_fsects import (
    FSection,
    delete_fsection,
    insert_fsection,
    replace_fsections,
    update_fsection,
)


class SGDocument(QtCore.QObject):
    section_changed = QtCore.pyqtSignal(int)
    geometry_changed = QtCore.pyqtSignal()
    metadata_changed = QtCore.pyqtSignal()

    ELEVATION_MIN = -1_000_000
    ELEVATION_MAX = 1_000_000

    def __init__(self, sg_data: SGFile | None = None, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._sg_data = sg_data
        if self._sg_data is not None:
            self.validate()

    @property
    def sg_data(self) -> SGFile | None:
        return self._sg_data

    def set_sg_data(self, sg_data: SGFile | None, *, validate: bool = True) -> None:
        self._sg_data = sg_data
        if self._sg_data is not None and validate:
            self.validate()
        self.metadata_changed.emit()
        self.geometry_changed.emit()

    def set_section_elevation(self, section_id: int, new_value: float) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if section_id < 0 or section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")

        section = self._sg_data.sects[section_id]
        if not section.alt:
            raise ValueError("Section has no elevation data.")

        updated = int(round(new_value))
        section.alt = [updated for _ in section.alt]

        if __debug__:
            self.validate()

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def set_section_xsect_altitude(
        self, section_id: int, xsect_index: int, new_value: float
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

        if __debug__:
            self.validate()

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def set_section_xsect_grade(
        self, section_id: int, xsect_index: int, new_value: float
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

        if __debug__:
            self.validate()

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

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

        self.geometry_changed.emit()

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

        dtype = getattr(self._sg_data.xsect_dlats, "dtype", np.int32)
        self._sg_data.xsect_dlats = np.array(dlats, dtype=dtype)
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
        self.geometry_changed.emit()

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

        if sg_data.num_sects != len(sg_data.sects):
            raise ValueError("Section count does not match SG header.")

        self._validate_section_links(sg_data.sects)
        self._validate_dlongs(sg_data.sects)
        self._validate_elevations(sg_data)

    def _validate_section_links(self, sections: Iterable[object]) -> None:
        """
        Validates section topology:
        - IDs must be in range
        - previous/next links must be reciprocal
        - ordering is NOT enforced
        """
        sections = list(sections)
        count = len(sections)
        link_ids: list[int] = []
        for sect in sections:
            prev_id = getattr(sect, "previous_id", getattr(sect, "sec_prev", None))
            next_id = getattr(sect, "next_id", getattr(sect, "sec_next", None))
            for value in (prev_id, next_id):
                if value is None or value == -1:
                    continue
                if isinstance(value, int):
                    link_ids.append(value)

        one_based = False
        if link_ids:
            min_id = min(link_ids)
            max_id = max(link_ids)
            if max_id == count or (min_id >= 1 and max_id <= count and 0 not in link_ids):
                one_based = True

        def normalize_id(value: int | None) -> int | None:
            if value is None or value == -1:
                return None
            if not isinstance(value, int):
                return None
            return value - 1 if one_based else value

        def valid_id(i):
            return isinstance(i, int) and 0 <= i < count

        for idx, sect in enumerate(sections):
            sid = getattr(sect, "section_id", idx)
            prev_id = getattr(sect, "previous_id", getattr(sect, "sec_prev", None))
            next_id = getattr(sect, "next_id", getattr(sect, "sec_next", None))
            norm_prev_id = normalize_id(prev_id)
            norm_next_id = normalize_id(next_id)

            # Validate previous link
            if norm_prev_id is not None:
                if not valid_id(norm_prev_id):
                    raise ValueError(f"Section {sid}: invalid previous_id {prev_id}")
                prev_sect = sections[norm_prev_id]
                prev_next_id = getattr(
                    prev_sect, "next_id", getattr(prev_sect, "sec_next", None)
                )
                norm_prev_next_id = normalize_id(prev_next_id)
                if norm_prev_next_id != idx:
                    raise ValueError(
                        f"Section {sid}: previous_id {prev_id} not reciprocated "
                        f"(prev.next_id={prev_next_id})"
                    )

            # Validate next link
            if norm_next_id is not None:
                if not valid_id(norm_next_id):
                    raise ValueError(f"Section {sid}: invalid next_id {next_id}")
                next_sect = sections[norm_next_id]
                next_prev_id = getattr(
                    next_sect, "previous_id", getattr(next_sect, "sec_prev", None)
                )
                norm_next_prev_id = normalize_id(next_prev_id)
                if norm_next_prev_id != idx:
                    raise ValueError(
                        f"Section {sid}: next_id {next_id} not reciprocated "
                        f"(next.previous_id={next_prev_id})"
                    )

        if count == 0:
            return

        # Ensure exactly one connected component (optional but recommended)
        visited = set()
        stack = [0]

        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            s = sections[cur]
            cur_next = normalize_id(getattr(s, "next_id", getattr(s, "sec_next", None)))
            cur_prev = normalize_id(
                getattr(s, "previous_id", getattr(s, "sec_prev", None))
            )
            if cur_next is not None:
                stack.append(cur_next)
            if cur_prev is not None:
                stack.append(cur_prev)

        if len(visited) != len(sections):
            raise ValueError("Track sections are not fully connected")

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
            for altitude in altitudes:
                if altitude < self.ELEVATION_MIN or altitude > self.ELEVATION_MAX:
                    raise ValueError(
                        f"Section {idx} elevation {altitude} outside bounds."
                    )
            grades = list(getattr(section, "grade", []))
            if len(grades) != num_xsects:
                raise ValueError(
                    f"Section {idx} grade count {len(grades)} does not match {num_xsects}."
                )
