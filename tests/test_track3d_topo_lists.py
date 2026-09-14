from pathlib import Path

from sg_viewer.io.track3d_parser import (
    Track3DTopoList,
    parse_track3d_topo_lists,
    save_topo_lists_to_track3d,
)


def test_parse_topo_lists_includes_nil_and_list_rows(tmp_path: Path) -> None:
    track3d = tmp_path / "track.3D"
    track3d.write_text(
        "TOPO_sec0_s0_L_HI: NIL;\n"
        "TOPO_sec0_s0_R_HI: LIST { __TSO4, __TSO9 };\n"
        "TOPO_sec12_s3_L_MED: NIL;\n",
        encoding="utf-8",
    )

    assert parse_track3d_topo_lists(track3d) == [
        Track3DTopoList(0, 0, "L", "HI", []),
        Track3DTopoList(0, 0, "R", "HI", [4, 9]),
        Track3DTopoList(12, 3, "L", "MED", []),
    ]


def test_save_topo_lists_converts_nil_to_list_and_empty_list_to_nil(
    tmp_path: Path,
) -> None:
    track3d = tmp_path / "track.3D"
    track3d.write_text(
        "TOPO_sec0_s0_L_HI: NIL;\n"
        "TOPO_sec0_s0_R_HI: LIST { __TSO4 };\n"
        "unrelated: NIL;\n",
        encoding="utf-8",
    )

    backup = save_topo_lists_to_track3d(
        track3d,
        [
            Track3DTopoList(0, 0, "L", "HI", [2, 7]),
            Track3DTopoList(0, 0, "R", "HI", []),
        ],
        create_backup=False,
    )

    assert backup is None
    assert track3d.read_text(encoding="utf-8") == (
        "TOPO_sec0_s0_L_HI: LIST { __TSO2, __TSO7 };\n"
        "TOPO_sec0_s0_R_HI: NIL;\n"
        "unrelated: NIL;\n"
    )


def test_save_topo_lists_writes_manual_list_entry_unchanged(tmp_path: Path) -> None:
    track3d = tmp_path / "track.3D"
    track3d.write_text("TOPO_sec34_s1_L_HI: NIL;\n", encoding="utf-8")

    save_topo_lists_to_track3d(
        track3d,
        [Track3DTopoList(34, 1, "L", "HI", ["sec34_s1_HI"])],
        create_backup=False,
    )

    assert track3d.read_text(encoding="utf-8") == (
        "TOPO_sec34_s1_L_HI: LIST { sec34_s1_HI };\n"
    )
    assert parse_track3d_topo_lists(track3d) == [
        Track3DTopoList(34, 1, "L", "HI", ["sec34_s1_HI"])
    ]
