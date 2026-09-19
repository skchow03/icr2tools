import math
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
    assert "sec0_l0: LIST { sec0_s0_HI, nil, sec0_s0_MED" in text
    assert "DATA { 0, 100000 }" in text
    assert "hash: DATA { 0, 0, 262144, 2, 400000, 3 };" in text
    assert "index: LIST { hash, sec0_l0, sec1_l0, sec2_l0, sec3_l0 };" in text


def test_options_reject_nonpositive_mesh_lengths():
    try:
        Track3DOptions(high_segment_length=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")
