from __future__ import annotations

import copy

from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.geometry.topology import is_closed_loop


class _RuntimeCoreConnectOpsMixin:
    def _fsect_edge_profile(
        self, source_index: int, endtype: str
    ) -> list[PreviewFSection]:
        if endtype not in {"start", "end"}:
            return []
        if not (0 <= source_index < len(self._fsects_by_section)):
            return []

        edge_profile: list[PreviewFSection] = []
        for fsect in self._fsects_by_section[source_index]:
            edge_value = fsect.end_dlat if endtype == "end" else fsect.start_dlat
            edge_profile.append(
                PreviewFSection(
                    start_dlat=edge_value,
                    end_dlat=edge_value,
                    surface_type=fsect.surface_type,
                    type2=fsect.type2,
                )
            )
        return edge_profile

    def _apply_fsect_edge_profile(
        self, index: int, endtype: str, edge_profile: list[PreviewFSection]
    ) -> None:
        if (
            not edge_profile
            or endtype not in {"start", "end"}
            or not (0 <= index < len(self._fsects_by_section))
        ):
            return

        current = self._fsects_by_section[index]
        if not current or len(current) != len(edge_profile):
            self._fsects_by_section[index] = copy.deepcopy(edge_profile)
            return

        updated: list[PreviewFSection] = []
        for existing, edge in zip(current, edge_profile):
            if endtype == "start":
                updated.append(
                    PreviewFSection(
                        start_dlat=edge.start_dlat,
                        end_dlat=existing.end_dlat,
                        surface_type=edge.surface_type,
                        type2=edge.type2,
                    )
                )
            else:
                updated.append(
                    PreviewFSection(
                        start_dlat=existing.start_dlat,
                        end_dlat=edge.end_dlat,
                        surface_type=edge.surface_type,
                        type2=edge.type2,
                    )
                )
        self._fsects_by_section[index] = updated

    def _sync_fsects_on_connection(
        self, source: tuple[int, str], target: tuple[int, str]
    ) -> None:
        source_index, source_end = source
        target_index, target_end = target
        if source_end not in {"start", "end"} or target_end not in {"start", "end"}:
            return
        if 0 <= source_index < len(self._fsects_by_section):
            if self._fsects_by_section[source_index]:
                return

        edge_profile = self._fsect_edge_profile(target_index, target_end)
        self._apply_fsect_edge_profile(source_index, source_end, edge_profile)

    def _insert_fsects_by_section(
        self,
        index: int,
        source_index: int | None = None,
        source_endtype: str | None = None,
    ) -> None:
        if source_index is not None and 0 <= source_index < len(self._fsects_by_section):
            if source_endtype in {"start", "end"}:
                self._fsects_by_section.insert(
                    index,
                    self._fsect_edge_profile(source_index, source_endtype),
                )
            else:
                self._fsects_by_section.insert(
                    index, copy.deepcopy(self._fsects_by_section[source_index])
                )
        else:
            self._fsects_by_section.insert(index, [])

    def _closed_loop_order(self, sections: list[SectionPreview]) -> list[int]:
        if not is_closed_loop(sections):
            return []
        order: list[int] = []
        visited: set[int] = set()
        index = 0
        while index not in visited:
            visited.add(index)
            order.append(index)
            index = sections[index].next_id
        return order
