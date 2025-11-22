"""Embedded surface preview widget for the standalone track viewer."""
from __future__ import annotations

import datetime
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import (
    CameraPosition,
    CameraSegmentRange,
    Type6CameraParameters,
    load_cam_positions,
    load_cam_positions_bytes,
    load_scr_segments,
    load_scr_segments_bytes,
    write_cam_positions,
    write_scr_segments,
)
from icr2_core.dat import packdat, unpackdat
from icr2_core.dat.unpackdat import extract_file_bytes
from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.surface_mesh import (
    GroundSurfaceStrip,
    build_ground_surface_mesh,
    compute_mesh_bounds,
)
from icr2_core.trk.trk_utils import get_cline_pos, color_from_ground_type, getxyz
from track_viewer.camera_models import CameraViewEntry, CameraViewListing


class TrackPreviewWidget(QtWidgets.QFrame):
    """Renders the TRK ground surface similar to the timing overlay."""

    cursorPositionChanged = QtCore.pyqtSignal(object)
    selectedFlagChanged = QtCore.pyqtSignal(object)
    camerasChanged = QtCore.pyqtSignal(list, list)
    selectedCameraChanged = QtCore.pyqtSignal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(24, 24, 24))
        self.setPalette(palette)

        self._status_message = "Select a track to preview."

        self.trk = None
        self._cline: List[Tuple[float, float]] = []
        self._surface_mesh: List[GroundSurfaceStrip] = []
        self._bounds: Tuple[float, float, float, float] | None = None
        self._sampled_centerline: List[Tuple[float, float]] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: Tuple[float, float, float, float] | None = None
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None
        self._current_track: Path | None = None
        self._camera_source: str | None = None
        self._dat_path: Path | None = None
        self._show_center_line = True
        self._show_cameras = True
        self._track_length: float | None = None

        self._view_center: Tuple[float, float] | None = None
        self._fit_scale: float | None = None
        self._current_scale: float | None = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._left_press_pos: QtCore.QPoint | None = None
        self._dragged_during_press = False

        self._dragging_camera_index: int | None = None
        self._camera_dragged = False

        self._flags: List[Tuple[float, float]] = []
        self._selected_flag: int | None = None
        self._cameras: List[CameraPosition] = []
        self._camera_views: List[CameraViewListing] = []
        self._selected_camera: int | None = None
        self._nearest_centerline_point: Tuple[float, float] | None = None
        self._nearest_centerline_dlong: float | None = None
        self._nearest_centerline_elevation: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        self.trk = None
        self._cline = []
        self._surface_mesh = []
        self._bounds = None
        self._sampled_centerline = []
        self._sampled_dlongs = []
        self._sampled_bounds = None
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = None
        self._camera_source = None
        self._dat_path = None
        self._view_center = None
        self._fit_scale = None
        self._current_scale = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos = None
        self._left_press_pos = None
        self._dragged_during_press = False
        self._dragging_camera_index = None
        self._camera_dragged = False
        self._flags = []
        self._selected_flag = None
        self._cameras = []
        self._camera_views = []
        self._selected_camera = None
        self._nearest_centerline_point = None
        self._nearest_centerline_dlong = None
        self._nearest_centerline_elevation = None
        self._track_length = None
        self._status_message = message
        self.cursorPositionChanged.emit(None)
        self.selectedFlagChanged.emit(None)
        self.camerasChanged.emit([], [])
        self.selectedCameraChanged.emit(None, None)
        self.update()

    # ------------------------------------------------------------------
    # Center line controls
    # ------------------------------------------------------------------
    def set_show_center_line(self, show: bool) -> None:
        """Enable or disable rendering of the track center line."""

        if self._show_center_line != show:
            self._show_center_line = show
            if not show:
                self._set_centerline_projection(None, None, None)
            self.update()

    def center_line_visible(self) -> bool:
        return self._show_center_line

    def track_length(self) -> Optional[int]:
        return int(self._track_length) if self._track_length is not None else None

    def set_show_cameras(self, show: bool) -> None:
        """Enable or disable rendering of track camera overlays."""

        if self._show_cameras != show:
            self._show_cameras = show
            self.update()

    def cameras(self) -> List[CameraPosition]:
        return list(self._cameras)

    def update_camera_dlongs(
        self, camera_index: int, start_dlong: Optional[int], end_dlong: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._cameras):
            return

        # Editing start/end values in the TV modes table updates the segment
        # ranges directly on the shared camera view entries. We only need to
        # trigger a repaint so the centerline markers reflect the new values.
        if self._selected_camera == camera_index:
            self._emit_selected_camera()
        self.update()

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
        self.update()

    def set_selected_camera(self, index: int | None) -> None:
        if index == self._selected_camera:
            return
        if index is not None:
            if index < 0 or index >= len(self._cameras):
                index = None
        self._selected_camera = index
        self._emit_selected_camera()
        self.update()

    def add_type6_camera(self) -> tuple[bool, str]:
        """Create a new type 6 camera relative to the current selection."""

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
        middle_point = self._interpolated_dlong(start_dlong, end_dlong) or 0

        if start_dlong is not None:
            previous_entry.end_dlong = start_dlong
        if end_dlong is not None:
            next_entry.start_dlong = end_dlong

        base_type6 = base_camera.type6
        start_zoom = base_type6.start_zoom if base_type6 else 0
        middle_zoom = base_type6.middle_point_zoom if base_type6 else 0
        end_zoom = base_type6.end_zoom if base_type6 else 0

        new_camera = CameraPosition(
            camera_type=6,
            index=0,
            x=base_camera.x + 60000,
            y=base_camera.y + 60000,
            z=base_camera.z,
            type6=Type6CameraParameters(
                middle_point=middle_point,
                start_point=start_dlong or 0,
                start_zoom=start_zoom,
                middle_point_zoom=middle_zoom,
                end_point=end_dlong or (start_dlong or 0),
                end_zoom=end_zoom,
            ),
            raw_values=tuple([0] * 9),
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
        self._status_message = f"Added camera #{insert_index} to {view.label}"
        self.update()
        return True, "Type 6 camera added."

    def _insert_camera_at_index(self, index: int, camera: CameraPosition) -> int:
        """Insert a camera into the global list and shift references."""

        insert_index = max(0, min(index, len(self._cameras)))
        self._cameras.insert(insert_index, camera)
        for view in self._camera_views:
            for entry in view.entries:
                if entry.camera_index is not None and entry.camera_index >= insert_index:
                    entry.camera_index += 1
        return insert_index

    def _renumber_camera_type_indices(self) -> None:
        """Ensure per-type camera indices are sequential after edits."""

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

    def load_track(self, track_folder: Path) -> None:
        """Load and render the contents of a track folder."""
        if not track_folder:
            self.clear()
            return

        if self._current_track == track_folder:
            return  # nothing to do

        self._status_message = f"Loading {track_folder.name}…"
        self.update()

        try:
            trk = load_trk_from_folder(str(track_folder))
            cline = get_cline_pos(trk)
            surface_mesh = build_ground_surface_mesh(trk, cline)
            bounds = compute_mesh_bounds(surface_mesh)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load track: {exc}")
            return

        self.trk = trk
        self._track_length = float(trk.trklength)
        self._cline = cline
        self._surface_mesh = surface_mesh
        sampled, sampled_dlongs, sampled_bounds = self._sample_centerline(trk, cline)
        self._sampled_centerline = sampled
        self._sampled_dlongs = sampled_dlongs
        self._sampled_bounds = sampled_bounds
        self._bounds = self._merge_bounds(bounds, sampled_bounds)
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = track_folder
        self._status_message = f"Loaded {track_folder.name}" if track_folder else ""
        self._view_center = self._default_center()
        self._user_transform_active = False
        self._update_fit_scale()
        self._flags = []
        self._set_selected_flag(None)
        self._load_track_cameras(track_folder)
        self.set_selected_camera(None)
        self.update()

    def save_cameras(self) -> tuple[bool, str]:
        """Persist the current camera data back to disk."""

        if self._current_track is None:
            return False, "No track is currently loaded."

        track_name = self._current_track.name
        cam_path = self._current_track / f"{track_name}.cam"
        scr_path = self._current_track / f"{track_name}.scr"

        try:
            self._backup_file(cam_path)
            self._backup_file(scr_path)
            write_cam_positions(cam_path, self._cameras)
            write_scr_segments(scr_path, self._camera_views)
            if self._camera_source == "dat" and self._dat_path is not None:
                self._repack_dat(cam_path, scr_path)
            self._status_message = f"Saved cameras for {track_name}"
            self.update()
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to save cameras: {exc}"

        return True, "Camera files saved successfully."

    def _load_track_cameras(self, track_folder: Path) -> None:
        self._cameras = []
        self._camera_views = []
        if not track_folder:
            self.camerasChanged.emit([], [])
            return
        try:
            track_name = track_folder.name
        except Exception:
            self.camerasChanged.emit([], [])
            return
        cam_path = track_folder / f"{track_name}.cam"
        scr_path = track_folder / f"{track_name}.scr"
        dat_files = list(track_folder.glob("*.dat"))
        dat_path = dat_files[0] if dat_files else None
        self._dat_path = dat_path
        self._camera_source = None

        cam_from_dat = False
        if cam_path.exists():
            try:
                self._cameras = load_cam_positions(cam_path)
            except Exception:  # pragma: no cover - best effort diagnostics
                self._cameras = []
        elif dat_path:
            try:
                cam_bytes = extract_file_bytes(str(dat_path), f"{track_name}.cam")
                self._cameras = load_cam_positions_bytes(cam_bytes)
                cam_from_dat = True
            except Exception:  # pragma: no cover - best effort diagnostics
                self._cameras = []

        segments: List[CameraSegmentRange] = []
        scr_from_dat = False
        if scr_path.exists():
            try:
                segments = load_scr_segments(scr_path)
            except Exception:  # pragma: no cover - best effort diagnostics
                segments = []
        elif dat_path:
            try:
                scr_bytes = extract_file_bytes(str(dat_path), f"{track_name}.scr")
                segments = load_scr_segments_bytes(scr_bytes)
                scr_from_dat = True
            except Exception:  # pragma: no cover - best effort diagnostics
                segments = []
        if cam_from_dat and scr_from_dat:
            self._camera_source = "dat"
        elif cam_path.exists() or scr_path.exists():
            self._camera_source = "files"
        elif dat_path:
            self._camera_source = "dat"
        self._camera_views = self._build_camera_views(segments)
        self.camerasChanged.emit(self._cameras, self._camera_views)

    def _backup_file(self, path: Path) -> Optional[Path]:
        if not path.exists():
            return None
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_suffix(path.suffix + f".bak.{timestamp}")
        shutil.copy2(path, backup_path)
        return backup_path

    def _repack_dat(self, cam_path: Path, scr_path: Path) -> None:
        if self._dat_path is None:
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            unpackdat.unpackdat(str(self._dat_path), output_folder=tmpdir)
            packlist_path = Path(tmpdir) / "packlist.txt"
            if not packlist_path.exists():
                raise FileNotFoundError("packlist.txt not found when rebuilding DAT")
            pack_entries = [
                line.strip() for line in packlist_path.read_text().splitlines() if line.strip()
            ]
            cam_entry = next(
                (name for name in pack_entries if name.lower() == cam_path.name.lower()),
                cam_path.name,
            )
            scr_entry = next(
                (name for name in pack_entries if name.lower() == scr_path.name.lower()),
                scr_path.name,
            )
            if cam_entry not in pack_entries:
                pack_entries.append(cam_entry)
            if scr_entry not in pack_entries:
                pack_entries.append(scr_entry)
            packlist_path.write_text("\n".join(pack_entries) + "\n")
            shutil.copy2(cam_path, Path(tmpdir) / cam_entry)
            shutil.copy2(scr_path, Path(tmpdir) / scr_entry)
            packdat.packdat(str(packlist_path), str(self._dat_path), backup=True)

    def _build_camera_views(
        self, segments: List[CameraSegmentRange]
    ) -> List[CameraViewListing]:
        if not segments:
            return []
        type_buckets: dict[int, dict[int, tuple[int, CameraPosition]]] = {}
        for global_index, camera in enumerate(self._cameras):
            per_type = type_buckets.setdefault(camera.camera_type, {})
            per_type[camera.index] = (global_index, camera)
        by_view: dict[int, List[CameraSegmentRange]] = {}
        for segment in segments:
            by_view.setdefault(segment.view, []).append(segment)
        listings: List[CameraViewListing] = []
        for view_index in sorted(by_view):
            entries = sorted(
                by_view[view_index],
                key=lambda segment: (
                    segment.start_dlong,
                    segment.end_dlong,
                    segment.camera_id,
                ),
            )
            view_entries: List[CameraViewEntry] = []
            for segment in entries:
                camera_type = segment.mark if segment.mark in (2, 6, 7) else None
                bucket_entry = type_buckets.get(camera_type, {}).get(segment.camera_id)
                camera_index = None
                camera = None
                if bucket_entry is not None:
                    camera_index, camera = bucket_entry
                elif 0 <= segment.camera_id < len(self._cameras):
                    camera_index = segment.camera_id
                    camera = self._cameras[camera_index]
                    if camera_type is None:
                        camera_type = camera.camera_type
                elif type_buckets:
                    # Try any camera with the requested type index as a last resort
                    for per_type in type_buckets.values():
                        candidate = per_type.get(segment.camera_id)
                        if candidate is not None:
                            camera_index, camera = candidate
                            break
                view_entries.append(
                    CameraViewEntry(
                        camera_index=camera_index if camera_index is not None else segment.camera_id,
                        type_index=segment.camera_id,
                        camera_type=camera_type if camera_type is not None else None,
                        start_dlong=segment.start_dlong,
                        end_dlong=segment.end_dlong,
                        mark=segment.mark,
                    )
                )
            listings.append(
                CameraViewListing(view=view_index, label=f"TV{view_index}", entries=view_entries)
            )
        return listings

    def _find_camera_entry(self, camera_index: int) -> tuple[int, int] | None:
        for view_index, view in enumerate(self._camera_views):
            for entry_index, entry in enumerate(view.entries):
                if entry.camera_index == camera_index:
                    return view_index, entry_index
        return None

    def _interpolated_dlong(
        self, first: Optional[int], second: Optional[int]
    ) -> Optional[int]:
        if first is None and second is None:
            return None
        if first is None:
            return second
        if second is None:
            return first
        if self._track_length:
            lap_length = int(self._track_length)
            if lap_length > 0:
                delta = (second - first) % lap_length
                return (first + delta // 2) % lap_length
        return (first + second) // 2

    # ------------------------------------------------------------------
    # Painting helpers
    # ------------------------------------------------------------------
    def _map_point(
        self, x: float, y: float, scale: float, offsets: Tuple[float, float]
    ) -> QtCore.QPointF:
        px = x * scale + offsets[0]
        py = y * scale + offsets[1]
        return QtCore.QPointF(px, self.height() - py)

    def _default_center(self) -> Tuple[float, float] | None:
        if not self._bounds:
            return None
        min_x, max_x, min_y, max_y = self._bounds
        return ((min_x + max_x) / 2, (min_y + max_y) / 2)

    def _calculate_fit_scale(self) -> float | None:
        if not self._bounds:
            return None
        min_x, max_x, min_y, max_y = self._bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return None
        margin = 24
        w, h = self.width(), self.height()
        available_w = max(w - margin * 2, 1)
        available_h = max(h - margin * 2, 1)
        scale_x = available_w / track_w
        scale_y = available_h / track_h
        return min(scale_x, scale_y)

    def _sample_centerline(
        self,
        trk,
        cline: List[Tuple[float, float]],
        step: int = 10000,
    ) -> Tuple[
        List[Tuple[float, float]],
        List[float],
        Tuple[float, float, float, float] | None,
    ]:
        if not trk or not cline:
            return [], [], None

        pts: List[Tuple[float, float]] = []
        dlongs: List[float] = []
        dlong = 0
        while dlong < trk.trklength:
            x, y, _ = getxyz(trk, dlong, 0, cline)
            pts.append((x, y))
            dlongs.append(dlong)
            dlong += step

        if trk.trklength > 0:
            x, y, _ = getxyz(trk, trk.trklength, 0, cline)
            pts.append((x, y))
            dlongs.append(float(trk.trklength))

        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])
            dlongs.append(float(trk.trklength))

        bounds = None
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bounds = (min(xs), max(xs), min(ys), max(ys))
        return pts, dlongs, bounds

    def _merge_bounds(
        self, *bounds: Tuple[float, float, float, float] | None
    ) -> Tuple[float, float, float, float] | None:
        valid = [b for b in bounds if b]
        if not valid:
            return None
        min_x = min(b[0] for b in valid)
        max_x = max(b[1] for b in valid)
        min_y = min(b[2] for b in valid)
        max_y = max(b[3] for b in valid)
        return (min_x, max_x, min_y, max_y)

    def _update_fit_scale(self) -> None:
        fit = self._calculate_fit_scale()
        self._fit_scale = fit
        if fit is not None and not self._user_transform_active:
            self._current_scale = fit
            if self._view_center is None:
                self._view_center = self._default_center()
            self._invalidate_cache()

    def _current_transform(self) -> Tuple[float, Tuple[float, float]] | None:
        if not self._bounds:
            return None
        if self._current_scale is None:
            self._update_fit_scale()
        if self._current_scale is None:
            return None
        center = self._view_center or self._default_center()
        if center is None:
            return None
        w, h = self.width(), self.height()
        offsets = (w / 2 - center[0] * self._current_scale, h / 2 - center[1] * self._current_scale)
        return self._current_scale, offsets

    def _invalidate_cache(self) -> None:
        self._cached_surface_pixmap = None
        self._pixmap_size = None

    def _map_to_track(self, point: QtCore.QPointF) -> Tuple[float, float] | None:
        transform = self._current_transform()
        if not transform:
            return None
        scale, offsets = transform
        x = (point.x() - offsets[0]) / scale
        py = self.height() - point.y()
        y = (py - offsets[1]) / scale
        return x, y

    def _clamp_scale(self, scale: float) -> float:
        base = self._fit_scale or self._current_scale or 1.0
        min_scale = base * 0.1
        max_scale = base * 25.0
        return max(min_scale, min(max_scale, scale))

    def _render_surface_to_pixmap(self) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(self.size())
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        transform = self._current_transform()
        if not transform:
            painter.end()
            return pixmap
        scale, offsets = transform
        for strip in self._surface_mesh:
            base_color = QtGui.QColor(color_from_ground_type(strip.ground_type))
            fill = QtGui.QColor(base_color)
            fill.setAlpha(200)
            outline = base_color.darker(125)
            points = [self._map_point(x, y, scale, offsets) for x, y in strip.points]
            poly = QtGui.QPolygonF(points)
            painter.setBrush(QtGui.QBrush(fill))
            painter.setPen(QtGui.QPen(outline, 1))
            painter.drawPolygon(poly)
        painter.end()
        return pixmap

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D401 - Qt signature
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Window))

        if not self._surface_mesh or not self._bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, self._status_message)
            return

        if self._cached_surface_pixmap is None or self._pixmap_size != self.size():
            self._cached_surface_pixmap = self._render_surface_to_pixmap()
            self._pixmap_size = self.size()

        painter.drawPixmap(0, 0, self._cached_surface_pixmap)

        transform = self._current_transform()
        if self._show_center_line and self._sampled_centerline and transform:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            scale, offsets = transform
            points = [
                self._map_point(x, y, scale, offsets)
                for x, y in self._sampled_centerline
            ]
            painter.setPen(QtGui.QPen(QtGui.QColor("white"), 2))
            painter.drawPolyline(QtGui.QPolygonF(points))

        if transform and self._show_center_line:
            self._draw_start_finish_line(painter, transform)

        if transform and self._show_center_line:
            self._draw_camera_range_markers(painter, transform)

        if transform and self._nearest_centerline_point:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            scale, offsets = transform
            highlight = self._map_point(
                self._nearest_centerline_point[0],
                self._nearest_centerline_point[1],
                scale,
                offsets,
            )
            pen = QtGui.QPen(QtGui.QColor("#ff5252"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff5252")))
            painter.drawEllipse(highlight, 5, 5)

        if transform:
            if self._show_cameras:
                self._draw_camera_positions(painter, transform)
            self._draw_flags(painter, transform)

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        y = 20
        if self._track_length is not None:
            track_length_text = (
                f"Track length: {int(round(self._track_length))} DLONG"
            )
            painter.drawText(12, y, track_length_text)
            y += 16
        painter.drawText(12, y, self._status_message)
        y += 16
        if self._nearest_centerline_dlong is not None:
            dlong_text = f"Centerline DLONG: {int(round(self._nearest_centerline_dlong))}"
            painter.drawText(12, y, dlong_text)
            y += 16
        if self._nearest_centerline_elevation is not None:
            elevation_text = (
                f"Elevation: {self._nearest_centerline_elevation:.2f} (DLAT = 0)"
            )
            painter.drawText(12, y, elevation_text)

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._pixmap_size = None
        self._cached_surface_pixmap = None
        self._update_fit_scale()
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401 - Qt signature
        if not self._surface_mesh or not self._bounds:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        if self._view_center is None:
            self._view_center = self._default_center()
        if self._view_center is None or self._current_scale is None:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._clamp_scale(self._current_scale * factor)
        cursor_track = self._map_to_track(event.pos())
        if cursor_track is None:
            cursor_track = self._view_center
        w, h = self.width(), self.height()
        px, py = event.pos().x(), event.pos().y()
        cx = cursor_track[0] - (px - w / 2) / new_scale
        cy = cursor_track[1] + (py - h / 2) / new_scale
        self._view_center = (cx, cy)
        self._current_scale = new_scale
        self._user_transform_active = True
        self._invalidate_cache()
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if event.button() == QtCore.Qt.RightButton and self._surface_mesh:
            if self._handle_flag_removal(event.pos()):
                event.accept()
                return

        if event.button() == QtCore.Qt.LeftButton and self._surface_mesh:
            if self._handle_camera_press(event.pos()):
                event.accept()
                return
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._left_press_pos = event.pos()
            self._dragged_during_press = False
            self._user_transform_active = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        handled = False
        if self._dragging_camera_index is not None:
            self._update_camera_position(event.pos())
            event.accept()
            handled = True
        if self._is_panning and self._last_mouse_pos is not None:
            transform = self._current_transform()
            if transform:
                if self._view_center is None:
                    self._view_center = self._default_center()
                if self._view_center is not None:
                    scale, _ = transform
                    delta = event.pos() - self._last_mouse_pos
                    self._last_mouse_pos = event.pos()
                    if (
                        not self._dragged_during_press
                        and self._left_press_pos is not None
                        and (event.pos() - self._left_press_pos).manhattanLength() > 4
                    ):
                        self._dragged_during_press = True
                    cx, cy = self._view_center
                    cx -= delta.x() / scale
                    cy += delta.y() / scale
                    self._view_center = (cx, cy)
                    self._invalidate_cache()
                    self.update()
            event.accept()
            handled = True
        self._update_cursor_position(event.pos())
        if not handled:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if event.button() == QtCore.Qt.LeftButton and self._surface_mesh:
            if self._dragging_camera_index is not None:
                self._dragging_camera_index = None
                self._camera_dragged = False
                event.accept()
                return
            click_without_drag = not self._dragged_during_press
            self._is_panning = False
            self._last_mouse_pos = None
            self._left_press_pos = None
            self._dragged_during_press = False
            if click_without_drag:
                self._handle_primary_click(event.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self.cursorPositionChanged.emit(None)
        self._set_centerline_projection(None, None, None)
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Cursor & flag helpers
    # ------------------------------------------------------------------
    def _update_cursor_position(self, point: QtCore.QPointF) -> None:
        if not self._surface_mesh or not self._bounds:
            self.cursorPositionChanged.emit(None)
            self._set_centerline_projection(None, None, None)
            return
        coords = self._map_to_track(point)
        self.cursorPositionChanged.emit(coords)
        self._update_centerline_projection(point)

    def _set_centerline_projection(
        self,
        point: Tuple[float, float] | None,
        dlong: float | None,
        elevation: float | None,
    ) -> None:
        if (
            point == self._nearest_centerline_point
            and dlong == self._nearest_centerline_dlong
            and elevation == self._nearest_centerline_elevation
        ):
            return
        self._nearest_centerline_point = point
        self._nearest_centerline_dlong = dlong
        self._nearest_centerline_elevation = elevation
        self.update()

    def _update_centerline_projection(self, point: QtCore.QPointF | None) -> None:
        if (
            point is None
            or not self._sampled_centerline
            or not self._sampled_dlongs
            or not self._show_center_line
        ):
            self._set_centerline_projection(None, None, None)
            return

        transform = self._current_transform()
        if not transform or not self.trk:
            self._set_centerline_projection(None, None, None)
            return

        cursor_track = self._map_to_track(point)
        if cursor_track is None:
            self._set_centerline_projection(None, None, None)
            return

        cursor_x, cursor_y = cursor_track
        best_point: Tuple[float, float] | None = None
        best_dlong: float | None = None
        best_distance_sq = float("inf")

        track_length = float(self.trk.trklength)
        for index, start in enumerate(self._sampled_centerline):
            end = self._sampled_centerline[(index + 1) % len(self._sampled_centerline)]
            start_dlong = self._sampled_dlongs[index]
            end_dlong = self._sampled_dlongs[(index + 1) % len(self._sampled_dlongs)]
            dlong_delta = end_dlong - start_dlong
            if dlong_delta <= 0:
                dlong_delta += track_length

            sx, sy = start
            ex, ey = end
            vx = ex - sx
            vy = ey - sy
            if vx == 0 and vy == 0:
                continue
            t = ((cursor_x - sx) * vx + (cursor_y - sy) * vy) / (vx * vx + vy * vy)
            t = max(0.0, min(1.0, t))
            proj_x = sx + vx * t
            proj_y = sy + vy * t

            distance_sq = (cursor_x - proj_x) ** 2 + (cursor_y - proj_y) ** 2
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                projected_dlong = start_dlong + dlong_delta * t
                if projected_dlong >= track_length:
                    projected_dlong -= track_length
                best_point = (proj_x, proj_y)
                best_dlong = projected_dlong

        scale, offsets = transform
        if best_point is None:
            self._set_centerline_projection(None, None, None)
            return

        mapped_point = self._map_point(best_point[0], best_point[1], scale, offsets)
        pixel_distance = (mapped_point - point).manhattanLength()
        if pixel_distance > 16:
            self._set_centerline_projection(None, None, None)
            return
        elevation = None
        if best_dlong is not None and self._cline:
            _, _, elevation = getxyz(self.trk, float(best_dlong), 0, self._cline)
        self._set_centerline_projection(best_point, best_dlong, elevation)

    def _draw_flags(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        if not self._flags:
            return
        scale, offsets = transform
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        radius = 6
        for index, (fx, fy) in enumerate(self._flags):
            point = self._map_point(fx, fy, scale, offsets)
            color = QtGui.QColor("#ffcc33")
            if index == self._selected_flag:
                color = QtGui.QColor("#ff7f0e")
            pen = QtGui.QPen(QtGui.QColor("black"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(color))
            painter.drawEllipse(point, radius, radius)
            painter.setPen(QtGui.QPen(QtGui.QColor("black")))
            flag_pole = QtCore.QLineF(
                point.x(),
                point.y() - radius - 4,
                point.x(),
                point.y() - radius,
            )
            painter.drawLine(flag_pole)

    def _camera_at_point(self, point: QtCore.QPointF, radius: int = 10) -> int | None:
        transform = self._current_transform()
        if not transform:
            return None
        scale, offsets = transform
        for index, cam in enumerate(self._cameras):
            camera_point = self._map_point(cam.x, cam.y, scale, offsets)
            if (camera_point - point).manhattanLength() <= radius:
                return index
        return None

    def _handle_camera_press(self, point: QtCore.QPointF) -> bool:
        camera_index = self._camera_at_point(point)
        if camera_index is None:
            return False
        self.set_selected_camera(camera_index)
        self._dragging_camera_index = camera_index
        self._camera_dragged = False
        self._is_panning = False
        self._dragged_during_press = False
        return True

    def _update_camera_position(self, point: QtCore.QPointF) -> None:
        if self._dragging_camera_index is None:
            return
        coords = self._map_to_track(point)
        if coords is None:
            return
        index = self._dragging_camera_index
        if index < 0 or index >= len(self._cameras):
            return
        cam = self._cameras[index]
        cam.x = int(round(coords[0]))
        cam.y = int(round(coords[1]))
        self._camera_dragged = True
        self._emit_selected_camera()
        self.update()

    def _draw_camera_positions(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        if not self._cameras:
            return
        scale, offsets = transform
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        type_colors = {
            2: QtGui.QColor("#ffeb3b"),
            6: QtGui.QColor("#ff9800"),
            7: QtGui.QColor("#4dd0e1"),
        }
        for index, cam in enumerate(self._cameras):
            point = self._map_point(cam.x, cam.y, scale, offsets)
            color = type_colors.get(cam.camera_type, QtGui.QColor("#ffffff"))
            self._draw_camera_symbol(painter, point, color, index == self._selected_camera)

    def _centerline_point_and_normal(
        self, dlong: float
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if not self.trk or not self._cline:
            return None
        track_length = float(self.trk.trklength)
        if track_length <= 0:
            return None

        def _wrap(value: float) -> float:
            while value < 0:
                value += track_length
            while value >= track_length:
                value -= track_length
            return value

        base = _wrap(float(dlong))
        delta = max(50.0, track_length * 0.002)
        prev_dlong = _wrap(base - delta)
        next_dlong = _wrap(base + delta)

        px, py, _ = getxyz(self.trk, prev_dlong, 0, self._cline)
        nx, ny, _ = getxyz(self.trk, next_dlong, 0, self._cline)
        cx, cy, _ = getxyz(self.trk, base, 0, self._cline)

        vx = nx - px
        vy = ny - py
        length = (vx * vx + vy * vy) ** 0.5
        if length == 0:
            return None
        normal = (-vy / length, vx / length)
        return (cx, cy), normal

    def _draw_perpendicular_bar(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
        dlong: float,
        *,
        color: QtGui.QColor | str = "#ff4081",
        width: float = 3.0,
        half_length_px: float = 10.0,
    ) -> None:
        mapping = self._centerline_point_and_normal(dlong)
        if mapping is None:
            return
        (cx, cy), (nx, ny) = mapping
        scale, offsets = transform
        if scale == 0:
            return

        half_length_track = half_length_px / scale
        start = self._map_point(
            cx - nx * half_length_track,
            cy - ny * half_length_track,
            scale,
            offsets,
        )
        end = self._map_point(
            cx + nx * half_length_track,
            cy + ny * half_length_track,
            scale,
            offsets,
        )
        pen = QtGui.QPen(QtGui.QColor(color), width)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.save()
        painter.setPen(pen)
        painter.drawLine(QtCore.QLineF(start, end))
        painter.restore()

    def _draw_start_finish_line(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        self._draw_perpendicular_bar(
            painter,
            transform,
            0.0,
            color="white",
            width=3.0,
            half_length_px=12.0,
        )

    def _camera_view_ranges(self, camera_index: int) -> list[tuple[float, float]]:
        ranges: list[tuple[float, float]] = []
        for view in self._camera_views:
            for entry in view.entries:
                if entry.camera_index != camera_index:
                    continue
                if entry.start_dlong is None or entry.end_dlong is None:
                    continue
                ranges.append((float(entry.start_dlong), float(entry.end_dlong)))
        return ranges

    def _draw_camera_range_markers(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        if self._selected_camera is None:
            return
        if self._selected_camera < 0 or self._selected_camera >= len(self._cameras):
            return

        ranges = self._camera_view_ranges(self._selected_camera)
        if not ranges:
            return

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        for start_dlong, end_dlong in ranges:
            self._draw_perpendicular_bar(painter, transform, float(start_dlong))
            self._draw_perpendicular_bar(painter, transform, float(end_dlong))

    def _draw_camera_symbol(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        base_color: QtGui.QColor,
        selected: bool,
    ) -> None:
        painter.save()
        painter.translate(center)
        pen = QtGui.QPen(QtGui.QColor("#111111"))
        pen.setWidth(1 if not selected else 2)
        pen.setColor(base_color if not selected else QtGui.QColor("#ff4081"))
        painter.setPen(pen)
        painter.setBrush(QtGui.QBrush(base_color))

        body_width = 14
        body_height = 9
        lens_radius = 3
        viewfinder_width = 5
        viewfinder_height = 4

        body_rect = QtCore.QRectF(
            -body_width / 2, -body_height / 2, body_width, body_height
        )
        painter.drawRoundedRect(body_rect, 2, 2)

        lens_center = QtCore.QPointF(body_width / 2 - lens_radius - 1, 0)
        painter.drawEllipse(lens_center, lens_radius, lens_radius)

        viewfinder_rect = QtCore.QRectF(
            -body_width / 2,
            -body_height / 2 - viewfinder_height + 1,
            viewfinder_width,
            viewfinder_height,
        )
        painter.drawRoundedRect(viewfinder_rect, 1.5, 1.5)

        painter.restore()

    def _flag_at_point(self, point: QtCore.QPointF, radius: int = 8) -> int | None:
        transform = self._current_transform()
        if not transform:
            return None
        scale, offsets = transform
        for index, (fx, fy) in enumerate(self._flags):
            flag_point = self._map_point(fx, fy, scale, offsets)
            if (flag_point - point).manhattanLength() <= radius:
                return index
        return None

    def _handle_primary_click(self, point: QtCore.QPointF) -> None:
        transform = self._current_transform()
        if not transform:
            return
        camera_index = self._camera_at_point(point)
        if camera_index is not None:
            self.set_selected_camera(camera_index)
            return
        flag_index = self._flag_at_point(point)
        if flag_index is not None:
            self._set_selected_flag(flag_index)
            return
        coords = self._map_to_track(point)
        if coords is None:
            return
        self._flags.append(coords)
        self._set_selected_flag(len(self._flags) - 1)
        self.update()

    def _handle_flag_removal(self, point: QtCore.QPointF) -> bool:
        flag_index = self._flag_at_point(point)
        if flag_index is None:
            return False
        del self._flags[flag_index]
        if self._selected_flag is not None:
            if self._selected_flag == flag_index:
                self._set_selected_flag(None)
            elif self._selected_flag > flag_index:
                self._set_selected_flag(self._selected_flag - 1)
        self.update()
        return True

    def _set_selected_flag(self, index: int | None) -> None:
        self._selected_flag = index
        coords = None
        if index is not None and 0 <= index < len(self._flags):
            coords = self._flags[index]
        self.selectedFlagChanged.emit(coords)
        self.update()
