"""I/O helpers for loading and saving track resources."""
from __future__ import annotations

import csv
import datetime
import struct
import shutil
import tempfile
from dataclasses import dataclass, field
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
from track_viewer.pit_models import PIT_PARAMETER_DEFINITIONS, PitParameters

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
class TrackTxtLine:
    """Represents a line in the track TXT file."""

    raw: str
    keyword: str | None = None
    values: list[str] = field(default_factory=list)


@dataclass
class TrackTxtResult:
    """Parsed track TXT data."""

    lines: list[TrackTxtLine]
    pit: PitParameters | None
    metadata: "TrackTxtMetadata"
    txt_path: Path
    exists: bool


@dataclass
class TrackTxtMetadata:
    """Non-pit track TXT parameters."""

    tname: str | None = None
    sname: str | None = None
    cityn: str | None = None
    count: str | None = None
    spdwy_start: int | None = None
    spdwy_end: int | None = None
    spdwy_flag: int | None = None
    lengt: int | None = None
    laps: int | None = None
    fname: str | None = None
    pacea_cars_abreast: int | None = None
    pacea_start_dlong: int | None = None
    pacea_right_dlat: int | None = None
    pacea_left_dlat: int | None = None
    pacea_unknown: int | None = None


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

    def load_track_txt(self, track_folder: Path) -> TrackTxtResult:
        track_name = track_folder.name
        txt_path = track_folder / f"{track_name}.txt"
        if not txt_path.exists():
            return TrackTxtResult([], None, TrackTxtMetadata(), txt_path, False)
        lines: list[TrackTxtLine] = []
        pit: PitParameters | None = None
        metadata = TrackTxtMetadata()
        for raw_line in txt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(("#", ";")):
                lines.append(TrackTxtLine(raw=raw_line))
                continue
            tokens = stripped.split()
            keyword = tokens[0]
            values = tokens[1:]
            line = TrackTxtLine(raw=raw_line, keyword=keyword, values=values)
            lines.append(line)
            keyword_upper = keyword.upper()
            if keyword_upper == "PIT" and pit is None:
                parsed = self._parse_pit_values(values)
                if parsed is not None:
                    pit = parsed
            elif keyword_upper == "TNAME" and metadata.tname is None and values:
                metadata.tname = " ".join(values)
            elif keyword_upper == "SNAME" and metadata.sname is None and values:
                metadata.sname = " ".join(values)
            elif keyword_upper == "CITYN" and metadata.cityn is None and values:
                metadata.cityn = " ".join(values)
            elif keyword_upper == "COUNT" and metadata.count is None and values:
                metadata.count = " ".join(values)
            elif keyword_upper == "FNAME" and metadata.fname is None and values:
                metadata.fname = " ".join(values)
            elif keyword_upper == "SPDWY" and metadata.spdwy_start is None:
                parsed = self._parse_spdwy_values(values)
                if parsed is not None:
                    (
                        metadata.spdwy_flag,
                        metadata.spdwy_start,
                        metadata.spdwy_end,
                    ) = parsed
            elif keyword_upper == "LENGT" and metadata.lengt is None and values:
                parsed = self._parse_track_integer(values[0])
                if parsed is not None:
                    metadata.lengt = parsed
            elif keyword_upper == "LAPS" and metadata.laps is None and values:
                parsed = self._parse_track_integer(values[0])
                if parsed is not None:
                    metadata.laps = parsed
            elif keyword_upper == "PACEA" and metadata.pacea_cars_abreast is None:
                parsed = self._parse_pacea_values(values)
                if parsed is not None:
                    (
                        metadata.pacea_cars_abreast,
                        metadata.pacea_start_dlong,
                        metadata.pacea_right_dlat,
                        metadata.pacea_left_dlat,
                        metadata.pacea_unknown,
                    ) = parsed
        return TrackTxtResult(lines, pit, metadata, txt_path, True)

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

    def save_track_txt(
        self,
        track_folder: Path,
        pit_params: PitParameters | None,
        metadata: TrackTxtMetadata | None,
        lines: Sequence[TrackTxtLine],
    ) -> str:
        track_name = track_folder.name
        txt_path = track_folder / f"{track_name}.txt"
        self._backup_file(txt_path)
        pit_line = self._format_pit_line(pit_params) if pit_params is not None else None
        replacements = self._build_track_txt_replacements(pit_line, metadata)
        output_lines: list[str] = []
        written = set()
        for line in lines:
            keyword = line.keyword.upper() if line.keyword else None
            if keyword in replacements:
                replacement = replacements[keyword]
                if replacement is not None:
                    output_lines.append(replacement)
                    written.add(keyword)
                continue
            output_lines.append(line.raw)
        for keyword, replacement in replacements.items():
            if replacement is None or keyword in written:
                continue
            output_lines.append(replacement)
        txt_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
        return f"Saved track.txt parameters to {txt_path.name}"

    def save_lp_line(self, track_folder: Path, lp_name: str, records: Sequence[object]) -> str:
        lp_path = track_folder / f"{lp_name}.LP"
        self._backup_file(lp_path)
        record_count = len(records)
        with lp_path.open("wb") as handle:
            handle.write(struct.pack("<i", record_count))
            for record in records:
                speed_mph = float(getattr(record, "speed_mph"))
                lateral_speed = float(getattr(record, "lateral_speed"))
                dlat = float(getattr(record, "dlat"))
                speed_raw = int(round(speed_mph * 5280 / 9))
                coriolis = int(round(lateral_speed))
                dlat_int = int(round(dlat))
                handle.write(struct.pack("<i", speed_raw))
                handle.write(struct.pack("<i", coriolis))
                handle.write(struct.pack("<i", dlat_int))
        return f"Saved {lp_name}.LP"

    def export_lp_csv(
        self, output_path: Path, lp_name: str, records: Sequence[object]
    ) -> str:
        fields = [
            "dlong",
            "dlat",
            "speed_raw",
            "speed_mph",
            "lateral_speed",
            "angle_deg",
            "x",
            "y",
        ]
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for record in records:
                writer.writerow(
                    {
                        "dlong": getattr(record, "dlong", None),
                        "dlat": getattr(record, "dlat", None),
                        "speed_raw": getattr(record, "speed_raw", None),
                        "speed_mph": getattr(record, "speed_mph", None),
                        "lateral_speed": getattr(record, "lateral_speed", None),
                        "angle_deg": getattr(record, "angle_deg", None),
                        "x": getattr(record, "x", None),
                        "y": getattr(record, "y", None),
                    }
                )
        return f"Exported {lp_name} to {output_path}"

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

    def _parse_pit_values(self, values: Sequence[str]) -> PitParameters | None:
        expected = len(PIT_PARAMETER_DEFINITIONS)
        if len(values) < expected - 1:
            return None
        numeric_values: list[float] = []
        for value, (_, _, _, is_integer) in zip(values, PIT_PARAMETER_DEFINITIONS):
            try:
                parsed = float(value)
            except ValueError:
                return None
            if is_integer:
                parsed = int(round(parsed))
            numeric_values.append(parsed)
        if len(numeric_values) < expected:
            numeric_values.append(0.0)
        return PitParameters.from_values(numeric_values)

    def _parse_spdwy_values(
        self, values: Sequence[str]
    ) -> tuple[int, int, int] | None:
        if len(values) < 3:
            return None
        flag_value = self._parse_track_integer(values[0])
        start_value = self._parse_track_integer(values[1])
        end_value = self._parse_track_integer(values[2])
        if flag_value is None or start_value is None or end_value is None:
            return None
        return flag_value, start_value, end_value

    def _parse_pacea_values(
        self, values: Sequence[str]
    ) -> tuple[int, int, int, int, int] | None:
        if len(values) < 5:
            return None
        parsed_values: list[int] = []
        for value in values[:5]:
            parsed = self._parse_track_integer(value)
            if parsed is None:
                return None
            parsed_values.append(parsed)
        return tuple(parsed_values)  # type: ignore[return-value]

    @staticmethod
    def _parse_track_integer(value: str) -> int | None:
        try:
            return int(round(float(value)))
        except ValueError:
            return None

    @staticmethod
    def _format_track_txt_value(value: float) -> str:
        if float(value).is_integer():
            return str(int(round(value)))
        return f"{value:.6f}".rstrip("0").rstrip(".")

    def _format_pit_line(self, pit_params: PitParameters) -> str:
        formatted_values = [
            self._format_track_txt_value(value) for value in pit_params.values()
        ]
        return "PIT " + " ".join(formatted_values)

    def _build_track_txt_replacements(
        self,
        pit_line: str | None,
        metadata: TrackTxtMetadata | None,
    ) -> dict[str, str | None]:
        replacements: dict[str, str | None] = {}
        if pit_line is not None:
            replacements["PIT"] = pit_line
        if metadata is None:
            return replacements
        replacements["TNAME"] = (
            f"TNAME {metadata.tname}" if metadata.tname else None
        )
        replacements["SNAME"] = (
            f"SNAME {metadata.sname}" if metadata.sname else None
        )
        replacements["CITYN"] = (
            f"CITYN {metadata.cityn}" if metadata.cityn else None
        )
        replacements["COUNT"] = (
            f"COUNT {metadata.count}" if metadata.count else None
        )
        replacements["FNAME"] = (
            f"FNAME {metadata.fname}" if metadata.fname else None
        )
        if metadata.spdwy_start is not None and metadata.spdwy_end is not None:
            flag = metadata.spdwy_flag if metadata.spdwy_flag is not None else 0
            replacements["SPDWY"] = (
                f"SPDWY {flag} {metadata.spdwy_start} {metadata.spdwy_end}"
            )
        else:
            replacements["SPDWY"] = None
        replacements["LENGT"] = (
            f"LENGT {metadata.lengt}" if metadata.lengt is not None else None
        )
        replacements["LAPS"] = (
            f"LAPS {metadata.laps}" if metadata.laps is not None else None
        )
        pacea_values = (
            metadata.pacea_cars_abreast,
            metadata.pacea_start_dlong,
            metadata.pacea_right_dlat,
            metadata.pacea_left_dlat,
            metadata.pacea_unknown,
        )
        if all(value is not None for value in pacea_values):
            replacements["PACEA"] = "PACEA " + " ".join(
                str(int(value)) for value in pacea_values  # type: ignore[arg-type]
            )
        else:
            replacements["PACEA"] = None
        return replacements

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
