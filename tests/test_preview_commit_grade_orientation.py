from __future__ import annotations

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.preview.edit_session import apply_preview_to_sgfile


def _make_sgfile(num_xsects: int = 3) -> SGFile:
    record_length = 58 + 2 * num_xsects
    data = [0] * record_length
    data[0] = 1
    data[3] = 10
    data[4] = 20
    data[5] = 30
    data[6] = 40
    data[17] = 100
    data[18] = 5
    data[19] = 200
    data[20] = -3
    data[21] = 300
    data[22] = 7
    section = SGFile.Section(data, num_xsects)
    header = [0, 0, 0, 0, 1, num_xsects]
    return SGFile(header, 1, num_xsects, [0] * num_xsects, [section])


def _preview(start: tuple[float, float], end: tuple[float, float]) -> SectionPreview:
    return SectionPreview(
        section_id=0,
        source_section_id=0,
        type_name="straight",
        previous_id=-1,
        next_id=-1,
        start=start,
        end=end,
        start_dlong=0.0,
        length=100.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=None,
        end_heading=None,
        polyline=[],
    )


def test_apply_preview_to_sgfile_keeps_grade_when_orientation_matches() -> None:
    sgfile = _make_sgfile()

    apply_preview_to_sgfile(sgfile, [_preview((10.0, 20.0), (30.0, 40.0))])

    assert sgfile.sects[0].alt == [100, 200, 300]
    assert sgfile.sects[0].grade == [5, -3, 7]


def test_apply_preview_to_sgfile_reverses_and_negates_grade_when_reversed() -> None:
    sgfile = _make_sgfile()

    apply_preview_to_sgfile(sgfile, [_preview((30.0, 40.0), (10.0, 20.0))])

    assert sgfile.sects[0].alt == [300, 200, 100]
    assert sgfile.sects[0].grade == [-7, 3, -5]


def test_apply_preview_to_sgfile_reverse_track_shifts_elevation_source_and_negates_grade() -> None:
    num_xsects = 3
    record_length = 58 + 2 * num_xsects

    sec0_data = [0] * record_length
    sec0_data[0] = 1
    sec0_data[1] = 1
    sec0_data[2] = 1
    sec0_data[3] = 0
    sec0_data[4] = 0
    sec0_data[5] = 10
    sec0_data[6] = 0
    sec0_data[17] = 100
    sec0_data[18] = 10
    sec0_data[19] = 200
    sec0_data[20] = 20
    sec0_data[21] = 300
    sec0_data[22] = 30

    sec1_data = [0] * record_length
    sec1_data[0] = 1
    sec1_data[1] = 0
    sec1_data[2] = 0
    sec1_data[3] = 10
    sec1_data[4] = 0
    sec1_data[5] = 0
    sec1_data[6] = 0
    sec1_data[17] = 400
    sec1_data[18] = 40
    sec1_data[19] = 500
    sec1_data[20] = 50
    sec1_data[21] = 600
    sec1_data[22] = 60

    header = [0, 0, 0, 0, 2, num_xsects]
    sgfile = SGFile(
        header,
        2,
        num_xsects,
        [0] * num_xsects,
        [SGFile.Section(sec0_data, num_xsects), SGFile.Section(sec1_data, num_xsects)],
    )

    reversed_preview = [
        SectionPreview(
            section_id=0,
            source_section_id=1,
            type_name="straight",
            previous_id=1,
            next_id=1,
            start=(0.0, 0.0),
            end=(10.0, 0.0),
            start_dlong=0.0,
            length=100.0,
            center=None,
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=None,
            start_heading=None,
            end_heading=None,
            polyline=[],
        ),
        SectionPreview(
            section_id=1,
            source_section_id=0,
            type_name="straight",
            previous_id=0,
            next_id=0,
            start=(10.0, 0.0),
            end=(0.0, 0.0),
            start_dlong=100.0,
            length=100.0,
            center=None,
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=None,
            start_heading=None,
            end_heading=None,
            polyline=[],
        ),
    ]

    apply_preview_to_sgfile(sgfile, reversed_preview)

    assert sgfile.sects[0].alt == [300, 200, 100]
    assert sgfile.sects[0].grade == [-30, -20, -10]
    assert sgfile.sects[1].alt == [600, 500, 400]
    assert sgfile.sects[1].grade == [-60, -50, -40]
