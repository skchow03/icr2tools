from sg_viewer.services.trackside_elevation import tso_relative_boundary_elevation
from sg_viewer.services.trackside_objects import TracksideObject


def test_tso_relative_boundary_elevation_returns_none_without_context() -> None:
    obj = TracksideObject("tree", 0, 0, 100, 0, 0, 0)
    assert tso_relative_boundary_elevation(obj, context=None) is None
