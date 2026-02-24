from types import SimpleNamespace

from sg_viewer.model.dlong_mapping import DlongSectionIndex, dlong_to_section_position


def _section(start_dlong: float, length: float):
    return SimpleNamespace(start_dlong=start_dlong, length=length)


def test_maps_dlong_to_expected_section_and_fraction():
    sections = [_section(0.0, 100.0), _section(100.0, 50.0), _section(150.0, 50.0)]

    mapped = dlong_to_section_position(sections, 125.0, track_length=200.0)

    assert mapped is not None
    assert mapped.section_index == 1
    assert mapped.fraction == 0.5


def test_wraps_dlong_when_it_exceeds_track_length():
    sections = [_section(0.0, 75.0), _section(75.0, 75.0), _section(150.0, 50.0)]

    mapped = dlong_to_section_position(sections, 210.0, track_length=200.0)

    assert mapped is not None
    assert mapped.section_index == 0
    assert mapped.fraction == 10.0 / 75.0


def test_supports_section_range_that_crosses_start_finish():
    sections = [_section(0.0, 100.0), _section(100.0, 80.0), _section(180.0, 40.0)]

    mapped = dlong_to_section_position(sections, 195.0, track_length=200.0)

    assert mapped is not None
    assert mapped.section_index == 2
    assert mapped.fraction == 15.0 / 40.0


def test_maps_exact_section_end_to_closing_section():
    sections = [_section(0.0, 100.0), _section(100.0, 40.0)]

    mapped = dlong_to_section_position(sections, 100.0, track_length=140.0)

    assert mapped is not None
    assert mapped.section_index == 0
    assert mapped.fraction == 1.0


def test_index_handles_wrapped_ranges():
    sections = [_section(0.0, 100.0), _section(100.0, 80.0), _section(180.0, 40.0)]
    index = DlongSectionIndex.build(sections, track_length=200.0)

    assert index is not None
    mapped = index.lookup(5.0)

    assert mapped.section_index == 0
    assert mapped.fraction == 0.05


def test_index_falls_back_to_last_section_for_degenerate_inputs():
    sections = [_section(100.0, 10.0), _section(0.0, 0.0), _section(10.0, 10.0)]
    index = DlongSectionIndex.build(sections, track_length=25.0)

    assert index is not None
    mapped = index.lookup(22.0)

    assert mapped.section_index == 2
    assert mapped.fraction == 1.0
