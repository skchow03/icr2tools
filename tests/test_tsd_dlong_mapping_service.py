from types import SimpleNamespace
from sg_viewer.services.tsd_dlong_mapping import adjusted_dlong_to_sg_dlong, build_adjusted_to_sg_ranges


def _section(index: int, start_dlong: float, length: float) -> SimpleNamespace:
    return SimpleNamespace(start_dlong=start_dlong, length=length)


def test_build_adjusted_to_sg_ranges_and_convert_dlongs() -> None:
    ranges = build_adjusted_to_sg_ranges(
        [_section(0, 0, 100), _section(1, 100, 100)],
        lambda index: [(0, 50), (50, 150)][index],
    )

    assert ranges == ([(0.0, 50.0, 0.0, 100.0), (50.0, 150.0, 100.0, 200.0)], [0.0, 50.0, 50.0, 150.0])
    assert adjusted_dlong_to_sg_dlong(25, ranges) == 50
    assert adjusted_dlong_to_sg_dlong(100, ranges) == 150
    assert adjusted_dlong_to_sg_dlong(175, ranges) == 50


def test_build_adjusted_to_sg_ranges_returns_empty_when_range_missing() -> None:
    assert build_adjusted_to_sg_ranges([_section(0, 0, 100)], lambda _index: None) == ([], [])
