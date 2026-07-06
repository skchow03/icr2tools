from pathlib import Path

from sg_viewer.io.track3d_parser import (
    Track3DObjectList,
    parse_track3d,
    parse_track3d_section_dlongs,
    parse_track3d_section_pointers,
    save_object_lists_to_track3d,
    track3d_has_object_lists,
)


def test_parse_track3d_extracts_object_lists(tmp_path: Path):
    sample = """3D VERSION 3.0;
ObjectList_L9_4: LIST {__TSO111, __TSO105, __TSO107};
ObjectList_R22_2: LIST {__TSO301, __TSO302, __TSO303, __TSO304};
foo
"""
    path = tmp_path / "track.3D"
    path.write_text(sample, encoding="utf-8")

    results = parse_track3d(path)

    assert len(results) == 2

    assert results[0].side == "L"
    assert results[0].section == 9
    assert results[0].sub_index == 4
    assert results[0].tso_ids == [111, 105, 107]

    assert results[1].side == "R"
    assert results[1].section == 22
    assert results[1].sub_index == 2
    assert results[1].tso_ids == [301, 302, 303, 304]


def test_parse_track3d_ignores_non_tso_items(tmp_path: Path):
    sample = "ObjectList_L1_0: LIST {__TSO12, BAD, __TSO7, thing};\n"
    path = tmp_path / "track.3d"
    path.write_text(sample, encoding="utf-8")

    results = parse_track3d(path)

    assert len(results) == 1
    assert results[0].tso_ids == [12, 7]


def test_track3d_has_object_lists_detects_presence(tmp_path: Path):
    path = tmp_path / "track.3d"
    path.write_text("ObjectList_L1_0: LIST {__TSO12};\n", encoding="utf-8")

    assert track3d_has_object_lists(path) is True


def test_track3d_has_object_lists_detects_absence(tmp_path: Path):
    path = tmp_path / "track.3d"
    path.write_text("sec0_l0: LIST { DATA { 0, 10, 20 } };\n", encoding="utf-8")

    assert track3d_has_object_lists(path) is False


def test_save_object_lists_to_track3d_replaces_rows_and_creates_backup(tmp_path: Path):
    original = """3D VERSION 3.0;
HeaderThing: 1;
ObjectList_L9_4: LIST {__TSO111, __TSO105, __TSO107};
ObjectList_R22_2: LIST {__TSO301, __TSO302};
TailThing: 2;
"""
    path = tmp_path / "track.3D"
    path.write_text(original, encoding="utf-8")

    replacement = [
        Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[5, 6]),
        Track3DObjectList(side="R", section=7, sub_index=3, tso_ids=[]),
    ]

    backup_path = save_object_lists_to_track3d(path, replacement)

    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == original

    updated = path.read_text(encoding="utf-8")
    assert "ObjectList_L9_4" not in updated
    assert "ObjectList_R22_2" not in updated
    assert "ObjectList_L1_0: LIST { __TSO5, __TSO6 };" in updated
    assert "ObjectList_R7_3: LIST {  };" in updated
    assert "HeaderThing: 1;" in updated
    assert "TailThing: 2;" in updated


def test_parse_track3d_section_dlongs_extracts_data_blocks(tmp_path: Path):
    sample = """sec0_l0: LIST { sec0_s0_HI, sec0_s1_HI, sec0_s0_MED, sec0_s0_LO, DATA { 0, 10, 20, 30 } };
sec1_l0: LIST { sec1_s0_HI, nil, nil, nil, sec1_s0_MED, nil, sec1_s0_LO, DATA { 99, 99, 99, 99 } };
"""
    path = tmp_path / "track.3d"
    path.write_text(sample, encoding="utf-8")

    rows = parse_track3d_section_dlongs(path)

    assert len(rows) == 2
    assert rows[0].section == 0
    assert rows[0].sub_index == 0
    assert rows[0].dlongs == (0, 10, 20, 30)
    assert rows[1].section == 1
    assert rows[1].sub_index == 0
    assert rows[1].dlongs == (99, 99, 99, 99)


def test_parse_track3d_section_dlongs_skips_missing_or_invalid_data(tmp_path: Path):
    sample = """sec3_l1: LIST { sec3_s4_HI, sec3_s5_HI };
sec3_l2: LIST { sec3_s8_HI, DATA { 1, BAD, 2, , 3 } };
"""
    path = tmp_path / "track.3d"
    path.write_text(sample, encoding="utf-8")

    rows = parse_track3d_section_dlongs(path)

    assert len(rows) == 1
    assert rows[0].section == 3
    assert rows[0].sub_index == 2
    assert rows[0].dlongs == (1, 2, 3)


def test_parse_track3d_section_pointers_extracts_ranges_and_line_numbers(tmp_path: Path):
    sample = """3D VERSION 3.0;
% Outputing section from dlong = 708606 to dlong = 1062909.
sec0_s2_HI: FACE
  ([< -1441064, 4076686, 21036 >]),
% Outputing section from dlong = 0 to dlong = 708606.
sec0_s0_MED: FACE
% Outputting section from dlong = 1062909 to dlong = 1200000.
sec1_s4_LO: FACE
"""
    path = tmp_path / "track.3D"
    path.write_text(sample, encoding="utf-8")

    rows = parse_track3d_section_pointers(path)

    assert len(rows) == 3
    assert rows[0].pointer_name == "sec0_s2_HI"
    assert rows[0].section == 0
    assert rows[0].sub_index == 2
    assert rows[0].resolution == "HI"
    assert rows[0].dlong_start == 708606
    assert rows[0].dlong_end == 1062909
    assert rows[0].line_number == 3
    assert rows[1].pointer_name == "sec0_s0_MED"
    assert rows[1].resolution == "MED"
    assert rows[1].line_number == 6
    assert rows[2].pointer_name == "sec1_s4_LO"
    assert rows[2].resolution == "LO"
    assert rows[2].dlong_start == 1062909
    assert rows[2].dlong_end == 1200000
    assert rows[2].line_number == 8


def test_parse_track3d_section_dlongs_extracts_comment_backed_face_sections(tmp_path: Path):
    sample = """% Outputing section from dlong = 1417213 to dlong = 1705867.
sec1_s0_HI: FACE
  ([< -1059364, 3474879, 16602 >]),
  LIST { DetailList_1-0H }
;
% Outputing section from dlong = 1705867 to dlong = 1994522.
sec1_s1_HI: FACE
  ([< -900913, 3233596, 15439 >]),
  LIST { DetailList_1-1H }
;
% Outputing section from dlong = 1417213 to dlong = 1705867.
sec1_s0_HI: FACE
  ([< -1059364, 3474879, 16602 >]),
  LIST { DetailList_1-0H }
;
"""
    path = tmp_path / "track.3D"
    path.write_text(sample, encoding="utf-8")

    rows = parse_track3d_section_dlongs(path)

    assert len(rows) == 2
    assert rows[0].section == 1
    assert rows[0].sub_index == 0
    assert rows[0].dlongs == (1417213, 1705867)
    assert rows[0].line_number == 2
    assert rows[1].section == 1
    assert rows[1].sub_index == 1
    assert rows[1].dlongs == (1705867, 1994522)
    assert rows[1].line_number == 7
