import pytest
import math

from sg_viewer.geometry.sg_geometry import rotate_section
from sg_viewer.model.sg_model import SectionPreview


def _section() -> SectionPreview:
    return SectionPreview(
        section_id=0,
        source_section_id=0,
        type_name="straight",
        previous_id=-1,
        next_id=-1,
        start=(1.0, 0.0),
        end=(2.0, 0.0),
        start_dlong=0.0,
        length=1.0,
        center=None,
        sang1=1.0,
        sang2=0.0,
        eang1=1.0,
        eang2=0.0,
        radius=None,
        start_heading=(1.0, 0.0),
        end_heading=(1.0, 0.0),
        polyline=[(1.0, 0.0), (2.0, 0.0)],
    )


def test_rotate_section_rotates_points_and_headings():
    rotated = rotate_section(_section(), math.pi / 2)

    assert rotated.start[0] == pytest.approx(0.0)
    assert rotated.start[1] == pytest.approx(1.0)
    assert rotated.end[0] == pytest.approx(0.0)
    assert rotated.end[1] == pytest.approx(2.0)
    assert rotated.start_heading[0] == pytest.approx(0.0)
    assert rotated.start_heading[1] == pytest.approx(1.0)
    assert rotated.end_heading[0] == pytest.approx(0.0)
    assert rotated.end_heading[1] == pytest.approx(1.0)
    assert rotated.sang1 == pytest.approx(0.0)
    assert rotated.sang2 == pytest.approx(1.0)
