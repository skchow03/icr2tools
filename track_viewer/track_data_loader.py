"""Helpers for loading TRK/LP/CAM/SCR content for the track viewer."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from icr2_core.cam.helpers import (
    CameraPosition,
    CameraSegmentRange,
    load_cam_positions,
    load_cam_positions_bytes,
    load_scr_segments,
    load_scr_segments_bytes,
    write_cam_positions,
    write_scr_segments,
)
from icr2_core.dat import packdat, unpackdat
from icr2_core.dat.unpackdat import extract_file_bytes
from icr2_core.lp.loader import load_lp_file
from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.surface_mesh import (
    GroundSurfaceStrip,
    build_ground_surface_mesh,
    compute_mesh_bounds,
)
from icr2_core.trk.trk_utils import get_cline_pos, getxyz
from track_viewer.camera_models import CameraViewListing


@dataclass
class TrackSurfaceData:
    """Pre-rendered geometry needed to paint a track."""

    trk: object
    cline: list[tuple[float, float]]
    surface_mesh: List[GroundSurfaceStrip]
    bounds: Tuple[float, float, float, float] | None
    sampled_centerline: List[tuple[float, float]]
    sampled_dlongs: List[float]
    sampled_bounds: Tuple[float, float, float, float] | None
    track_length: float | None


@dataclass
class AiLineData:
    """Collection of AI racing line data for LP overlays."""

    available_files: list[str]
    ai_lines: dict[str, List[Tuple[float, float]]]


@dataclass
class CameraData:
    """Raw camera positions and TV mode metadata."""

    cameras: list[CameraPosition]
    camera_views: list[CameraViewListing]
    camera_source: str | None
    camera_files_from_dat: bool
    dat_path: Path | None


class TrackDataLoader:
    """Load TRK geometry, AI lines, and camera data for rendering."""

    def __init__(self) -> None:
        self._temp_dir: Path | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_track(self, track_folder: Path) -> tuple[TrackSurfaceData, AiLineData, CameraData]:
        trk = load_trk_from_folder(str(track_folder))
        cline = get_cline_pos(trk)
        surface_mesh = build_ground_surface_mesh(trk, cline)
        bounds = compute_mesh_bounds(surface_mesh)
        sampled, sampled_dlongs, sampled_bounds = self._sample_centerline(trk, cline)
        track_data = TrackSurfaceData(
            trk=trk,
            cline=cline,
            surface_mesh=surface_mesh,
            bounds=bounds,
            sampled_centerline=sampled,
            sampled_dlongs=sampled_dlongs,
            sampled_bounds=sampled_bounds,
            track_length=float(trk.trklength),
        )

        available_lp_files = self._detect_available_lp_files(track_folder)
        ai_lines = {
            name: self._load_ai_line(track_folder, name, track_data)
            for name in available_lp_files
        }
        ai_data = AiLineData(available_files=available_lp_files, ai_lines=ai_lines)

        camera_data = self._load_track_cameras(track_folder)
        return track_data, ai_data, camera_data

    def save_cameras(
        self,
        track_folder: Path,
        camera_data: CameraData,
    ) -> tuple[bool, str]:
        track_name = track_folder.name
        cam_path = track_folder / f"{track_name}.cam"
        scr_path = track_folder / f"{track_name}.scr"

        try:
            self._backup_file(cam_path)
            self._backup_file(scr_path)
            write_cam_positions(cam_path, camera_data.cameras)
            write_scr_segments(scr_path, camera_data.camera_views)
            if camera_data.camera_source == "dat" and camera_data.dat_path is not None:
                self._repack_dat(camera_data.dat_path, cam_path, scr_path)
                if camera_data.camera_files_from_dat:
                    if cam_path.exists():
                        cam_path.unlink()
                    if scr_path.exists():
                        scr_path.unlink()
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to save cameras: {exc}"

        return True, "Camera files saved successfully."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _sample_centerline(
        self, trk, cline: list[tuple[float, float]]
    ) -> tuple[list[tuple[float, float]], list[float], Tuple[float, float, float, float]]:
        num_points = 2000
        cline_points: list[tuple[float, float]] = []
        cline_dlongs: list[float] = []
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for index in range(num_points):
            dlong = index * trk.trklength / num_points
            x, y, z = getxyz(trk, dlong, 0, cline)
            cline_points.append((x, y))
            cline_dlongs.append(dlong)
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
        return cline_points, cline_dlongs, (min_x, max_x, min_y, max_y)

    def _detect_available_lp_files(self, track_folder: Path) -> list[str]:
        available: list[str] = []
        track_name = track_folder.name
        dat_path = self._dat_path(track_folder)
        fallback_lp_dir = track_folder / "LINE"

        if dat_path:
            available.extend(self._detect_dat_lp_files(dat_path, track_name))
        if fallback_lp_dir.exists() and fallback_lp_dir.is_dir():
            available.extend(
                str(file.stem)
                for file in fallback_lp_dir.iterdir()
                if file.suffix.lower() == ".lp"
            )
        return sorted(set(available))

    def _detect_dat_lp_files(self, dat_path: Path, track_name: str) -> list[str]:
        names: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            unpackdat(str(dat_path), str(temp_dir))
            lp_dir = temp_dir / track_name / "LINE"
            if not lp_dir.exists() or not lp_dir.is_dir():
                return []
            for file in lp_dir.iterdir():
                if file.suffix.lower() == ".lp":
                    names.append(file.stem)
        return names

    def _load_ai_line(
        self, track_folder: Path, name: str, track_data: TrackSurfaceData
    ) -> List[Tuple[float, float]]:
        track_name = track_folder.name
        dat_path = self._dat_path(track_folder)
        track_length = int(track_data.track_length) if track_data.track_length else None

        def _convert_points(records: list) -> List[Tuple[float, float]]:
            points: List[Tuple[float, float]] = []
            for record in records:
                try:
                    x, y, _ = getxyz(
                        track_data.trk,
                        float(record.dlong),
                        record.dlat,
                        track_data.cline,
                    )
                except Exception:
                    continue
                points.append((x, y))
            return points

        if dat_path:
            lp_path = Path(f"{track_name}/LINE/{name}.LP")
            try:
                lp_bytes = extract_file_bytes(str(dat_path), str(lp_path))
                records = load_lp_file(
                    lp_bytes.decode("latin-1"), track_length=track_length
                )
                return _convert_points(records)
            except Exception:
                pass

        lp_path = track_folder / "LINE" / f"{name}.lp"
        try:
            records = load_lp_file(lp_path, track_length=track_length)
            return _convert_points(records)
        except Exception:
            return []

    def _dat_path(self, track_folder: Path) -> Optional[Path]:
        track_name = track_folder.name
        dat_path = track_folder / f"{track_name}.dat"
        return dat_path if dat_path.exists() else None

    def _load_track_cameras(self, track_folder: Path) -> CameraData:
        cameras: list[CameraPosition] = []
        camera_views: list[CameraViewListing] = []
        camera_source: str | None = None
        camera_files_from_dat = False
        dat_path = self._dat_path(track_folder)

        if dat_path:
            cam_path = Path(f"{track_folder.name}/{track_folder.name}.CAM")
            scr_path = Path(f"{track_folder.name}/{track_folder.name}.SCR")
            try:
                cam_bytes = extract_file_bytes(str(dat_path), str(cam_path))
                scr_bytes = extract_file_bytes(str(dat_path), str(scr_path))
                cameras = load_cam_positions_bytes(cam_bytes)
                camera_views = load_scr_segments_bytes(scr_bytes)
                camera_source = "dat"
                camera_files_from_dat = True
            except Exception:
                camera_source = "dat"

        if not cameras:
            track_name = track_folder.name
            cam_path = track_folder / f"{track_name}.cam"
            scr_path = track_folder / f"{track_name}.scr"
            try:
                cameras = load_cam_positions(cam_path)
                camera_source = camera_source or "cam"
            except Exception:
                cameras = []
            try:
                camera_views = load_scr_segments(scr_path)
            except Exception:
                camera_views = []

        return CameraData(
            cameras=cameras,
            camera_views=camera_views,
            camera_source=camera_source,
            camera_files_from_dat=camera_files_from_dat,
            dat_path=dat_path,
        )

    def _backup_file(self, path: Path) -> None:
        if not path.exists():
            return
        timestamp = path.stat().st_mtime
        date_str = f"{timestamp:.0f}"
        backup_dir = path.parent / "BACKUP"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"{path.name}.{date_str}.bak"
        shutil.copy2(path, backup_path)

    def _repack_dat(self, dat_path: Path, cam_path: Path, scr_path: Path) -> None:
        if self._temp_dir is None:
            temp_dir = tempfile.TemporaryDirectory()
            self._temp_dir = Path(temp_dir.name)
        else:
            temp_dir = tempfile.TemporaryDirectory(dir=self._temp_dir)
            self._temp_dir = Path(temp_dir.name)

        unpackdat(str(dat_path), str(self._temp_dir))
        target_dir = self._temp_dir / dat_path.stem
        target_dir.mkdir(exist_ok=True, parents=True)
        shutil.copy2(cam_path, target_dir / cam_path.name)
        shutil.copy2(scr_path, target_dir / scr_path.name)
        packdat(str(self._temp_dir), str(dat_path))
