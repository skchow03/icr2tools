import math
import re
from types import SimpleNamespace

from icr2_core.trk.trk3d_builder import (
    MATERIALS,
    Track3DOptions,
    build_track3d_text,
    material_for_ground_type,
)


def _square_track():
    starts = ((0, 0), (100_000, 0), (100_000, 100_000), (0, 100_000))
    headings = (0, 2**30, -(2**31), -(2**30))
    sections = []
    for index, ((x, y), heading) in enumerate(zip(starts, headings)):
        angle = heading / 2**31 * math.pi + math.pi / 2
        offsets = (-6_000, 6_000)
        sections.append(
            SimpleNamespace(
                type=1,
                start_dlong=index * 100_000,
                length=100_000,
                heading=heading,
                ang1=0,
                ang2=0,
                pos1=[round(x + d * math.cos(angle)) for d in offsets],
                pos2=[round(y + d * math.sin(angle)) for d in offsets],
                ground_fsects=1,
                num_bounds=1,
                bound_dlat_start=[6_000],
                bound_dlat_end=[6_000],
                ground_dlat_start=[-6_000],
                ground_dlat_end=[-6_000],
                ground_type=[46],
            )
        )
    return SimpleNamespace(
        num_sects=4,
        num_xsects=2,
        trklength=400_000,
        xsect_dlats=[-6_000, 6_000],
        xsect_data=[[0] * 8 for _ in range(8)],
        sects=sections,
    )


def test_ground_type_families_match_stock_materials():
    assert [material_for_ground_type(i * 8).name for i in range(7)] == [
        material.name for material in MATERIALS
    ]
    assert material_for_ground_type(46).name == "Asphalt"
    assert material_for_ground_type(54).name == "Paint"


def test_builds_complete_track3d_surface_and_lod_index():
    text = build_track3d_text(_square_track(), track_name="square")

    assert text.startswith("3D VERSION 3.0;\n")
    assert "% Track square" in text
    assert "sec0_s0_HI: FACE" in text
    assert "sec3_s0_LO: FACE" in text
    assert 'MATERIAL GROUP = 2, MIP = "ASPHALT"' in text
    assert "sec0_l0: LIST { sec0_s0_HI, nil, nil, nil, sec0_s0_MED" in text
    assert "DATA { 0, 0, 0, 0 }" in text
    assert "hash: DATA { 0, 2 };" in text
    assert "index: LIST { hash, sec0_l0, sec1_l0, sec2_l0, sec3_l0 };" in text

    texture_coordinates = [
        tuple(map(int, match))
        for match in re.findall(r"t= <(-?\d+), (-?\d+)>", text)
    ]
    assert texture_coordinates
    assert all(u >= 0 and v >= 0 for u, v in texture_coordinates)
    assert all(v <= 1_024 for _u, v in texture_coordinates)


def test_segment_layout_has_required_eight_entries():
    text = build_track3d_text(_square_track(), track_name="square")
    match = re.search(r"sec0_l0: LIST \{(.*?)\};", text)
    assert match is not None
    body = match.group(1)
    data = re.search(r"DATA \{([^}]*)\}", body)
    assert data is not None
    pointers = [
        item.strip()
        for item in re.sub(r"DATA \{.*?\}", "DATA", body).split(",")
    ]

    assert len(pointers) == 8
    assert pointers[-1] == "DATA"
    assert len([value for value in data.group(1).split(",") if value.strip()]) == 4


def test_faces_include_segment_tso_bspa_scaffold():
    text = build_track3d_text(_square_track(), track_name="square")

    # Four sections times three LODs, with two nested BSPA nodes per FACE.
    assert text.count(": FACE ") == 12
    assert text.count("  BSPA (") == 24
    assert text.count("TOPO_sec0_s0_L_HI: NIL;") == 1
    assert text.count("TSO_sec0_s0_L: NIL;") == 1
    assert "LIST { TOPO_sec0_s0_L_HI, TSO_sec0_s0_L }," in text
    assert "LIST { TOPO_sec0_s0_R_HI, TSO_sec0_s0_R }," in text

    face = text.split("sec0_s0_HI: FACE", 1)[1].split("};", 1)[0]
    assert face.index("BSPA") < face.index('MATERIAL GROUP = 2, MIP = "ASPHALT"')


def test_texture_axes_match_trk23d_orientation():
    text = build_track3d_text(_square_track(), track_name="square")
    first_poly = text.split("POLY [T]", 1)[1].split("},", 1)[0]
    coordinates = [
        tuple(map(int, match))
        for match in re.findall(r"t= <(-?\d+), (-?\d+)>", first_poly)
    ]

    # The first two points run longitudinally: U stays on the same lateral
    # edge while V changes. The second and third points cross the track: V is
    # constant while U changes.
    assert coordinates[0][0] == coordinates[1][0]
    assert coordinates[0][1] != coordinates[1][1]
    assert coordinates[1][1] == coordinates[2][1]
    assert coordinates[1][0] != coordinates[2][0]


def test_options_reject_nonpositive_mesh_lengths():
    try:
        Track3DOptions(high_segment_length=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")
