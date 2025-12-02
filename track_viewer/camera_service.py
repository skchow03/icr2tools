"""Service wrapper for camera loading, saving, and mutations."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from icr2_core.cam.helpers import CameraPosition
from track_viewer.camera_controller import CameraController
from track_viewer.camera_models import CameraViewListing
from track_viewer.io_service import CameraLoadResult, TrackIOService


class CameraService:
    """Coordinate camera persistence and mutations for the preview widget."""

    def __init__(
        self,
        io_service: TrackIOService | None = None,
        camera_controller: CameraController | None = None,
    ) -> None:
        self._io_service = io_service or TrackIOService()
        self._camera_controller = camera_controller or CameraController()
        self._track_folder: Path | None = None
        self._cameras: list[CameraPosition] = []
        self._camera_views: list[CameraViewListing] = []
        self._archived_camera_views: list[CameraViewListing] = []
        self._camera_source: str | None = None
        self._camera_files_from_dat = False
        self._dat_path: Path | None = None
        self._tv_mode_count = 0

    @property
    def cameras(self) -> list[CameraPosition]:
        return self._cameras

    @property
    def camera_views(self) -> list[CameraViewListing]:
        return self._camera_views

    @property
    def archived_camera_views(self) -> list[CameraViewListing]:
        return self._archived_camera_views

    @property
    def tv_mode_count(self) -> int:
        return self._tv_mode_count

    def reset(self) -> None:
        """Reset any loaded camera state."""

        self._track_folder = None
        self._cameras = []
        self._camera_views = []
        self._archived_camera_views = []
        self._camera_source = None
        self._camera_files_from_dat = False
        self._dat_path = None
        self._tv_mode_count = 0

    def load_for_track(self, track_folder: Path | None) -> CameraLoadResult | None:
        """Load cameras for a track folder and cache the results."""

        self.reset()
        if not track_folder:
            return None

        try:
            camera_data = self._io_service.load_cameras(track_folder)
        except Exception:
            return None

        self._track_folder = track_folder
        self._dat_path = camera_data.dat_path
        self._camera_source = camera_data.camera_source
        self._camera_files_from_dat = camera_data.camera_files_from_dat
        self._cameras = camera_data.cameras
        self._camera_views = camera_data.camera_views
        self._tv_mode_count = camera_data.tv_mode_count
        return camera_data

    def save(self) -> str:
        """Persist loaded camera data to disk."""

        if self._track_folder is None:
            raise ValueError("No track is currently loaded.")

        return self._io_service.save_cameras(
            self._track_folder,
            self._cameras,
            self._camera_views,
            self._camera_source,
            self._dat_path,
            self._camera_files_from_dat,
        )

    def set_tv_mode_count(self, count: int) -> int:
        """Update the active TV mode count and archive/restore views."""

        if not self._camera_views:
            return self._tv_mode_count

        (
            self._camera_views,
            self._archived_camera_views,
            self._tv_mode_count,
        ) = self._camera_controller.set_tv_mode_count(
            self._camera_views, self._archived_camera_views, count
        )
        return self._tv_mode_count

    def add_type6_camera(
        self, selected_camera: int | None, track_length: float | None
    ) -> tuple[bool, str, int | None]:
        """Create a new type 6 camera relative to the selection."""

        result = self._camera_controller.add_type6_camera(
            self._cameras, self._camera_views, selected_camera, track_length
        )
        return result.success, result.message, result.selected_camera

    def add_type7_camera(
        self, selected_camera: int | None, track_length: float | None
    ) -> tuple[bool, str, int | None]:
        """Create a new type 7 camera relative to the selection."""

        result = self._camera_controller.add_type7_camera(
            self._cameras, self._camera_views, selected_camera, track_length
        )
        return result.success, result.message, result.selected_camera

    def renumber(
        self, cameras: Sequence[CameraPosition], camera_views: Sequence[CameraViewListing]
    ) -> tuple[list[CameraPosition], list[CameraViewListing]]:
        """Expose controller renumbering for callers that need it."""

        return self._camera_controller.renumber(list(cameras), list(camera_views))
