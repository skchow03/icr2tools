from sg_viewer.io.track3d_parser import Track3DSectionDlongList
from sg_viewer.services.tso_visibility_ranges import build_subsection_dlong_metadata


def test_subindex_ranges_extend_to_the_next_subindex_start():
    ranges, starts = build_subsection_dlong_metadata(
        [
            Track3DSectionDlongList(section=12, sub_index=0, dlongs=(1000, 1100, 1200)),
            Track3DSectionDlongList(section=12, sub_index=1, dlongs=(1300, 1400, 1490)),
            Track3DSectionDlongList(section=12, sub_index=2, dlongs=(1500, 1600, 1700)),
        ]
    )

    assert ranges == {
        (12, 0): (1000, 1300),
        (12, 1): (1300, 1500),
        (12, 2): (1500, 1700),
    }
    assert starts == {12: (1000, 1300, 1500)}


def test_terminal_subindex_extends_to_the_next_section_start_when_available():
    ranges, starts = build_subsection_dlong_metadata(
        [
            Track3DSectionDlongList(section=8, sub_index=0, dlongs=(200, 240, 260)),
            Track3DSectionDlongList(section=8, sub_index=1, dlongs=(300, 360, 390)),
            Track3DSectionDlongList(section=9, sub_index=0, dlongs=(450, 500, 540)),
        ]
    )

    assert ranges[(8, 0)] == (200, 300)
    assert ranges[(8, 1)] == (300, 450)
    assert ranges[(9, 0)] == (450, 540)
    assert starts == {8: (200, 300), 9: (450,)}


def test_terminal_subindex_keeps_its_recorded_end_dlong_without_a_following_section():
    ranges, starts = build_subsection_dlong_metadata(
        [
            Track3DSectionDlongList(section=8, sub_index=0, dlongs=(200, 240, 260)),
            Track3DSectionDlongList(section=8, sub_index=1, dlongs=(300, 360, 390)),
        ]
    )

    assert ranges[(8, 0)] == (200, 300)
    assert ranges[(8, 1)] == (300, 390)
    assert starts == {8: (200, 300)}
