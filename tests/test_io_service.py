"""Unit tests for the track viewer I/O service helpers."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from icr2_core.cam.helpers import (
    CameraPosition,
    Type6CameraParameters,
    load_cam_positions_bytes,
    load_scr_segments_bytes,
    write_cam_positions,
    write_scr_segments,
)
from icr2_core.dat import packdat, unpackdat
from icr2_core.dat.unpackdat import extract_file_bytes
from track_viewer.model.camera_models import CameraViewEntry, CameraViewListing
from track_viewer.services.io_service import CameraLoadResult, TrackIOService


@pytest.fixture()
def sample_cameras() -> list[CameraPosition]:
    return [
        CameraPosition(
            camera_type=6,
            index=0,
            x=1,
            y=2,
            z=3,
            type6=Type6CameraParameters(
                middle_point=0,
                start_point=0,
                start_zoom=0,
                middle_point_zoom=0,
                end_point=0,
                end_zoom=0,
            ),
        )
    ]


@pytest.fixture()
def sample_views() -> list[CameraViewListing]:
    return [
        CameraViewListing(
            view=2,
            label="TV2",
            entries=[
                CameraViewEntry(
                    camera_index=0,
                    type_index=0,
                    camera_type=6,
                    start_dlong=10,
                    end_dlong=20,
                    mark=None,
                )
            ],
        )
    ]


def test_load_track_uses_core_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = TrackIOService()
    track_folder = tmp_path / "SPEEDWAY"
    track_folder.mkdir()
    (track_folder / "RACE.LP").write_bytes(b"")

    dummy_trk = object()

    monkeypatch.setattr(
        "track_viewer.services.io_service.load_trk_from_folder",
        lambda path: dummy_trk if path == str(track_folder) else None,
    )
    monkeypatch.setattr(
        "track_viewer.services.io_service.get_cline_pos", lambda trk: [(1.0, 2.0)] if trk is dummy_trk else []
    )
    monkeypatch.setattr(
        "track_viewer.services.io_service.build_ground_surface_mesh", lambda trk, cline: ["mesh", trk, tuple(cline)]
    )
    monkeypatch.setattr("track_viewer.services.io_service.compute_mesh_bounds", lambda mesh: (0.0, 1.0, -1.0, 2.0))

    result = service.load_track(track_folder)

    assert result.trk is dummy_trk
    assert result.centerline == [(1.0, 2.0)]
    assert result.surface_mesh[0] == "mesh"
    assert result.surface_bounds == (0.0, 1.0, -1.0, 2.0)
    assert result.available_lp_files == ["RACE"]


def test_load_cameras_prefers_files(tmp_path: Path, sample_cameras: list[CameraPosition], sample_views: list[CameraViewListing]) -> None:
    service = TrackIOService()
    track_folder = tmp_path / "TEST"
    track_folder.mkdir()

    cam_path = track_folder / "TEST.cam"
    scr_path = track_folder / "TEST.scr"
    write_cam_positions(cam_path, sample_cameras)
    write_scr_segments(scr_path, sample_views)

    result = service.load_cameras(track_folder)

    assert isinstance(result, CameraLoadResult)
    assert result.camera_source == "files"
    assert result.dat_path is None
    assert not result.camera_files_from_dat
    assert len(result.cameras) == 1
    assert result.cameras[0].x == 1
    assert result.camera_views and result.camera_views[0].view == 2
    assert result.tv_mode_count == 2


def _build_dat_archive(track_folder: Path, track_name: str, cam_views: list[CameraViewListing], cameras: list[CameraPosition], *, extra: bool = False) -> Path:
    unpack_dir = track_folder / "unpack"
    unpack_dir.mkdir()
    cam_path = unpack_dir / f"{track_name}.cam"
    scr_path = unpack_dir / f"{track_name}.scr"
    write_cam_positions(cam_path, cameras)
    write_scr_segments(scr_path, cam_views)

    packlist_path = unpack_dir / "packlist.txt"
    entries = []
    if extra:
        extra_path = unpack_dir / "existing.txt"
        extra_path.write_text("placeholder")
        entries.append(extra_path.name)
    entries.extend([cam_path.name, scr_path.name])
    packlist_path.write_text("\n".join(entries) + "\n")

    dat_path = track_folder / f"{track_name}.dat"
    packdat.packdat(str(packlist_path), str(dat_path), backup=False)
    return dat_path


def test_load_cameras_falls_back_to_dat(tmp_path: Path, sample_cameras: list[CameraPosition], sample_views: list[CameraViewListing]) -> None:
    service = TrackIOService()
    track_folder = tmp_path / "FROMDAT"
    track_folder.mkdir()
    dat_path = _build_dat_archive(track_folder, "FROMDAT", sample_views, sample_cameras)

    result = service.load_cameras(track_folder)

    assert result.camera_source == "dat"
    assert result.dat_path == dat_path
    assert result.camera_files_from_dat
    assert result.cameras[0].camera_type == 6
    assert result.camera_views[0].entries[0].camera_index == 0
    assert result.tv_mode_count == 2


def test_save_cameras_repacks_dat_and_removes_temp_files(
    tmp_path: Path, sample_cameras: list[CameraPosition], sample_views: list[CameraViewListing]
) -> None:
    service = TrackIOService()
    track_folder = tmp_path / "SAVE"
    track_folder.mkdir()
    dat_path = _build_dat_archive(track_folder, "SAVE", sample_views, sample_cameras, extra=True)

    message = service.save_cameras(
        track_folder,
        sample_cameras,
        sample_views,
        camera_source="dat",
        dat_path=dat_path,
        camera_files_from_dat=True,
    )

    assert "Saved cameras" in message
    assert not (track_folder / "SAVE.cam").exists()
    assert not (track_folder / "SAVE.scr").exists()

    extracted_cam = extract_file_bytes(str(dat_path), "SAVE.cam")
    extracted_scr = extract_file_bytes(str(dat_path), "SAVE.scr")
    assert load_cam_positions_bytes(extracted_cam)[0].x == sample_cameras[0].x
    assert load_scr_segments_bytes(extracted_scr)[0].view == sample_views[0].view

    with tempfile.TemporaryDirectory() as tmpdir:
        unpackdat.unpackdat(str(dat_path), output_folder=tmpdir)
        packlist_entries = (Path(tmpdir) / "packlist.txt").read_text().splitlines()
        assert "existing.txt" in packlist_entries
        assert "SAVE.cam" in packlist_entries
        assert "SAVE.scr" in packlist_entries
