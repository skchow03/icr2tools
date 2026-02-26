from types import SimpleNamespace

import pytest

from sg_viewer.model.dlong_mapping import build_dlong_section_lookup, dlong_to_section_position


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


def _legacy_scan_mapping(sections, dlong: float, track_length: float):
    wrapped_dlong = dlong % track_length
    for idx, section in enumerate(sections):
        start = float(section.start_dlong)
        length = float(section.length)
        if length <= 0:
            continue
        end = start + length
        in_range = (
            (start <= wrapped_dlong < end) or abs(wrapped_dlong - end) < 1e-12
            if end <= track_length
            else (
                wrapped_dlong >= start
                or wrapped_dlong < (end - track_length)
                or abs(wrapped_dlong - (end - track_length)) < 1e-12
            )
        )
        if not in_range:
            continue
        fraction = (wrapped_dlong - start) / length
        if end > track_length and wrapped_dlong < start:
            fraction = (wrapped_dlong + track_length - start) / length
        return idx, max(0.0, min(1.0, fraction))
    return len(sections) - 1, 1.0


@pytest.mark.parametrize(
    "sections,track_length,probe_dlongs",
    [
        (
            [_section(0.0, 100.0), _section(100.0, 80.0), _section(180.0, 20.0)],
            200.0,
            [0.0, 50.0, 99.999, 100.0, 179.0, 199.999, 200.0, 260.0],
        ),
        (
            [_section(0.0, 70.0), _section(70.0, 90.0), _section(160.0, 60.0)],
            200.0,
            [0.0, 69.999, 70.0, 159.999, 160.0, 199.999, 215.0, 399.9],
        ),
        (
            [_section(0.0, 100.0), _section(100.0, 120.0)],
            200.0,
            [0.0, 50.0, 100.0, 150.0, 199.999, 205.0, 250.0],
        ),
    ],
)
def test_lookup_path_matches_legacy_scan_behavior(sections, track_length: float, probe_dlongs):
    lookup = build_dlong_section_lookup(sections, track_length)

    for probe in probe_dlongs:
        mapped = dlong_to_section_position(sections, probe, track_length=track_length, lookup=lookup)
        assert mapped is not None
        expected_index, expected_fraction = _legacy_scan_mapping(sections, probe, track_length)
        assert mapped.section_index == expected_index
        assert mapped.fraction == pytest.approx(expected_fraction)
