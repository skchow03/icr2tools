from types import SimpleNamespace

from track_viewer.widget.interaction import projection_utils


def test_track_elevation_uses_hover_dlong_and_dlat(monkeypatch):
    calls = []

    def fake_getxyz(trk, dlong, dlat, centerline):
        calls.append((trk, dlong, dlat, centerline))
        return 1.0, 2.0, 123.45

    monkeypatch.setattr(projection_utils, "getxyz", fake_getxyz)
    model = SimpleNamespace(trk="trk", centerline="cline")

    assert projection_utils.track_elevation_at(model, 100.5, -2500) == 123.45
    assert calls == [("trk", 100.5, -2500.0, "cline")]


def test_track_elevation_requires_track_position_data(monkeypatch):
    def fake_getxyz(*_args):
        raise AssertionError("getxyz should not be called without complete data")

    monkeypatch.setattr(projection_utils, "getxyz", fake_getxyz)

    assert (
        projection_utils.track_elevation_at(
            SimpleNamespace(trk=None, centerline="cline"), 1, 2
        )
        is None
    )
    assert (
        projection_utils.track_elevation_at(
            SimpleNamespace(trk="trk", centerline=None), 1, 2
        )
        is None
    )
    assert (
        projection_utils.track_elevation_at(
            SimpleNamespace(trk="trk", centerline="cline"), None, 2
        )
        is None
    )
    assert (
        projection_utils.track_elevation_at(
            SimpleNamespace(trk="trk", centerline="cline"), 1, None
        )
        is None
    )
