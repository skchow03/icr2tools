from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from sg_viewer.model.edit_commands import TrackEditSnapshot

if TYPE_CHECKING:
    from sg_viewer.preview.runtime import PreviewRuntime


class TrackStateSnapshotHelper:
    """Shared snapshot/restore helpers for unified track edit history."""

    def snapshot_track_state(self, runtime: "PreviewRuntime") -> TrackEditSnapshot:
        topology = runtime._snapshot_topology_state()
        sections: list = []
        start_finish_dlong = None
        if isinstance(topology, dict):
            sections = copy.deepcopy(list(topology.get("sections", [])))
            start_finish_dlong = topology.get("start_finish_dlong")
        return TrackEditSnapshot(
            sections=sections,
            start_finish_dlong=start_finish_dlong,
            fsects_by_section=self.snapshot_fsects(runtime),
            elevation_state=self.snapshot_elevation_state(runtime),
        )

    def restore_track_state(self, runtime: "PreviewRuntime", snapshot: TrackEditSnapshot) -> list:
        runtime._fsects_by_section = copy.deepcopy(snapshot.fsects_by_section)
        runtime._restore_topology_state(
            {
                "sections": copy.deepcopy(snapshot.sections),
                "start_finish_dlong": snapshot.start_finish_dlong,
            }
        )
        runtime._validate_section_fsects_alignment()
        self.restore_elevation_state(runtime, snapshot.elevation_state)
        runtime._bump_sg_version()
        runtime._has_unsaved_changes = True
        if runtime._emit_sections_changed is not None:
            runtime._emit_sections_changed()
        if not runtime.refresh_fsections_preview():
            runtime._context.request_repaint()
        return copy.deepcopy(runtime._section_manager.sections)

    def snapshot_fsects(self, runtime: "PreviewRuntime") -> list[list[object]]:
        return [copy.deepcopy(fsects) for fsects in runtime._fsects_by_section]

    def snapshot_elevation_state(self, runtime: "PreviewRuntime") -> dict[str, object] | None:
        sg_data = runtime._document.sg_data
        if sg_data is None:
            return None
        header = list(getattr(sg_data, "header", []))
        return {
            "num_xsects": int(getattr(sg_data, "num_xsects", 0)),
            "xsect_dlats": list(getattr(sg_data, "xsect_dlats", [])),
            "header": header,
            "sections": [
                {
                    "alt": list(getattr(section, "alt", [])),
                    "grade": list(getattr(section, "grade", [])),
                }
                for section in getattr(sg_data, "sects", [])
            ],
        }

    def restore_elevation_state(self, runtime: "PreviewRuntime", state: dict[str, object] | None) -> None:
        if state is None:
            return
        sg_data = runtime._document.sg_data
        if sg_data is None:
            return

        sections = list(getattr(sg_data, "sects", []))
        snapshot_sections = list(state.get("sections", []))
        if len(sections) != len(snapshot_sections):
            return

        sg_data.num_xsects = int(state.get("num_xsects", sg_data.num_xsects))
        if len(getattr(sg_data, "header", [])) > 5:
            header = list(state.get("header", []))
            if len(header) > 5:
                sg_data.header[5] = int(header[5])
            else:
                sg_data.header[5] = int(sg_data.num_xsects)

        xsect_dlats = state.get("xsect_dlats", [])
        dtype = getattr(getattr(sg_data, "xsect_dlats", None), "dtype", None)
        if dtype is not None:
            try:
                import numpy as np

                sg_data.xsect_dlats = np.array(xsect_dlats, dtype=dtype)
            except Exception:
                sg_data.xsect_dlats = list(xsect_dlats)
        else:
            sg_data.xsect_dlats = list(xsect_dlats)

        for section, snapshot_section in zip(sections, snapshot_sections):
            if not isinstance(snapshot_section, dict):
                continue
            section.alt = list(snapshot_section.get("alt", []))
            section.grade = list(snapshot_section.get("grade", []))
