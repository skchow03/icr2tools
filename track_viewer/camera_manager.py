"""Camera state and editing helpers for the track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5 import QtCore

from icr2_core.cam.helpers import CameraPosition, Type6CameraParameters, Type7CameraParameters
from track_viewer.camera_models import CameraViewEntry, CameraViewListing
from track_viewer.track_data_loader import CameraData


class CameraManager(QtCore.QObject):
    """Encapsulate camera state and editing logic."""

    camerasChanged = QtCore.pyqtSignal(list, list)
    selectedCameraChanged = QtCore.pyqtSignal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self._cameras: list[CameraPosition] = []
        self._camera_views: list[CameraViewListing] = []
        self._archived_views: list[CameraViewListing] = []
        self._selected_camera: int | None = None
        self._tv_mode_count = 0
        self._camera_source: str | None = None
        self._camera_files_from_dat = False
        self._dat_path: Path | None = None
        self._track_length: float | None = None

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------
    @property
    def cameras(self) -> list[CameraPosition]:
        return self._cameras

    @property
    def camera_views(self) -> list[CameraViewListing]:
        return self._camera_views

    @property
    def selected_camera(self) -> int | None:
        return self._selected_camera

    @property
    def tv_mode_count(self) -> int:
        return self._tv_mode_count

    @property
    def camera_source(self) -> str | None:
        return self._camera_source

    @property
    def camera_files_from_dat(self) -> bool:
        return self._camera_files_from_dat

    @property
    def dat_path(self):
        return self._dat_path

    def reset(self) -> None:
        self._cameras = []
        self._camera_views = []
        self._archived_views = []
        self._selected_camera = None
        self._tv_mode_count = 0
        self._camera_source = None
        self._camera_files_from_dat = False
        self._dat_path = None
        self._track_length = None
        self.camerasChanged.emit([], [])
        self.selectedCameraChanged.emit(None, None)

    def set_track_length(self, length: float | None) -> None:
        self._track_length = length

    def set_camera_data(self, camera_data: CameraData) -> None:
        self._cameras = list(camera_data.cameras)
        self._camera_views = list(camera_data.camera_views)
        self._archived_views = []
        self._tv_mode_count = len(self._camera_views)
        self._selected_camera = None
        self._camera_source = camera_data.camera_source
        self._camera_files_from_dat = camera_data.camera_files_from_dat
        self._dat_path = camera_data.dat_path
        self._renumber_camera_type_indices()
        self.camerasChanged.emit(self._cameras, self._camera_views)
        self.selectedCameraChanged.emit(None, None)

    def set_tv_mode_count(self, count: int) -> None:
        if not self._camera_views:
            return
        clamped_count = max(1, min(2, count))
        if clamped_count == self._tv_mode_count:
            return

        if clamped_count == 1:
            if len(self._camera_views) > 1:
                self._archived_views = self._camera_views[1:]
            self._camera_views = self._camera_views[:1]
        elif clamped_count == 2:
            if len(self._camera_views) > 2:
                self._camera_views = self._camera_views[:2]
                self._archived_views = []
            elif len(self._camera_views) == 1:
                restored_view = None
                if self._archived_views:
                    restored_view = self._archived_views.pop(0)
                if restored_view is not None:
                    self._camera_views.append(restored_view)
                else:
                    source_view = self._camera_views[0]
                    copied_entries = [
                        CameraViewEntry(
                            camera_index=entry.camera_index,
                            type_index=entry.type_index,
                            camera_type=entry.camera_type,
                            start_dlong=entry.start_dlong,
                            end_dlong=entry.end_dlong,
                            mark=entry.mark,
                        )
                        for entry in source_view.entries
                    ]
                    self._camera_views.append(
                        CameraViewListing(view=2, label="TV2", entries=copied_entries)
                    )

        for index, view in enumerate(self._camera_views, start=1):
            view.view = index
            view.label = f"TV{index}"

        self._tv_mode_count = len(self._camera_views)
        self.camerasChanged.emit(self._cameras, self._camera_views)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------
    def set_selected_camera(self, index: int | None) -> None:
        if index == self._selected_camera:
            return
        if index is not None:
            if index < 0 or index >= len(self._cameras):
                index = None
        self._selected_camera = index
        self._emit_selected_camera()

    def update_camera_position(
        self, camera_index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._cameras):
            return
        camera = self._cameras[camera_index]
        if x is not None:
            camera.x = int(x)
        if y is not None:
            camera.y = int(y)
        if z is not None:
            camera.z = int(z)
        if self._selected_camera == camera_index:
            self._emit_selected_camera()
        self.camerasChanged.emit(self._cameras, self._camera_views)

    def update_camera_dlongs(
        self, camera_index: int, start_dlong: Optional[int], end_dlong: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._cameras):
            return
        if self._selected_camera == camera_index:
            self._emit_selected_camera()
        self.camerasChanged.emit(self._cameras, self._camera_views)

    # ------------------------------------------------------------------
    # Camera insertion helpers
    # ------------------------------------------------------------------
    def add_type6_camera(self) -> tuple[bool, str]:
        if not self._cameras:
            return False, "No cameras are loaded."
        if self._selected_camera is None:
            return False, "Select a camera before adding a new one."
        view_entry = self._find_camera_entry(self._selected_camera)
        if view_entry is None:
            return False, "The selected camera is not part of any TV camera mode."

        view_index, entry_index = view_entry
        view = self._camera_views[view_index]
        if not view.entries:
            return False, "No TV camera entries are available to place the new camera."

        base_camera = self._cameras[self._selected_camera]
        insert_index = self._selected_camera + 1
        previous_entry = view.entries[entry_index]
        next_index = (entry_index + 1) % len(view.entries)
        next_entry = view.entries[next_index]
        start_dlong = self._interpolated_dlong(
            previous_entry.start_dlong, next_entry.start_dlong
        )
        end_dlong = self._interpolated_dlong(previous_entry.end_dlong, next_entry.end_dlong)

        new_type6 = Type6CameraParameters(
            roll=0,
            pitch=0,
            yaw=0,
            zoom=0,
            unused=0,
        )

        new_camera = CameraPosition(
            camera_type=6,
            index=0,
            x=base_camera.x + 30000,
            y=base_camera.y + 30000,
            z=base_camera.z,
            type6=new_type6,
            raw_values=tuple([0] * 12),
        )

        insert_index = self._insert_camera_at_index(insert_index, new_camera)
        view.entries.insert(
            next_index,
            CameraViewEntry(
                camera_index=insert_index,
                type_index=new_camera.index,
                camera_type=6,
                start_dlong=start_dlong,
                end_dlong=end_dlong,
                mark=6,
            ),
        )
        self._renumber_camera_type_indices()
        self.set_selected_camera(insert_index)
        self.camerasChanged.emit(self._cameras, self._camera_views)
        return True, "Type 6 camera added."

    def add_type7_camera(self) -> tuple[bool, str]:
        if not self._cameras:
            return False, "No cameras are loaded."
        if self._selected_camera is None:
            return False, "Select a camera before adding a new one."
        view_entry = self._find_camera_entry(self._selected_camera)
        if view_entry is None:
            return False, "The selected camera is not part of any TV camera mode."

        view_index, entry_index = view_entry
        view = self._camera_views[view_index]
        if not view.entries:
            return False, "No TV camera entries are available to place the new camera."

        base_camera = self._cameras[self._selected_camera]
        insert_index = self._selected_camera + 1
        next_index = (entry_index + 1) % len(view.entries)
        previous_entry = view.entries[entry_index]
        next_entry = view.entries[next_index]
        start_dlong = self._interpolated_dlong(
            previous_entry.start_dlong, next_entry.start_dlong
        )
        end_dlong = self._interpolated_dlong(previous_entry.end_dlong, next_entry.end_dlong)

        if start_dlong is not None:
            previous_entry.end_dlong = start_dlong
        if end_dlong is not None:
            next_entry.start_dlong = end_dlong

        base_type7 = base_camera.type7
        new_type7 = Type7CameraParameters(
            z_axis_rotation=base_type7.z_axis_rotation if base_type7 else 0,
            vertical_rotation=base_type7.vertical_rotation if base_type7 else 0,
            tilt=base_type7.tilt if base_type7 else 0,
            zoom=base_type7.zoom if base_type7 else 0,
            unknown1=base_type7.unknown1 if base_type7 else 0,
            unknown2=base_type7.unknown2 if base_type7 else 0,
            unknown3=base_type7.unknown3 if base_type7 else 0,
            unknown4=base_type7.unknown4 if base_type7 else 0,
        )

        new_camera = CameraPosition(
            camera_type=7,
            index=0,
            x=base_camera.x + 60000,
            y=base_camera.y + 60000,
            z=base_camera.z,
            type7=new_type7,
            raw_values=tuple([0] * 12),
        )

        insert_index = self._insert_camera_at_index(insert_index, new_camera)
        view.entries.insert(
            next_index,
            CameraViewEntry(
                camera_index=insert_index,
                type_index=new_camera.index,
                camera_type=7,
                start_dlong=start_dlong,
                end_dlong=end_dlong,
                mark=7,
            ),
        )
        self._renumber_camera_type_indices()
        self.set_selected_camera(insert_index)
        self.camerasChanged.emit(self._cameras, self._camera_views)
        return True, "Type 7 camera added."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _interpolated_dlong(
        self, previous: Optional[int], next_val: Optional[int]
    ) -> Optional[int]:
        if previous is None:
            return next_val
        if next_val is None:
            return previous
        if self._track_length is None:
            return None
        half_track = self._track_length / 2
        difference = next_val - previous
        if difference > half_track:
            difference -= self._track_length
        elif difference < -half_track:
            difference += self._track_length
        return previous + difference // 2

    def _find_camera_entry(self, camera_index: int) -> tuple[int, int] | None:
        for view_index, view in enumerate(self._camera_views):
            for entry_index, entry in enumerate(view.entries):
                if entry.camera_index == camera_index:
                    return view_index, entry_index
        return None

    def _insert_camera_at_index(self, index: int, camera: CameraPosition) -> int:
        insert_index = max(0, min(index, len(self._cameras)))
        self._cameras.insert(insert_index, camera)
        for view in self._camera_views:
            for entry in view.entries:
                if entry.camera_index is not None and entry.camera_index >= insert_index:
                    entry.camera_index += 1
        return insert_index

    def _renumber_camera_type_indices(self) -> None:
        type_counts: dict[int, int] = {}
        for camera in self._cameras:
            count = type_counts.get(camera.camera_type, 0)
            camera.index = count
            type_counts[camera.camera_type] = count + 1
        for view in self._camera_views:
            for entry in view.entries:
                if entry.camera_index is None:
                    continue
                if entry.camera_index < 0 or entry.camera_index >= len(self._cameras):
                    continue
                camera = self._cameras[entry.camera_index]
                if entry.camera_type is None or entry.camera_type == camera.camera_type:
                    entry.type_index = camera.index

    def _emit_selected_camera(self) -> None:
        selected = None
        index = self._selected_camera
        if index is not None and 0 <= index < len(self._cameras):
            selected = self._cameras[index]
        self.selectedCameraChanged.emit(index, selected)
