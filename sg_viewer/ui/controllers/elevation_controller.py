from __future__ import annotations

from sg_viewer.ui.elevation_profile import ElevationProfileData


class ElevationController:
    """Tracks elevation profile UI state and dirty/refresh coordination."""

    def __init__(self) -> None:
        self.current_profile: ElevationProfileData | None = None
        self.deferred_profile_refresh = False
        self.profile_dragging = False
        self.profile_editing = False

    def defer_refresh_if_dragging(self, *, is_interaction_dragging: bool) -> bool:
        if is_interaction_dragging:
            self.deferred_profile_refresh = True
            return True
        return False

    def consume_deferred_refresh(self) -> bool:
        if not self.deferred_profile_refresh:
            return False
        self.deferred_profile_refresh = False
        return True

    def begin_drag(self) -> None:
        self.profile_dragging = True

    def end_drag(self) -> None:
        self.profile_dragging = False

    def begin_edit(self) -> None:
        self.profile_editing = True

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
