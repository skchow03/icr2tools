from dataclasses import asdict
from pathlib import Path

from icr2_3d_catalog_viewer.icr2_3d_catalog_parser import parse_3d
from sg_viewer.io.track3d_catalog import (
    Track3DCatalog,
    Track3DDetailListDefinition,
    Track3DObjectListDefinition,
    parse_track3d_catalog,
)


def test_parse_track3d_catalog_returns_typed_catalog(tmp_path: Path):
    sample = """__TSO1: DYNAMIC 1, 2, 3, 4, EXTERN "tree";
ObjectList_L12_0: LIST { __TSO1, __TSO2 };
DetailList_12-0H: LIST { __TSO1, DetailO_263-0, DetailN_263-0 };
// Outputing section from dlong = 100 to dlong = 200
sec12_s0_HI: FACE
  ObjectList_L12_0
  DetailList_12-0H
  TOPO_sec12_s0_L_HI
  MIP = "road.mip"
sec12_l0: LIST { sec12_s0_HI, DATA { 100, 200 } };
index: LIST { sec12_l0 };
"""
    path = tmp_path / "track.3d"
    path.write_text(sample, encoding="utf-8")

    catalog = parse_track3d_catalog(path)

    assert isinstance(catalog, Track3DCatalog)
    assert catalog.counts == {
        "tsos": 1,
        "object_lists": 1,
        "detail_lists": 1,
        "faces": 1,
        "section_lists": 1,
        "index_entries": 1,
    }
    assert catalog.tsos["__TSO1"].extern == "tree"
    assert isinstance(catalog.object_lists["ObjectList_L12_0"], Track3DObjectListDefinition)
    assert catalog.object_lists["ObjectList_L12_0"].externs == ["tree", None]
    assert isinstance(catalog.detail_lists["DetailList_12-0H"], Track3DDetailListDefinition)
    assert catalog.detail_lists["DetailList_12-0H"].section == 12
    assert catalog.detail_lists["DetailList_12-0H"].subsection == 0
    assert catalog.detail_lists["DetailList_12-0H"].lod_suffix == "H"
    assert catalog.detail_lists["DetailList_12-0H"].items == ["__TSO1", "DetailO_263-0", "DetailN_263-0"]
    assert catalog.detail_lists["DetailList_12-0H"].externs == ["tree", None, None]
    assert catalog.faces[0].dlong_start == 100
    assert catalog.faces[0].dlong_end == 200
    assert catalog.faces[0].materials == ["road.mip"]
    assert catalog.section_summary[0].dlong_ranges == [(100, 200)]


def test_legacy_parser_returns_catalog_dictionary(tmp_path: Path):
    path = tmp_path / "track.3d"
    path.write_text('__TSO1: DYNAMIC 1, 2, 3, 4, EXTERN "tree";\n', encoding="utf-8")

    assert parse_3d(path) == asdict(parse_track3d_catalog(path))


def test_parse_track3d_catalog_records_source_spans_for_multiline_labels(tmp_path: Path):
    sample = """__TSO1: DYNAMIC 1, 2,
  3, 4, EXTERN "tree";
ObjectList_L12_0: LIST {
  __TSO1,
  __TSO2
};
DetailList_12-0H: LIST {
  __TSO1,
  DetailO_263-0,
  DetailN_263-0
};
// Outputing section from dlong = 100 to dlong = 200
sec12_s0_HI: FACE
  ObjectList_L12_0
  DetailList_12-0H
  TOPO_sec12_s0_L_HI
  MIP = "road.mip"
sec12_l0: LIST {
  sec12_s0_HI,
  DATA {
    100,
    200
  }
};
index: LIST {
  sec12_l0
};
trailing_label: LIST { should_not_be_consumed };
"""
    path = tmp_path / "track.3d"
    path.write_text(sample, encoding="utf-8")

    catalog = parse_track3d_catalog(path)

    tso_span = catalog.tsos["__TSO1"].span
    assert (tso_span.start_line, tso_span.end_line) == (1, 2)
    assert tso_span.text == '__TSO1: DYNAMIC 1, 2,\n  3, 4, EXTERN "tree";'

    object_span = catalog.object_lists["ObjectList_L12_0"].span
    assert (object_span.start_line, object_span.end_line) == (3, 6)
    assert object_span.text.endswith("\n};")
    assert "sec12_s0_HI" not in object_span.text

    detail_span = catalog.detail_lists["DetailList_12-0H"].span
    assert (detail_span.start_line, detail_span.end_line) == (7, 11)
    assert detail_span.text.endswith("\n};")
    assert "sec12_s0_HI" not in detail_span.text

    face_span = catalog.faces[0].span
    assert (face_span.start_line, face_span.end_line) == (13, 17)
    assert 'MIP = "road.mip"' in face_span.text
    assert "sec12_l0:" not in face_span.text

    section_span = catalog.section_lists["sec12_l0"].span
    assert (section_span.start_line, section_span.end_line) == (18, 24)
    assert "DATA" in section_span.text
    assert "index:" not in section_span.text

    assert catalog.index_span is not None
    assert (catalog.index_span.start_line, catalog.index_span.end_line) == (25, 27)
    assert "sec12_l0" in catalog.index_span.text
    assert "trailing_label:" not in catalog.index_span.text
