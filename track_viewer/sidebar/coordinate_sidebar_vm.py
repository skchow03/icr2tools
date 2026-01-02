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
        if not self._cameras:
            return CameraListState(
                labels=["(No cameras found)"],
                enabled=False,
                status_text="This track does not define any camera positions.",
                selected_index=None,
            )
        labels = [f"#{cam.index} (type {cam.camera_type})" for cam in self._cameras]
        return CameraListState(
            labels=labels,
            enabled=True,
            status_text="Select a camera to inspect.",
            selected_index=None,
        )

    def resolve_camera_selection(self, index: int) -> int | None:
        if not self._cameras or index < 0 or index >= len(self._cameras):
            return None
        return index

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
        details = [f"Index: {camera.index}", f"Type: {camera.camera_type}"]
        type6_camera = None
        type7_camera = None

        if camera.camera_type == 6 and camera.type6 is not None:
            details.append("Type 6 parameters can be edited below.")
            type6_camera = camera

        if camera.camera_type == 7 and camera.type7 is not None:
            params = camera.type7
            details.append("Type 7 parameters:")
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
