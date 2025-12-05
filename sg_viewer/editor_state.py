# sg_viewer/editor_state.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import math

import copy

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer import preview_loader, sg_geometry


@dataclass
class Node:
    id: int
    x: float
    y: float
    attached_sections: set[int]


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
    nodes: Dict[int, Node]
    next_node_id: int

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
        nodes, next_node_id = cls._build_nodes(data.sgfile)
        return cls(
            path=path,
            sg=data.sgfile,
            trk=data.trk,
            preview=data,
            nodes=nodes,
            next_node_id=next_node_id,
        )

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

        # Refresh nodes to reflect the latest section geometry
        self.nodes, self.next_node_id = self._build_nodes(self.sg)

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------
    @classmethod
    def _build_nodes(cls, sgfile: SGFile) -> tuple[Dict[int, Node], int]:
        """Build nodes from SG section endpoints and attach section references."""

        nodes: Dict[int, Node] = {}
        next_node_id = 0
        coord_to_id: Dict[Tuple[int, int], int] = {}

        def get_or_create_node_id(x: int, y: int) -> int:
            nonlocal next_node_id
            coord = (round(x), round(y))
            if coord in coord_to_id:
                return coord_to_id[coord]

            node_id = next_node_id
            coord_to_id[coord] = node_id
            nodes[node_id] = Node(id=node_id, x=float(x), y=float(y), attached_sections=set())
            next_node_id += 1
            return node_id

        for idx, sec in enumerate(sgfile.sects):
            start_node_id = get_or_create_node_id(getattr(sec, "start_x", 0), getattr(sec, "start_y", 0))
            end_node_id = get_or_create_node_id(getattr(sec, "end_x", 0), getattr(sec, "end_y", 0))

            sec.start_node_id = start_node_id
            sec.end_node_id = end_node_id

            for node_id in (start_node_id, end_node_id):
                node = nodes[node_id]
                if idx not in node.attached_sections:
                    node.attached_sections.add(idx)

        return nodes, next_node_id

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

    def update_straight_from_nodes(self, section_index: int) -> None:
        sec = self.sg.sects[section_index]
        if sec.type != 1:
            return

        sn = self.nodes[sec.start_node_id]
        en = self.nodes[sec.end_node_id]

        sx, sy = sn.x, sn.y
        ex, ey = en.x, en.y

        # Update endpoints
        sec.start_x = sx
        sec.start_y = sy
        sec.end_x = ex
        sec.end_y = ey

        dx = ex - sx
        dy = ey - sy
        length = math.hypot(dx, dy)
        sec.dlong = int(length)

        # Heading
        heading = math.atan2(dy, dx)
        sec.sang1 = sg_geometry.sin_fixed(heading)
        sec.sang2 = sg_geometry.cos_fixed(heading)
        sec.eang1 = sec.sang1
        sec.eang2 = sec.sang2

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

    def detach_node_for_section(self, node_id: int, section_index: int) -> None:
        """Detach a section endpoint into a new node if the node has multiple attachments."""

        if section_index < 0 or section_index >= len(self.sg.sects):
            return

        node = self.nodes.get(node_id)
        if (
            node is None
            or len(node.attached_sections) <= 1
            or section_index not in node.attached_sections
        ):
            return

        new_id = self.next_node_id
        self.next_node_id += 1

        new_node = Node(
            id=new_id,
            x=node.x,
            y=node.y,
            attached_sections={section_index},
        )
        self.nodes[new_id] = new_node

        sec = self.sg.sects[section_index]
        if getattr(sec, "start_node_id", None) == node_id:
            sec.start_node_id = new_id
        elif getattr(sec, "end_node_id", None) == node_id:
            sec.end_node_id = new_id

        node.attached_sections.discard(section_index)

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
