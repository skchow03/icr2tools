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
