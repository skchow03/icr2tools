from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sg_viewer.model.track_model import TrackModel


class InteractionController:
    """Pure interaction state machine for section handle dragging."""

    def __init__(self, model: "TrackModel"):
        self.model = model
        self.current_interaction: int | None = None
        self.interaction_state: dict[str, object] = {}

    def start_drag(self, section_id: int, handle: str):
        """Begin an interaction on a section handle."""
        self.current_interaction = section_id
        self.interaction_state = {"handle": handle}

    def update_drag(self, x: float, y: float):
        """Update drag coordinates."""
        assert self.current_interaction is not None
        self.interaction_state["pos"] = (x, y)

    def end_drag(self):
        """Commit the drag edit back to the model."""
        sid = self.current_interaction
        handle = self.interaction_state["handle"]
        pos = self.interaction_state["pos"]

        if sid is None:
            raise RuntimeError("Cannot end drag when no interaction is active.")

        self.model.update_section_handle(sid, handle, pos)

        self.current_interaction = None
        self.interaction_state = {}
