from pathlib import Path

from sg_viewer.io.track3d_parser import (
    Track3DObjectList,
    parse_track3d,
    save_object_lists_to_track3d,
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
