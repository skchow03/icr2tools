"""View-model for the track viewer's coordinate sidebar."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from icr2_core.cam.helpers import CameraPosition
from track_viewer.model.camera_models import CameraViewListing


@dataclass(frozen=True)
class CameraListState:
    labels: list[str]
    enabled: bool
    status_text: str
    selected_index: int | None


@dataclass(frozen=True)
class SelectedCameraState:
    details_html: str
    selected_index: int | None
    type6_camera: CameraPosition | None
    type7_camera: CameraPosition | None


class CoordinateSidebarViewModel:
    """Owns camera list state and detail formatting for the sidebar."""

    def __init__(self) -> None:
        self._cameras: list[CameraPosition] = []
        self._camera_views: list[CameraViewListing] = []
        self._selected_camera_index: int | None = None
        self._track_length: int | None = None
        self._show_current_tv_only = False
        self._current_tv_mode_index = 0
        self._visible_camera_indices: list[int] = []

    @property
    def cameras(self) -> list[CameraPosition]:
        return self._cameras

    @property
    def camera_views(self) -> list[CameraViewListing]:
        return self._camera_views

    @property
    def track_length(self) -> int | None:
        return self._track_length

    def set_track_length(self, track_length: Optional[int]) -> None:
        self._track_length = track_length if track_length is not None else None

    def set_cameras(
        self,
        cameras: list[CameraPosition],
        views: list[CameraViewListing],
    ) -> CameraListState:
        self._cameras = list(cameras)
        self._camera_views = list(views)
        self._selected_camera_index = None
        return self._build_camera_list_state()

    def set_camera_filter(
        self, show_current_tv_only: bool | None = None, tv_mode_index: int | None = None
    ) -> CameraListState:
        if show_current_tv_only is not None:
            self._show_current_tv_only = bool(show_current_tv_only)
        if tv_mode_index is not None:
            self._current_tv_mode_index = max(0, int(tv_mode_index))
        return self._build_camera_list_state()

    def resolve_camera_selection(self, index: int) -> int | None:
        if not self._visible_camera_indices:
            return None
        if index < 0 or index >= len(self._visible_camera_indices):
            return None
        return self._visible_camera_indices[index]

    def camera_for_index(self, index: int | None) -> CameraPosition | None:
        if index is None:
            return None
        if 0 <= index < len(self._cameras):
            return self._cameras[index]
        return None

    def update_selected_camera_details(
        self, index: int | None, camera: CameraPosition | None
    ) -> SelectedCameraState:
        if camera is None:
            self._selected_camera_index = None
            return SelectedCameraState(
                details_html="Select a camera to inspect.",
                selected_index=None,
                type6_camera=None,
                type7_camera=None,
            )
        self._selected_camera_index = index
        details = [
            f"Index: {camera.index}",
            f"Type: {self._format_camera_type(camera.camera_type)}",
        ]
        type6_camera = None
        type7_camera = None

        if camera.camera_type in {2, 6} and camera.type6 is not None:
            details.append("Panning parameters can be edited below.")
            type6_camera = camera

        if camera.camera_type == 7 and camera.type7 is not None:
            params = camera.type7
            details.append("Fixed parameters:")
            details.append(
                "Z-axis rotation: {0}, vertical rotation: {1}, tilt: {2}, zoom: {3}".format(
                    params.z_axis_rotation,
                    params.vertical_rotation,
                    params.tilt,
                    params.zoom,
                )
            )
            details.append(
                "Unknowns: {0}, {1}, {2}, {3}".format(
                    params.unknown1,
                    params.unknown2,
                    params.unknown3,
                    params.unknown4,
                )
            )
            type7_camera = camera

        return SelectedCameraState(
            details_html="<br>".join(details),
            selected_index=index,
            type6_camera=type6_camera,
            type7_camera=type7_camera,
        )

    def camera_needing_refresh(self, index: int) -> CameraPosition | None:
        if (
            self._selected_camera_index is not None
            and index == self._selected_camera_index
            and 0 <= index < len(self._cameras)
        ):
            return self._cameras[index]
        return None

    def list_index_for_camera(self, camera_index: int | None) -> int | None:
        if camera_index is None:
            return None
        try:
            return self._visible_camera_indices.index(camera_index)
        except ValueError:
            return None

    def _build_camera_list_state(self) -> CameraListState:
        if not self._cameras:
            self._visible_camera_indices = []
            return CameraListState(
                labels=["(No cameras found)"],
                enabled=False,
                status_text="This track does not define any camera positions.",
                selected_index=None,
            )
        self._visible_camera_indices = self._filtered_camera_indices()
        if not self._visible_camera_indices:
            return CameraListState(
                labels=["(No cameras in current TV mode)"],
                enabled=False,
                status_text="No cameras are assigned to the selected TV mode.",
                selected_index=None,
            )
        labels = [
            f"#{self._cameras[index].index} ({self._format_camera_type(self._cameras[index].camera_type)})"
            for index in self._visible_camera_indices
        ]
        selected_index = self.list_index_for_camera(self._selected_camera_index)
        return CameraListState(
            labels=labels,
            enabled=True,
            status_text="Select a camera to inspect.",
            selected_index=selected_index,
        )

    def _filtered_camera_indices(self) -> list[int]:
        if not self._show_current_tv_only:
            return list(range(len(self._cameras)))
        if (
            self._current_tv_mode_index < 0
            or self._current_tv_mode_index >= len(self._camera_views)
        ):
            return []
        view = self._camera_views[self._current_tv_mode_index]
        visible = {entry.camera_index for entry in view.entries}
        return [index for index in range(len(self._cameras)) if index in visible]

    @staticmethod
    def _format_camera_type(camera_type: int) -> str:
        if camera_type == 6:
            return "Pan"
        if camera_type == 2:
            return "Alt pan"
        if camera_type == 7:
            return "Fixed"
        return f"type {camera_type}"
