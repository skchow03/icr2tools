from sg_viewer.services.track3d_topo_tso_calls import (
    SectionTopoTsoCalls,
    parse_topo_tso_calls,
    update_topo_tso_calls,
)


def test_topo_tso_calls_parse_and_update(tmp_path):
    path = tmp_path / "track.3d"
    path.write_text(
        "sec0_s2_HI: LIST {\n"
        "% Output left side TSOs\n"
        "LIST { TOPO_sec0_s2_L_LO, ObjectList_L0_2 }\n"
        "% Output right side TSOs\n"
        "LIST { TOPO_sec0_s2_R_LO, ObjectList_R0_2 }\n"
        "};\n"
        "sec1_s0_MED: LIST {\n"
        "% Output left side TSOs\nLIST { A }\n"
        "% Output right side TSOs\nLIST { B }\n};\n",
        encoding="utf-8",
    )

    parsed = parse_topo_tso_calls(path)
    assert parsed[0].section == "sec0_s2_HI"
    assert parsed[0].right == ["TOPO_sec0_s2_R_LO", "ObjectList_R0_2"]

    count = update_topo_tso_calls(
        path,
        [SectionTopoTsoCalls("sec0_s2_HI", ["free form", "FIRST"], ["ONLY"])],
    )
    assert count == 2
    reparsed = parse_topo_tso_calls(path)
    assert reparsed[0].left == ["free form", "FIRST"]
    assert reparsed[0].right == ["ONLY"]
    assert reparsed[1].left == ["A"]
