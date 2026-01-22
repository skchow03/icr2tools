from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sg_viewer.geometry.derived_geometry import DerivedGeometry


class _Signal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, func) -> None:
        self._callbacks.append(func)

    def emit(self) -> None:
        for func in list(self._callbacks):
            func()


@dataclass
class _Document:
    sg_data: object
    geometry_changed: _Signal


class _GeometryHarness:
    def __init__(self) -> None:
        self._sg_data = SimpleNamespace(sects=_build_test_sections())
        self._document = _Document(sg_data=self._sg_data, geometry_changed=_Signal())
        self._geometry = DerivedGeometry(self._document)
        self._geometry.rebuild_if_needed()

    @property
    def sections(self):
        return self._geometry.sections

    def insert_section(self, index: int, section: object) -> None:
        self._sg_data.sects.insert(index, section)
        _relink_sections(self._sg_data.sects)
        self._document.geometry_changed.emit()

    def rebuild_if_needed(self) -> None:
        self._geometry.rebuild_if_needed()


def _build_test_sections() -> list[object]:
    sections = [
        _make_test_section(0.0, 0.0, 100.0, 0.0, start_dlong=0.0, length=100.0),
        _make_test_section(100.0, 0.0, 200.0, 0.0, start_dlong=100.0, length=100.0),
    ]
    _relink_sections(sections)
    return sections


def _relink_sections(sections: list[object]) -> None:
    for idx, sect in enumerate(sections):
        sect.sec_prev = idx - 1 if idx > 0 else -1
        sect.sec_next = idx + 1 if idx < len(sections) - 1 else -1


def _make_test_section(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    *,
    start_dlong: float,
    length: float,
) -> object:
    return SimpleNamespace(
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        start_dlong=start_dlong,
        length=length,
        type=1,
        center_x=0.0,
        center_y=0.0,
        radius=0.0,
        sang1=0.0,
        sang2=0.0,
        eang1=0.0,
        eang2=0.0,
        sec_prev=-1,
        sec_next=-1,
    )


def build_test_geometry() -> _GeometryHarness:
    return _GeometryHarness()


def make_test_section() -> object:
    return _make_test_section(
        50.0,
        0.0,
        150.0,
        0.0,
        start_dlong=50.0,
        length=100.0,
    )


def test_section_id_matches_index_after_insert():
    geom = build_test_geometry()
    geom.insert_section(1, make_test_section())
    geom.rebuild_if_needed()

    for i, sect in enumerate(geom.sections):
        assert sect.section_id == i
