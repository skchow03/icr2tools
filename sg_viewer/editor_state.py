# sg_viewer/editor_state.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import math

import copy

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer import preview_loader, sg_geometry


@dataclass
class EditorState:
    """
    EditorState owns the mutable SGFile, the derived TRKFile, and the latest
    PreviewData snapshot. All edits flow through here.

    Typical flow:

      state = EditorState.from_path(path)
      state.set_section_length(5, 120000)
      widget.refresh_from_state(state)  # rebinds preview fields and repaints
    """

    path: Path
    sg: SGFile
    trk: TRKFile
    preview: preview_loader.PreviewData

    max_undo: int = 50
    _undo_stack: List[SGFile] = field(default_factory=list, repr=False)
    _redo_stack: List[SGFile] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def from_path(cls, path: Path) -> "EditorState":
        """
        Load SG + TRK + preview data from disk.

        Uses the existing preview_loader.load_preview() helper so we leverage
        your current sampling + curve marker code.
        """
        data = preview_loader.load_preview(path)
        return cls(path=path, sg=data.sgfile, trk=data.trk, preview=data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _push_undo(self) -> None:
        """
        Save a deep copy of the current SGFile to the undo stack.
        Clears the redo stack (standard undo semantics).
        """
        self._redo_stack.clear()
        self._undo_stack.append(copy.deepcopy(self.sg))
        if len(self._undo_stack) > self.max_undo:
            self._undo_stack.pop(0)

    def _restore_sg(self, sg_snapshot: SGFile) -> None:
        """
        Replace the current SGFile with a snapshot and rebuild TRK/preview.
        """
        self.sg = copy.deepcopy(sg_snapshot)
        self._rebuild_from_sg()

    def _rebuild_from_sg(self) -> None:
        """
        Regenerate TRK and PreviewData from the in-memory SG without writing.

        SG remains the source of truth and we rebuild dependent data after
        each edit while keeping the on-disk file untouched.
        """

        # Regenerate TRK from updated SG
        self.trk = TRKFile.from_sgfile(self.sg)

        # Rebuild preview snapshot
        self.preview = preview_loader.load_preview_from_objects(self.sg, self.trk, self.path)

    # ------------------------------------------------------------------
    # Public edit operations
    # ------------------------------------------------------------------
    def set_section_length(self, index: int, new_length: float) -> None:
        """
        Change section length and recompute geometry + preview.
        """
        if index < 0 or index >= self.sg.num_sects:
            return
        self._push_undo()
        sg_geometry.update_section_length(self.sg, index, new_length)
        self._rebuild_from_sg()

    def set_section_radius(self, index: int, new_radius: float) -> None:
        """
        Change curve radius (for type=2 sections) and recompute geometry + preview.
        """
        if index < 0 or index >= self.sg.num_sects:
            return
        self._push_undo()
        sg_geometry.update_section_radius(self.sg, index, new_radius)
        self._rebuild_from_sg()

    def set_curve_center(self, index: int, new_center_x: float, new_center_y: float) -> None:
        """
        Change curve centre (for type=2 sections) and recompute geometry + preview.
        """
        if index < 0 or index >= self.sg.num_sects:
            return
        self._push_undo()
        sg_geometry.update_curve_center(self.sg, index, new_center_x, new_center_y)
        self._rebuild_from_sg()

    def set_section_start_heading_deg(self, index: int, new_heading_deg: float) -> None:
        """
        Change the starting heading (in degrees) for a section and recompute.
        """
        if index < 0 or index >= self.sg.num_sects:
            return
        self._push_undo()
        theta = math.radians(new_heading_deg)
        sg_geometry.update_section_start_heading(self.sg, index, theta)
        self._rebuild_from_sg()

    def commit_endpoint_move(
        self, section_index: int, endpoint_type: str, new_x: float, new_y: float
    ) -> None:
        """
        Apply final endpoint geometry after a drag operation.
        This is called on mouse release in move-point mode.

        Behavior:
        - If moving the END of a straight:
            * Recompute length from start->new_end.
            * Update heading from start->new_end.
        - If moving the START of a straight:
            * Shift start, recompute length, update heading.
        - For curves (type=2):
            * For now: only update end point and recompute end heading.
              (Phase 1: no curve fitting yet)
        - Call recompute_chain() from sg_geometry.
        - Push undo BEFORE mutation.
        - Rebuild TRK + preview afterward.
        """

        if section_index < 0 or section_index >= self.sg.num_sects:
            return

        self._push_undo()

        sec = self.sg.sects[section_index]
        etype = endpoint_type.lower()
        sec_type = getattr(sec, "type", 1)
        target_x = float(new_x)
        target_y = float(new_y)

        if sec_type == 1:
            # Straight section handling
            if etype == "end":
                start_x = float(sec.start_x)
                start_y = float(sec.start_y)
                sec.end_x = int(round(target_x))
                sec.end_y = int(round(target_y))

                dx = target_x - start_x
                dy = target_y - start_y
                if dx != 0.0 or dy != 0.0:
                    theta = math.atan2(dy, dx)
                    sec.sang1, sec.sang2 = sg_geometry._sincos_from_heading(theta)
                    sec.eang1, sec.eang2 = sg_geometry._sincos_from_heading(theta)
                    sec.length = int(round(math.hypot(dx, dy)))
            elif etype == "start":
                end_x = float(sec.end_x)
                end_y = float(sec.end_y)
                sec.start_x = int(round(target_x))
                sec.start_y = int(round(target_y))

                dx = end_x - target_x
                dy = end_y - target_y
                if dx != 0.0 or dy != 0.0:
                    theta = math.atan2(dy, dx)
                    sec.sang1, sec.sang2 = sg_geometry._sincos_from_heading(theta)
                    sec.eang1, sec.eang2 = sg_geometry._sincos_from_heading(theta)
                    sec.length = int(round(math.hypot(dx, dy)))
        else:
            # Curve handling (Phase 1): only update end point + heading.
            if etype == "end":
                sec.end_x = int(round(target_x))
                sec.end_y = int(round(target_y))

                start_x = float(sec.start_x)
                start_y = float(sec.start_y)
                dx = target_x - start_x
                dy = target_y - start_y
                if dx != 0.0 or dy != 0.0:
                    theta_end = math.atan2(dy, dx)
                    sec.eang1, sec.eang2 = sg_geometry._sincos_from_heading(theta_end)
            elif etype == "start":
                sec.start_x = int(round(target_x))
                sec.start_y = int(round(target_y))

                end_x = float(sec.end_x)
                end_y = float(sec.end_y)
                dx = end_x - target_x
                dy = end_y - target_y
                if dx != 0.0 or dy != 0.0:
                    theta_start = math.atan2(dy, dx)
                    sec.sang1, sec.sang2 = sg_geometry._sincos_from_heading(theta_start)

        sg_geometry.recompute_chain(self.sg, section_index)
        self._rebuild_from_sg()

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> None:
        """
        Restore the last SG snapshot from the undo stack, push current SG to redo.
        """
        if not self._undo_stack:
            return

        current_snapshot = copy.deepcopy(self.sg)
        previous = self._undo_stack.pop()
        self._redo_stack.append(current_snapshot)

        self._restore_sg(previous)

    def redo(self) -> None:
        """
        Restore the last SG snapshot from the redo stack, push current SG to undo.
        """
        if not self._redo_stack:
            return

        current_snapshot = copy.deepcopy(self.sg)
        next_state = self._redo_stack.pop()
        self._undo_stack.append(current_snapshot)

        self._restore_sg(next_state)
