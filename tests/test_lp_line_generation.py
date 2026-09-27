from types import SimpleNamespace

import numpy as np

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


def test_generate_lp_speeds_uses_wrapped_pit_dlong_zone(monkeypatch) -> None:
    model = _build_model()
    dlongs = (0.0, 3000.0, 6000.0, 9000.0)
    xy = ((6000.0, 0.0), (0.0, 6000.0), (-6000.0, 0.0), (0.0, -6000.0))
    model._ai_lines = {
        "RACE": [
            SimpleNamespace(
                dlong=dlong,
                dlat=0.0,
                x=x,
                y=y,
                speed_mph=0.0,
                speed_raw=0,
            )
            for dlong, (x, y) in zip(dlongs, xy)
        ]
    }
    monkeypatch.setattr(
        "track_viewer.model.track_preview_model.build_trk_banking_profile",
        lambda *_args, **_kwargs: SimpleNamespace(
            at_dlats=lambda dlats: np.zeros(len(dlats))
        ),
    )
    captured = {}

    def _fake_speed_profile(points, performance, **kwargs):
        captured["limits"] = kwargs["speed_limits_mph"].copy()
        return kwargs["speed_limits_mph"]

    monkeypatch.setattr(
        "track_viewer.model.track_preview_model.speed_profile_mph",
        _fake_speed_profile,
    )

    success, message = model.recalculate_lp_speed_profile(
        "RACE",
        pit_speed_limit_mph=79.0,
        pit_speed_limit_start_dlong=8000.0,
        pit_speed_limit_end_dlong=2000.0,
    )

    assert success is True
    assert np.array_equal(captured["limits"], [79.0, 245.0, 245.0, 79.0])
    assert "Pit speed zone: 79.0 mph across 2 LP samples" in message
