from __future__ import annotations

import pytest

from sg_viewer.services.mrk_io import (
    MarkBoundaryEntry,
    MarkFile,
    MarkTrackPosition,
    MarkUvRect,
    parse_mrk_text,
    serialize_mrk,
)


_SAMPLE_MRK = """\
MARK_V1      ## Header
59 0         ## Start
pit1: Boundary 1 \"walldk\" <0,0> - <1023, 15>
59 0.7
End pit1
"""


def test_parse_mrk_text_reads_boundary_entry() -> None:
    mark_file = parse_mrk_text(_SAMPLE_MRK)

    assert mark_file.version == "MARK_V1"
    assert len(mark_file.entries) == 1
    entry = mark_file.entries[0]
    assert entry.pointer_name == "pit1"
    assert entry.boundary_id == 1
    assert entry.mip_name == "walldk"
    assert entry.start == MarkTrackPosition(section=59, fraction=0.0)
    assert entry.end == MarkTrackPosition(section=59, fraction=0.7)
    assert entry.uv_rect == MarkUvRect(upper_left_u=0, upper_left_v=0, lower_right_u=1023, lower_right_v=15)


def test_serialize_mrk_round_trips() -> None:
    mark_file = MarkFile(
        entries=(
            MarkBoundaryEntry(
                pointer_name="pit1",
                boundary_id=1,
                mip_name="walldk",
                uv_rect=MarkUvRect(upper_left_u=0, upper_left_v=0, lower_right_u=1023, lower_right_v=15),
                start=MarkTrackPosition(section=59, fraction=0.0),
                end=MarkTrackPosition(section=59, fraction=0.7),
            ),
        )
    )

    serialized = serialize_mrk(mark_file)
    reparsed = parse_mrk_text(serialized)

    assert reparsed == mark_file


def test_parse_mrk_text_rejects_duplicate_pointer_names() -> None:
    duplicate = """\
MARK_V1
1 0
pit1: Boundary 0 \"wall\" <0,0> - <1,1>
1 1
End pit1
2 0
pit1: Boundary 1 \"wall\" <0,0> - <1,1>
2 1
End pit1
"""

    with pytest.raises(ValueError, match="Duplicate pointer name"):
        parse_mrk_text(duplicate)


def test_parse_mrk_text_rejects_fraction_out_of_range() -> None:
    invalid_fraction = """\
MARK_V1
1 1.2
pit1: Boundary 0 \"wall\" <0,0> - <1,1>
1 1
End pit1
"""

    with pytest.raises(ValueError, match="Track fraction"):
        parse_mrk_text(invalid_fraction)
