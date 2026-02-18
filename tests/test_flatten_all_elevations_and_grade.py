from __future__ import annotations

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.model.sg_document import SGDocument



def _make_sgfile(num_sections: int, num_xsects: int = 3) -> SGFile:
    sections = []
    record_length = 58 + 2 * num_xsects
    for idx in range(num_sections):
        data = [0] * record_length
        data[0] = 1
        data[1] = -1
        data[2] = -1
        data[7] = idx * 100
        data[8] = 100
        sections.append(SGFile.Section(data, num_xsects))

    for idx, section in enumerate(sections):
        section.alt = [100 * (idx + 1) + x for x in range(num_xsects)]
        section.grade = [10 * (idx + 1) + x for x in range(num_xsects)]

    header = [0, 0, 0, 0, num_sections, num_xsects]
    xsect_dlats = [0 for _ in range(num_xsects)]
    return SGFile(header, num_sections, num_xsects, xsect_dlats, sections)


def test_flatten_all_elevations_and_grade() -> None:
    sg_document = SGDocument(_make_sgfile(2, 3))

    sg_document.flatten_all_elevations_and_grade(321, grade=0)

    for section in sg_document.sg_data.sects:
        assert list(section.alt) == [321, 321, 321]
        assert list(section.grade) == [0, 0, 0]


def test_flatten_emits_single_bulk_signal() -> None:
    sg_document = SGDocument(_make_sgfile(5, 3))
    emitted: list[None] = []
    per_section: list[int] = []

    sg_document.elevations_bulk_changed.connect(lambda: emitted.append(None))
    sg_document.elevation_changed.connect(lambda section_id: per_section.append(section_id))

    sg_document.flatten_all_elevations_and_grade(111, grade=7)

    assert emitted == [None]
    assert per_section == []


def test_suspended_drag_updates_emit_one_bulk_signal_on_commit() -> None:
    sg_document = SGDocument(_make_sgfile(4, 2))
    emitted: list[None] = []
    per_section: list[int] = []

    sg_document.elevations_bulk_changed.connect(lambda: emitted.append(None))
    sg_document.elevation_changed.connect(lambda section_id: per_section.append(section_id))

    sg_document.set_elevation_signals_suspended(True)
    sg_document.set_section_xsect_altitude(0, 0, 1000, validate=False)
    sg_document.set_section_xsect_altitude(1, 0, 1200, validate=False)

    assert emitted == []
    assert per_section == []

    sg_document.set_elevation_signals_suspended(False)

    assert emitted == [None]
    assert per_section == []


def test_set_xsect_definitions_remaps_altitudes_and_emits_bulk_signal() -> None:
    sg_document = SGDocument(_make_sgfile(2, 3))
    emitted: list[None] = []
    per_section: list[int] = []

    sg_document.elevations_bulk_changed.connect(lambda: emitted.append(None))
    sg_document.elevation_changed.connect(lambda section_id: per_section.append(section_id))

    sg_document.set_xsect_definitions([(2, -250.2), (None, 0.0), (0, 250.8)])

    assert list(sg_document.sg_data.xsect_dlats) == [-250, 0, 251]
    assert sg_document.sg_data.num_xsects == 3
    assert sg_document.sg_data.header[5] == 3
    assert list(sg_document.sg_data.sects[0].alt) == [102, 0, 100]
    assert list(sg_document.sg_data.sects[0].grade) == [12, 0, 10]
    assert list(sg_document.sg_data.sects[1].alt) == [202, 0, 200]
    assert list(sg_document.sg_data.sects[1].grade) == [22, 0, 20]
    assert emitted == [None]
    assert per_section == []


def test_set_xsect_definitions_preserves_array_dtype_when_available() -> None:
    np = __import__("numpy")
    sgfile = _make_sgfile(1, 3)
    sgfile.xsect_dlats = np.array([0, 100, 200], dtype=np.int16)
    sg_document = SGDocument(sgfile)

    sg_document.set_xsect_definitions([(0, -10), (1, 10)])

    assert isinstance(sg_document.sg_data.xsect_dlats, np.ndarray)
    assert sg_document.sg_data.xsect_dlats.dtype == np.int16
    assert sg_document.sg_data.xsect_dlats.tolist() == [-10, 10]
