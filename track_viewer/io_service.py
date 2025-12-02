"""I/O helpers for loading and saving track resources."""
from __future__ import annotations

import datetime
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

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
from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.surface_mesh import GroundSurfaceStrip, build_ground_surface_mesh, compute_mesh_bounds
from icr2_core.trk.trk_utils import get_cline_pos
from track_viewer.camera_models import CameraViewEntry, CameraViewListing

LP_FILE_NAMES = [
    "RACE",
    "PASS1",
    "PASS2",
    "PIT",
    "MINRACE",
    "MAXRACE",
    "MINPANIC",
    "MAXPANIC",
    "PACE",
]


@dataclass
class TrackLoadResult:
    """Result of loading a TRK folder."""

    trk: object
    centerline: list[tuple[float, float]]
    surface_mesh: list[GroundSurfaceStrip]
    surface_bounds: tuple[float, float, float, float] | None
    available_lp_files: list[str]
    track_length: float


@dataclass
class CameraLoadResult:
    """Loaded camera data for a track."""

    cameras: list[CameraPosition]
    camera_views: list[CameraViewListing]
    camera_source: str | None
    camera_files_from_dat: bool
    dat_path: Path | None
    tv_mode_count: int


class TrackIOService:
    """Load/save helpers for the track viewer widget."""

    def load_track(self, track_folder: Path) -> TrackLoadResult:
        trk = load_trk_from_folder(str(track_folder))
        centerline = get_cline_pos(trk)
        surface_mesh = build_ground_surface_mesh(trk, centerline)
        surface_bounds = compute_mesh_bounds(surface_mesh)
        available_lp_files = self._detect_available_lp_files(track_folder)
        track_length = float(trk.trklength)
        return TrackLoadResult(
            trk=trk,
            centerline=centerline,
            surface_mesh=surface_mesh,
            surface_bounds=surface_bounds,
            available_lp_files=available_lp_files,
            track_length=track_length,
        )

    def load_cameras(self, track_folder: Path) -> CameraLoadResult:
        track_name = track_folder.name
        cam_path = track_folder / f"{track_name}.cam"
        scr_path = track_folder / f"{track_name}.scr"
        dat_path = self._find_matching_dat(track_folder, track_name)

        cameras: list[CameraPosition] = []
        segments: List[CameraSegmentRange] = []
        camera_source: str | None = None
        camera_files_from_dat = False

        cam_from_dat = False
        scr_from_dat = False
        cam_on_disk = cam_path.exists()
        scr_on_disk = scr_path.exists()

        if cam_on_disk:
            cameras = self._load_cam_file(cam_path)
        elif dat_path:
            cameras, cam_from_dat = self._load_cam_from_dat(dat_path, track_name)

        if scr_on_disk:
            segments = self._load_scr_file(scr_path)
        elif dat_path:
            segments, scr_from_dat = self._load_scr_from_dat(dat_path, track_name)

        if cam_from_dat and scr_from_dat:
            camera_source = "dat"
            camera_files_from_dat = not cam_on_disk and not scr_on_disk
        elif cam_on_disk or scr_on_disk:
            camera_source = "files"
            camera_files_from_dat = False
        elif dat_path:
            camera_source = "dat"
            camera_files_from_dat = True

        camera_views = self._build_camera_views(cameras, segments)
        tv_mode_count = max((view.view for view in camera_views), default=0)

        return CameraLoadResult(
            cameras=cameras,
            camera_views=camera_views,
            camera_source=camera_source,
            camera_files_from_dat=camera_files_from_dat,
            dat_path=dat_path,
            tv_mode_count=tv_mode_count,
        )

    def save_cameras(
        self,
        track_folder: Path,
        cameras: Sequence[CameraPosition],
        camera_views: Sequence[CameraViewListing],
        camera_source: str | None,
        dat_path: Path | None,
        camera_files_from_dat: bool,
    ) -> str:
        track_name = track_folder.name
        cam_path = track_folder / f"{track_name}.cam"
        scr_path = track_folder / f"{track_name}.scr"

        self._backup_file(cam_path)
        self._backup_file(scr_path)
        write_cam_positions(cam_path, cameras)
        write_scr_segments(scr_path, camera_views)

        if camera_source == "dat" and dat_path is not None:
            self._repack_dat(dat_path, cam_path, scr_path)
            if camera_files_from_dat:
                if cam_path.exists():
                    cam_path.unlink()
                if scr_path.exists():
                    scr_path.unlink()

        return f"Saved cameras for {track_name}"

    def _load_cam_file(self, cam_path: Path) -> list[CameraPosition]:
        try:
            return load_cam_positions(cam_path)
        except Exception:
            return []

    def _load_scr_file(self, scr_path: Path) -> list[CameraSegmentRange]:
        try:
            return load_scr_segments(scr_path)
        except Exception:
            return []

    def _load_cam_from_dat(
        self, dat_path: Path, track_name: str
    ) -> tuple[list[CameraPosition], bool]:
        try:
            cam_bytes = extract_file_bytes(str(dat_path), f"{track_name}.cam")
            return load_cam_positions_bytes(cam_bytes), True
        except Exception:
            return [], False

    def _load_scr_from_dat(
        self, dat_path: Path, track_name: str
    ) -> tuple[list[CameraSegmentRange], bool]:
        try:
            scr_bytes = extract_file_bytes(str(dat_path), f"{track_name}.scr")
            return load_scr_segments_bytes(scr_bytes), True
        except Exception:
            return [], False

    def _detect_available_lp_files(self, track_folder: Path) -> List[str]:
        available: List[str] = []
        for name in LP_FILE_NAMES:
            if (track_folder / f"{name}.LP").exists():
                available.append(name)
        return available

    def _find_matching_dat(self, track_folder: Path, track_name: str) -> Path | None:
        dat_files = list(track_folder.glob("*.dat"))
        return next(
            (
                candidate
                for candidate in dat_files
                if candidate.stem.lower() == track_name.lower()
            ),
            None,
        )

    def _backup_file(self, path: Path) -> Path | None:
        if not path.exists():
            return None
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_suffix(path.suffix + f".bak.{timestamp}")
        shutil.copy2(path, backup_path)
        return backup_path

    def _repack_dat(self, dat_path: Path, cam_path: Path, scr_path: Path) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            unpackdat.unpackdat(str(dat_path), output_folder=tmpdir)
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
            packdat.packdat(str(packlist_path), str(dat_path), backup=True)

    def _build_camera_views(
        self, cameras: list[CameraPosition], segments: Sequence[CameraSegmentRange]
    ) -> List[CameraViewListing]:
        if not segments:
            return []
        type_buckets: dict[int, dict[int, tuple[int, CameraPosition]]] = {}
        for global_index, camera in enumerate(cameras):
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
                if bucket_entry is not None:
                    camera_index, _ = bucket_entry
                elif 0 <= segment.camera_id < len(cameras):
                    camera_index = segment.camera_id
                    if camera_type is None:
                        camera_type = cameras[camera_index].camera_type
                elif type_buckets:
                    for per_type in type_buckets.values():
                        candidate = per_type.get(segment.camera_id)
                        if candidate is not None:
                            camera_index, _ = candidate
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
