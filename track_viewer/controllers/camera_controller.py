"""Camera orchestration helpers for the track preview widget."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from icr2_core.cam.helpers import CameraPosition, Type6CameraParameters, Type7CameraParameters
from track_viewer.model.camera_models import CameraViewEntry, CameraViewListing


@dataclass
class CameraUpdateResult:
    """Result bundle for camera mutations."""

    success: bool
    message: str
    cameras: List[CameraPosition]
    camera_views: List[CameraViewListing]
    selected_camera: int | None = None


class CameraController:
    """Encapsulate camera CRUD and TV-mode coordination."""

    def _add_tv_camera(
        self,
        cameras: List[CameraPosition],
        camera_views: List[CameraViewListing],
        selected_camera: int | None,
        track_length: float | None,
        camera_type: int,
        build_camera_params: Callable[
            [CameraPosition, Optional[int], Optional[int]],
            Type6CameraParameters | Type7CameraParameters,
        ],
        raw_values_length: int,
        success_message: str,
    ) -> CameraUpdateResult:
        if not cameras:
            return CameraUpdateResult(False, "No cameras are loaded.", cameras, camera_views)
        if selected_camera is None:
            return CameraUpdateResult(
                False, "Select a camera before adding a new one.", cameras, camera_views
            )

        view_entry = self._find_camera_entry(camera_views, selected_camera)
        if view_entry is None:
            return CameraUpdateResult(
                False,
                "The selected camera is not part of any TV camera mode.",
                cameras,
                camera_views,
            )

        view_index, entry_index = view_entry
        view = camera_views[view_index]
        if not view.entries:
            return CameraUpdateResult(
                False, "No TV camera entries are available to place the new camera.", cameras, camera_views
            )

        base_camera = cameras[selected_camera]
        insert_index = selected_camera + 1
        next_index = (entry_index + 1) % len(view.entries)
        previous_entry = view.entries[entry_index]
        next_entry = view.entries[next_index]
        start_dlong = self._interpolated_dlong(
            previous_entry.start_dlong, next_entry.start_dlong, track_length
        )
        end_dlong = self._interpolated_dlong(previous_entry.end_dlong, next_entry.end_dlong, track_length)

        if start_dlong is not None:
            previous_entry.end_dlong = start_dlong
        if end_dlong is not None:
            next_entry.start_dlong = end_dlong

        new_camera_params = build_camera_params(base_camera, start_dlong, end_dlong)
        if camera_type == 6:
            new_camera = CameraPosition(
                camera_type=camera_type,
                index=0,
                x=base_camera.x + 60000,
                y=base_camera.y + 60000,
                z=base_camera.z,
                type6=new_camera_params,
                raw_values=tuple([0] * raw_values_length),
            )
        else:
            new_camera = CameraPosition(
                camera_type=camera_type,
                index=0,
                x=base_camera.x + 60000,
                y=base_camera.y + 60000,
                z=base_camera.z,
                type7=new_camera_params,
                raw_values=tuple([0] * raw_values_length),
            )

        insert_index = self._insert_camera_at_index(cameras, camera_views, insert_index, new_camera)
        view.entries.insert(
            next_index,
            CameraViewEntry(
                camera_index=insert_index,
                type_index=new_camera.index,
                camera_type=camera_type,
                start_dlong=start_dlong,
                end_dlong=end_dlong,
                mark=camera_type,
            ),
        )
        self._renumber_camera_type_indices(cameras, camera_views)

        return CameraUpdateResult(
            True,
            success_message,
            cameras,
            camera_views,
            selected_camera=insert_index,
        )

    def add_type6_camera(
        self,
        cameras: List[CameraPosition],
        camera_views: List[CameraViewListing],
        selected_camera: int | None,
        track_length: float | None,
    ) -> CameraUpdateResult:
        def build_camera_params(
            base_camera: CameraPosition, start_dlong: Optional[int], end_dlong: Optional[int]
        ) -> Type6CameraParameters:
            middle_point = self._interpolated_dlong(start_dlong, end_dlong, track_length) or 0
            base_type6 = base_camera.type6
            start_zoom = base_type6.start_zoom if base_type6 else 0
            middle_zoom = base_type6.middle_point_zoom if base_type6 else 0
            end_zoom = base_type6.end_zoom if base_type6 else 0
            return Type6CameraParameters(
                middle_point=middle_point,
                start_point=start_dlong or 0,
                start_zoom=start_zoom,
                middle_point_zoom=middle_zoom,
                end_point=end_dlong or (start_dlong or 0),
                end_zoom=end_zoom,
            )

        return self._add_tv_camera(
            cameras,
            camera_views,
            selected_camera,
            track_length,
            camera_type=6,
            build_camera_params=build_camera_params,
            raw_values_length=9,
            success_message="Type 6 camera added.",
        )

    def add_type7_camera(
        self,
        cameras: List[CameraPosition],
        camera_views: List[CameraViewListing],
        selected_camera: int | None,
        track_length: float | None,
    ) -> CameraUpdateResult:
        def build_camera_params(
            base_camera: CameraPosition, start_dlong: Optional[int], end_dlong: Optional[int]
        ) -> Type7CameraParameters:
            base_type7 = base_camera.type7
            return Type7CameraParameters(
                z_axis_rotation=base_type7.z_axis_rotation if base_type7 else 0,
                vertical_rotation=base_type7.vertical_rotation if base_type7 else 0,
                tilt=base_type7.tilt if base_type7 else 0,
                zoom=base_type7.zoom if base_type7 else 0,
                unknown1=base_type7.unknown1 if base_type7 else 0,
                unknown2=base_type7.unknown2 if base_type7 else 0,
                unknown3=base_type7.unknown3 if base_type7 else 0,
                unknown4=base_type7.unknown4 if base_type7 else 0,
            )

        return self._add_tv_camera(
            cameras,
            camera_views,
            selected_camera,
            track_length,
            camera_type=7,
            build_camera_params=build_camera_params,
            raw_values_length=12,
            success_message="Type 7 camera added.",
        )

    def renumber(
        self, cameras: List[CameraPosition], camera_views: List[CameraViewListing]
    ) -> Tuple[List[CameraPosition], List[CameraViewListing]]:
        self._renumber_camera_type_indices(cameras, camera_views)
        return cameras, camera_views

    def set_tv_mode_count(
        self,
        camera_views: List[CameraViewListing],
        archived_camera_views: List[CameraViewListing],
        count: int,
    ) -> Tuple[List[CameraViewListing], List[CameraViewListing], int]:
        if not camera_views:
            return camera_views, archived_camera_views, len(camera_views)

        clamped_count = max(1, min(2, count))
        if clamped_count == 1:
            if len(camera_views) > 1:
                archived_camera_views[:] = camera_views[1:]
            del camera_views[1:]
        elif clamped_count == 2:
            if len(camera_views) > 2:
                del camera_views[2:]
                archived_camera_views[:] = []
            elif len(camera_views) == 1:
                restored_view = archived_camera_views.pop(0) if archived_camera_views else None
                if restored_view is not None:
                    camera_views.append(restored_view)
                else:
                    source_view = camera_views[0]
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
                    camera_views.append(
                        CameraViewListing(view=2, label="TV2", entries=copied_entries)
                    )

        for index, view in enumerate(camera_views, start=1):
            view.view = index
            view.label = f"TV{index}"

        return camera_views, archived_camera_views, len(camera_views)

    def _insert_camera_at_index(
        self,
        cameras: List[CameraPosition],
        camera_views: List[CameraViewListing],
        index: int,
        camera: CameraPosition,
    ) -> int:
        insert_index = max(0, min(index, len(cameras)))
        cameras.insert(insert_index, camera)
        for view in camera_views:
            for entry in view.entries:
                if entry.camera_index is not None and entry.camera_index >= insert_index:
                    entry.camera_index += 1
        return insert_index

    def _renumber_camera_type_indices(
        self, cameras: List[CameraPosition], camera_views: List[CameraViewListing]
    ) -> None:
        type_counts: dict[int, int] = {}
        for camera in cameras:
            count = type_counts.get(camera.camera_type, 0)
            camera.index = count
            type_counts[camera.camera_type] = count + 1
        for view in camera_views:
            for entry in view.entries:
                if entry.camera_index is None:
                    continue
                if entry.camera_index < 0 or entry.camera_index >= len(cameras):
                    continue
                camera = cameras[entry.camera_index]
                if entry.camera_type is None or entry.camera_type == camera.camera_type:
                    entry.type_index = camera.index

    def _find_camera_entry(
        self, camera_views: List[CameraViewListing], camera_index: int
    ) -> tuple[int, int] | None:
        for view_index, view in enumerate(camera_views):
            for entry_index, entry in enumerate(view.entries):
                if entry.camera_index == camera_index:
                    return view_index, entry_index
        return None

    def _interpolated_dlong(
        self, first: Optional[int], second: Optional[int], track_length: float | None
    ) -> Optional[int]:
        if first is None and second is None:
            return None
        if first is None:
            return second
        if second is None:
            return first
        if track_length:
            lap_length = int(track_length)
            if lap_length > 0:
                delta = (second - first) % lap_length
                return (first + delta // 2) % lap_length
        return (first + second) // 2
