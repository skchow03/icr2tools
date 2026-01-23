from __future__ import annotations

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.model.sg_document import SGDocument


def _make_sgfile(num_sections: int, num_xsects: int = 1) -> SGFile:
    sections = []
    record_length = 58 + 2 * num_xsects
    for idx in range(num_sections):
        data = [0] * record_length
        data[0] = 1
        data[1] = -1
        data[2] = -1
        data[7] = idx * 100
        data[8] = 100
        fsect_start = 17 + 2 * num_xsects
        data[fsect_start] = 0
        sections.append(SGFile.Section(data, num_xsects))
    header = [0, 0, 0, 0, num_sections, num_xsects]
    xsect_dlats = [0 for _ in range(num_xsects)]
    return SGFile(header, num_sections, num_xsects, xsect_dlats, sections)


def test_section_isolation_for_fsections() -> None:
    sg_document = SGDocument(_make_sgfile(2))

    section_b = sg_document.sg_data.sects[1]
    section_b.num_fsects = 2
    section_b.ftype1 = [1, 1]
    section_b.ftype2 = [0, 0]
    section_b.fstart = [50, 0]
    section_b.fend = [60, 10]

    original_b = (list(section_b.fstart), list(section_b.fend))

    sg_document.add_fsection(
        0, 0, {"start_dlat": 12.0, "end_dlat": 2.0, "surface_type": 1, "type2": 0}
    )

    section_a = sg_document.sg_data.sects[0]
    assert list(section_a.fstart) == [2]
    assert list(section_a.fend) == [12]
    assert (list(section_b.fstart), list(section_b.fend)) == original_b
