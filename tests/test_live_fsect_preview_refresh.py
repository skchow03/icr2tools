from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.preview.runtime_ops_persistence import _RuntimePersistenceMixin


def _make_sgfile() -> SGFile:
    num_xsects = 1
    record_length = 58 + 2 * num_xsects
    data = [0] * record_length
    data[0] = 1
    data[1] = -1
    data[2] = -1
    data[7] = 0
    data[8] = 100
    fsect_start = 17 + 2 * num_xsects
    data[fsect_start] = 0
    section = SGFile.Section(data, num_xsects)
    section.num_fsects = 1
    section.ftype1 = [1]
    section.ftype2 = [0]
    section.fstart = [0]
    section.fend = [10]
    header = [0, 0, 0, 0, 1, num_xsects]
    return SGFile(header, 1, num_xsects, [0], [section])


class _DummyRuntime(_RuntimePersistenceMixin):
    def __init__(self) -> None:
        self._sgfile = _make_sgfile()
        self._preview_data = SimpleNamespace(fsections=[])
        self._fsects_by_section = [
            [
                PreviewFSection(
                    start_dlat=5.0,
                    end_dlat=15.0,
                    surface_type=2,
                    type2=1,
                )
            ]
        ]
        self._context = SimpleNamespace(request_repaint=lambda: None)
        self._sg_preview_model = None

    def apply_preview_to_sgfile(self) -> SGFile:
        section = self._sgfile.sects[0]
        preview = self._fsects_by_section[0][0]
        section.fstart = [int(round(preview.start_dlat))]
        section.fend = [int(round(preview.end_dlat))]
        section.ftype1 = [int(preview.surface_type)]
        section.ftype2 = [int(preview.type2)]
        section.num_fsects = 1
        return self._sgfile


def test_lightweight_refresh_updates_overlay_model(monkeypatch) -> None:
    runtime = _DummyRuntime()
    captured: dict[str, int] = {}

    def _fake_build_sg_preview_model(sg_document) -> object:
        section = sg_document.sg_data.sects[0]
        captured["fstart"] = int(section.fstart[0])
        captured["fend"] = int(section.fend[0])
        captured["ftype1"] = int(section.ftype1[0])
        return object()

    monkeypatch.setattr(
        "sg_viewer.preview.runtime_ops_persistence.build_sg_preview_model",
        _fake_build_sg_preview_model,
    )

    assert runtime.refresh_fsections_preview_lightweight() is True

    assert captured == {"fstart": 5, "fend": 15, "ftype1": 2}
    assert runtime._sg_preview_model is not None
    assert runtime._preview_data.fsections == runtime._fsects_by_section[0]
