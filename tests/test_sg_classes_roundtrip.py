import pytest

np = pytest.importorskip("numpy")

from icr2_core.trk.sg_classes import SGFile


def _make_section(num_xsects: int) -> SGFile.Section:
    data = [0] * (58 + 2 * num_xsects)
    data[0] = 1
    data[1] = 0
    data[2] = 0
    data[3] = 100
    data[4] = 200
    data[5] = 300
    data[6] = 400
    data[7] = 0
    data[8] = 1234
    data[17 + 2 * num_xsects] = 0
    section = SGFile.Section(data, num_xsects)
    section.alt = [10 for _ in range(num_xsects)]
    section.grade = [0 for _ in range(num_xsects)]
    return section


def test_output_sg_rewrites_header_counts_from_data(tmp_path):
    # Intentionally stale/inconsistent counts in header and SGFile fields.
    header = [0x53470000, 1, 1, 0, 99, 99]
    xsect_dlats = np.array([0], dtype=np.int32)
    sgfile = SGFile(header=header, num_sects=99, num_xsects=99, xsect_dlats=xsect_dlats, sects=[_make_section(1)])

    out_path = tmp_path / "roundtrip.sg"
    sgfile.output_sg(str(out_path))

    loaded = SGFile.from_sg(str(out_path))

    assert loaded.num_sects == 1
    assert loaded.num_xsects == 1
    assert list(loaded.header[:6]) == [0x53470000, 1, 1, 0, 1, 1]
    assert loaded.sects[0].length == 1234
