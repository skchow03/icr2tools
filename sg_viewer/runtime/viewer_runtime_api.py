from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable

from icr2_core.trk.utils import approx_curve_length
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.model.edit_commands import (
    ReplaceTrackSnapshotCommand,
    TrackEditSnapshot,
)
from sg_viewer.model.edit_manager import EditManager
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.preview_mutations import translate_section
from sg_viewer.runtime.preview_geometry_service import (
    ConnectNodesRequest,
    ConnectionSolveRequest,
    NodeDisconnectRequest,
    NodeDragRequest,
    PreviewGeometryService,
    StartFinishRequest,
)


@dataclass(frozen=True)
class RuntimeSelectionDelta:
    selected_before: int | None = None
    selected_after: int | None = None


@dataclass(frozen=True)
class RuntimeUpdatePayload:
    updated_sections: list[SectionPreview] | None = None
    changed_indices: list[int] = field(default_factory=list)
    last_dragged_indices: list[int] = field(default_factory=list)
    selection_delta: RuntimeSelectionDelta | None = None
    status_messages: list[str] = field(default_factory=list)
    validation_messages: list[str] = field(default_factory=list)
    closed_loop_transition: bool = False


class ViewerRuntimeApi:
    """High-level runtime interface for preview/UI edit intents."""

    def __init__(
        self,
        *,
        preview_context: PreviewContext | None = None,
        geometry_service: PreviewGeometryService | None = None,
        edit_manager: EditManager | None = None,
        snapshot_provider: Callable[[], TrackEditSnapshot] | None = None,
        restore_snapshot: Callable[[TrackEditSnapshot], list[SectionPreview]] | None = None,
    ) -> None:
        self._preview_context = preview_context
        self._geometry_service = geometry_service or PreviewGeometryService()
        self._edit_manager = edit_manager or EditManager()
        self._snapshot_provider = snapshot_provider
        self._restore_snapshot = restore_snapshot

    def _commit_track_edit(self, command: ReplaceTrackSnapshotCommand) -> list[SectionPreview]:
        return self._edit_manager.execute(command)

    def commit_sections(
        self,
        *,
        before: list[SectionPreview],
        after: list[SectionPreview],
        changed_indices: list[int] | None = None,
    ) -> RuntimeUpdatePayload:
        if self._snapshot_provider is None or self._restore_snapshot is None:
            raise RuntimeError("ViewerRuntimeApi.commit_sections requires snapshot provider and restore callback")
        before_snapshot = self._snapshot_provider()
        before_snapshot = replace(before_snapshot, sections=list(before))
        after_snapshot = self._snapshot_provider()
        after_snapshot = replace(after_snapshot, sections=list(after))
        command = ReplaceTrackSnapshotCommand(
            before=before_snapshot,
            after=after_snapshot,
            restore_snapshot=self._restore_snapshot,
        )
        updated = self._commit_track_edit(command)
        return RuntimeUpdatePayload(
            updated_sections=updated,
            changed_indices=list(changed_indices or []),
        )

    def commit_snapshot(
        self,
        *,
        before: TrackEditSnapshot,
        after: TrackEditSnapshot,
        restore_snapshot: Callable[[TrackEditSnapshot], list[SectionPreview]],
    ) -> RuntimeUpdatePayload:
        command = ReplaceTrackSnapshotCommand(
            before=before,
            after=after,
            restore_snapshot=restore_snapshot,
        )
        updated = self._commit_track_edit(command)
        return RuntimeUpdatePayload(updated_sections=updated)

    def undo(self) -> RuntimeUpdatePayload:
        updated = self._edit_manager.undo()
        return RuntimeUpdatePayload(updated_sections=updated)

    def redo(self) -> RuntimeUpdatePayload:
        updated = self._edit_manager.redo()
        return RuntimeUpdatePayload(updated_sections=updated)

    def clear_history(self) -> None:
        self._edit_manager.clear()

    def set_start_finish_intent(
        self,
        *,
        sections: list[SectionPreview],
        hit: tuple[int, str],
    ) -> RuntimeUpdatePayload:
        response = self._geometry_service.set_start_finish(
            StartFinishRequest(sections=sections, hit=hit)
        )
        return RuntimeUpdatePayload(
            updated_sections=response.sections,
            status_messages=[response.status_message],
        )

    def disconnect_node_intent(
        self,
        *,
        sections: list[SectionPreview],
        node: tuple[int, str],
    ) -> RuntimeUpdatePayload:
        response = self._geometry_service.disconnect_node(
            NodeDisconnectRequest(sections=sections, node=node)
        )
        return RuntimeUpdatePayload(
            updated_sections=response.sections,
            changed_indices=list(response.changed_indices or []),
        )

    def connect_nodes_intent(
        self,
        *,
        sections: list[SectionPreview],
        source: tuple[int, str],
        target: tuple[int, str],
    ) -> RuntimeUpdatePayload:
        response = self._geometry_service.connect_nodes(
            ConnectNodesRequest(sections=sections, source=source, target=target)
        )
        return RuntimeUpdatePayload(
            updated_sections=response.sections,
            changed_indices=list(response.changed_indices or []),
        )

    def solve_connection_intent(
        self,
        *,
        sections: list[SectionPreview],
        source: tuple[int, str],
        target: tuple[int, str],
    ) -> RuntimeUpdatePayload:
        response = self._geometry_service.solve_connection(
            ConnectionSolveRequest(sections=sections, source=source, target=target)
        )
        status = [response.status_message] if response.status_message else []
        return RuntimeUpdatePayload(
            updated_sections=response.sections,
            changed_indices=list(response.changed_indices or []),
            status_messages=status,
        )

    def drag_node_intent(
        self,
        *,
        sections: list[SectionPreview],
        active_node: tuple[int, str],
        track_point: tuple[float, float],
        can_drag_node: bool,
    ) -> RuntimeUpdatePayload:
        response = self._geometry_service.update_dragged_section(
            NodeDragRequest(
                sections=sections,
                active_node=active_node,
                track_point=track_point,
                can_drag_node=can_drag_node,
            )
        )
        return RuntimeUpdatePayload(
            updated_sections=response.sections,
            changed_indices=list(response.changed_indices or []),
            last_dragged_indices=list(response.last_dragged_indices or []),
        )

    def apply_closure_transition_intent(
        self,
        *,
        old_sections: list[SectionPreview],
        updated_sections: list[SectionPreview],
        changed_indices: list[int],
    ) -> RuntimeUpdatePayload:
        response = self._geometry_service.apply_closure_transition(
            old_sections=old_sections,
            updated_sections=updated_sections,
            changed_indices=changed_indices,
        )
        status = [response.status_message] if response.status_message else []
        return RuntimeUpdatePayload(
            updated_sections=response.sections,
            changed_indices=list(response.changed_indices or []),
            status_messages=status,
            closed_loop_transition=response.closed_loop_transition,
        )

    def move_sections_intent(
        self,
        *,
        sections: list[SectionPreview],
        chain_indices: list[int],
        dx: float,
        dy: float,
    ) -> RuntimeUpdatePayload:
        moved_sections = list(sections)
        for chain_index in chain_indices:
            if 0 <= chain_index < len(moved_sections):
                translated = translate_section(sections[chain_index], dx, dy)
                moved_sections[chain_index] = self._geometry_service.refresh_section_geometry(translated)
        return RuntimeUpdatePayload(updated_sections=moved_sections, changed_indices=list(chain_indices))

    def validate_sections(self, sections: list[SectionPreview]) -> RuntimeUpdatePayload:
        self._geometry_service.validate_sections(sections)
        return RuntimeUpdatePayload(updated_sections=sections)

    def can_start_shared_node_drag(self, node: tuple[int, str], sections: list[SectionPreview]) -> bool:
        return self._geometry_service.can_start_shared_node_drag(node, sections)

    def recalculate_elevations_intent(
        self,
        *,
        changed_indices: list[int] | None,
        recalculate: Callable[[list[int] | None], None] | None,
    ) -> RuntimeUpdatePayload:
        if recalculate is not None:
            recalculate(changed_indices)
        return RuntimeUpdatePayload(changed_indices=list(changed_indices or []))

    def fsect_edit_intent(self, action: Callable[[], None], status_message: str | None = None) -> RuntimeUpdatePayload:
        action()
        return RuntimeUpdatePayload(status_messages=[status_message] if status_message else [])

    def xsect_edit_intent(self, action: Callable[[], None], status_message: str | None = None) -> RuntimeUpdatePayload:
        action()
        return RuntimeUpdatePayload(status_messages=[status_message] if status_message else [])

    def track_metrics_intent(self, sections: list[SectionPreview]) -> RuntimeUpdatePayload:
        if not sections:
            return RuntimeUpdatePayload(status_messages=["Track Length: –"])
        if not is_closed_loop(sections):
            return RuntimeUpdatePayload(status_messages=["Track Length: Not a closed loop"])
        try:
            return RuntimeUpdatePayload(status_messages=[str(loop_length(sections))])
        except ValueError:
            return RuntimeUpdatePayload(status_messages=["Track Length: Not a closed loop"])

    @staticmethod
    def approx_curve_length_intent(
        grade1: int,
        grade2: int,
        grade3: int,
        centerline_altitude: float,
        section_length: int,
    ) -> float:
        return approx_curve_length(grade1, grade2, grade3, centerline_altitude, section_length)
