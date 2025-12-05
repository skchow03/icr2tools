# sg_viewer/editor_state.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

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
        Persist SG to disk, regenerate TRK from SG, and rebuild PreviewData.

        This keeps your viewer code unchanged: it still uses TRK + preview_loader.
        The only difference is that SG is now the source of truth and we
        regenerate TRK after each edit.
        """
        # Write current SG back to its file
        self.sg.output_sg(str(self.path))

        # Regenerate TRK from updated SG
        self.trk = TRKFile.from_sg(str(self.path))

        # Rebuild preview snapshot
        self.preview = preview_loader.load_preview(self.path)

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

    def set_section_start_heading_deg(self, index: int, new_heading_deg: float) -> None:
        """
        Change the starting heading (in degrees) for a section and recompute.
        """
        if index < 0 or index >= self.sg.num_sects:
            return
        self._push_undo()
        import math

        theta = math.radians(new_heading_deg)
        sg_geometry.update_section_start_heading(self.sg, index, theta)
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
