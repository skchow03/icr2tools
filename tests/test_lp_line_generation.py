from types import SimpleNamespace

from track_viewer.model.track_preview_model import TrackPreviewModel


def _build_model() -> TrackPreviewModel:
    model = TrackPreviewModel()
    model.trk = SimpleNamespace(
        trklength=12000.0,
        num_sects=1,
        sects=[
            SimpleNamespace(
                start_dlong=0.0,
                length=12000.0,
                num_bounds=2,
                bound_dlat_start=[-50.0, 10.0],
                bound_dlat_end=[-70.0, 30.0],
            )
        ],
    )
    model.centerline = [(0.0, 0.0)]
    model.track_length = 12000.0
    model.available_lp_files = ["RACE"]
    return model


def test_generate_lp_line_uses_boundary_dlat_and_margin(monkeypatch) -> None:
    model = _build_model()
    monkeypatch.setattr(
        "track_viewer.model.track_preview_model.getxyz",
        lambda _trk, dlong, dlat, _cline: (float(dlong), float(dlat), 0.0),
    )

    success, message = model.generate_lp_line(
        "RACE",
        120.0,
        0.0,
        boundary_index=1,
        wall_margin=-2.0,
    )

    assert success is True
    assert "Generated RACE LP line" in message
    records = model.ai_line_records("RACE")
    assert [record.dlong for record in records] == [0.0, 6000.0, 12000.0]
    assert [record.dlat for record in records] == [8.0, 18.0, 28.0]


def test_generate_lp_line_boundary_index_validates_section_bounds(monkeypatch) -> None:
    model = _build_model()
    monkeypatch.setattr(
        "track_viewer.model.track_preview_model.getxyz",
        lambda _trk, dlong, dlat, _cline: (float(dlong), float(dlat), 0.0),
    )

    success, message = model.generate_lp_line(
        "RACE",
        120.0,
        0.0,
        boundary_index=2,
    )

    assert success is False
    assert "Boundary 2 is unavailable in section 0" in message


def test_generate_lp_line_replaces_existing_records_using_current_track_length(
    monkeypatch,
) -> None:
    model = _build_model()
    monkeypatch.setattr(
        "track_viewer.model.track_preview_model.getxyz",
        lambda _trk, dlong, dlat, _cline: (float(dlong), float(dlat), 0.0),
    )

    model._ai_lines = {
        "RACE": [SimpleNamespace(dlong=0.0), SimpleNamespace(dlong=12000.0)]
    }
    model.track_length = 12000.0
    model.trk.trklength = 18000.0

    success, _ = model.generate_lp_line("RACE", 100.0, 0.0)

    assert success is True
    records = model.ai_line_records("RACE")
    assert [record.dlong for record in records] == [0.0, 6000.0, 12000.0, 18000.0]


def test_closest_boundary_elevation_at_returns_nearest_boundary_height(
    monkeypatch,
) -> None:
    model = _build_model()

    def _fake_getxyz(_trk, dlong, dlat, _cline):
        return (float(dlong), float(dlat), float(dlong + (dlat * 10.0)))

    monkeypatch.setattr("track_viewer.model.track_preview_model.getxyz", _fake_getxyz)

    elevation = model.closest_boundary_elevation_at(0.0, 9.0)

    assert elevation == 90


def test_closest_boundary_elevation_at_returns_none_without_track() -> None:
    model = TrackPreviewModel()

    assert model.closest_boundary_elevation_at(0.0, 0.0) is None
