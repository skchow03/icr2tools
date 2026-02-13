from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from types import SimpleNamespace

from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.preview.runtime_ops_editing.edit_preview_ops import _RuntimeEditPreviewOpsMixin


def _section(section_id: int, source_section_id: int) -> SectionPreview:
    return SectionPreview(
        section_id=section_id,
        source_section_id=source_section_id,
        type_name="straight",
        previous_id=(section_id - 1) % 2,
        next_id=(section_id + 1) % 2,
        start=(float(section_id), 0.0),
        end=(float(section_id + 1), 0.0),
        start_dlong=float(section_id),
        length=1.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=(1.0, 0.0),
        end_heading=(1.0, 0.0),
        polyline=[(float(section_id), 0.0), (float(section_id + 1), 0.0)],
    )


class _DummySectionManager:
    def __init__(self, sections: list[SectionPreview]) -> None:
        self.sections = list(sections)
        self.sampled_bounds = (0.0, 0.0, 2.0, 0.0)
        self.sampled_centerline = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
        self.sampled_dlongs = [0.0, 1.0, 2.0]
        self.centerline_index = object()

    def load_sections(self, **kwargs) -> None:
        self.sections = list(kwargs["sections"])
        self.sampled_centerline = list(kwargs["sampled_centerline"])
        self.sampled_dlongs = list(kwargs["sampled_dlongs"])
        self.sampled_bounds = kwargs["sampled_bounds"]
        self.centerline_index = kwargs["centerline_index"]


class _DummySelection:
    def blockSignals(self, _blocked: bool) -> bool:  # noqa: N802
        return False

    def reset(self, *_args, **_kwargs) -> None:
        return

    def set_selected_section(self, *_args, **_kwargs) -> None:
        return


class _DummyRuntime(_RuntimeEditPreviewOpsMixin):
    def __init__(self, sections: list[SectionPreview]) -> None:
        self._section_manager = _DummySectionManager(sections)
        self._fsects_by_section = [["fsect-a"], ["fsect-b"]]
        self._sampled_bounds = None
        self._sampled_centerline = []
        self._track_length = 0.0
        self._start_finish_mapping = None
        self._start_finish_dlong = None
        self._selection = _DummySelection()
        self._context = SimpleNamespace(request_repaint=lambda: None)
        self._has_unsaved_changes = False
        self._emit_sections_changed = None

    def _realign_fsects_after_recalc(self, old_sections, old_fsects) -> None:
        old_by_source = {
            section.source_section_id: fsects
            for section, fsects in zip(old_sections, old_fsects)
        }
        self._fsects_by_section = [
            old_by_source.get(section.source_section_id, [])
            for section in self._section_manager.sections
        ]

    def _update_node_status(self) -> None:
        return

    def _update_start_finish_mapping(self, _start_dlong) -> None:
        return


def test_rebuild_after_start_finish_realigns_fsects(monkeypatch) -> None:
    old_sections = [_section(0, 10), _section(1, 20)]
    runtime = _DummyRuntime(old_sections)

    reordered_sections = [_section(0, 20), _section(1, 10)]

    monkeypatch.setattr(
        "sg_viewer.preview.runtime_ops_editing.edit_preview_ops.rebuild_centerline_from_sections",
        lambda _sections: (
            [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)],
            [0.0, 1.0, 2.0],
            (0.0, 0.0, 2.0, 0.0),
            object(),
        ),
    )

    runtime.rebuild_after_start_finish(reordered_sections)

    assert runtime._fsects_by_section == [["fsect-b"], ["fsect-a"]]
