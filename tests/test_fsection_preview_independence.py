from __future__ import annotations

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.runtime_ops.fsection_edit_session import FSectionEditSession


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


def _get_fsects(section: SGFile.Section) -> list[tuple[int, int]]:
    return list(
        zip(
            list(getattr(section, "fstart", [])),
            list(getattr(section, "fend", [])),
        )
    )


def test_preview_edit_session_independence() -> None:
    sg_document = SGDocument(_make_sgfile(1))
    sg_document.replace_fsections(
        0, [{"start_dlat": 0.0, "end_dlat": 10.0, "surface_type": 1, "type2": 0}]
    )

    session = FSectionEditSession(sg_document, 0)
    session.begin()
    session.update_preview(0, end_dlat=25.0)

    assert _get_fsects(sg_document.sg_data.sects[0]) == [(0, 10)]

    session.cancel()
    assert session.preview_fsections == session.original_fsections

    session.update_preview(0, end_dlat=30.0)
    session.commit()

    assert _get_fsects(sg_document.sg_data.sects[0]) == [(0, 30)]
