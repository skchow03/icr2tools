from types import SimpleNamespace

from track_viewer.model.track_preview_model import TrackPreviewModel


def _build_model() -> TrackPreviewModel:
    model = TrackPreviewModel()
    model.trk = SimpleNamespace(
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
