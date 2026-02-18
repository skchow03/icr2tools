from __future__ import annotations

from sg_viewer.ui.elevation_profile import ElevationProfileData


class ElevationController:
    """Tracks elevation profile UI state for drag/edit bound locking."""

    def __init__(self) -> None:
        self.current_profile: ElevationProfileData | None = None
        self.profile_dragging = False
        self.profile_editing = False

    def reset(self) -> None:
        self.current_profile = None
        self.profile_dragging = False
        self.profile_editing = False

    def begin_drag(self) -> bool:
        if self.profile_dragging:
            return False
        self.profile_dragging = True
        return True

    def end_drag(self) -> bool:
        if not self.profile_dragging:
            return False
        self.profile_dragging = False
        return True

    def begin_edit(self) -> bool:
        if self.profile_editing:
            return False
        self.profile_editing = True
        return True

    def end_edit(self) -> bool:
        if not self.profile_editing:
            return False
        self.profile_editing = False
        return True

    def should_lock_bounds(self) -> bool:
        return (
            (self.profile_dragging or self.profile_editing)
            and self.current_profile is not None
        )
