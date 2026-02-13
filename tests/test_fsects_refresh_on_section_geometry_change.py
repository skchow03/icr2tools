from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")

from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.preview.runtime_ops_editing.edit_preview_ops import _RuntimeEditPreviewOpsMixin


def _section(section_id: int, *, start_x: float) -> SectionPreview:
    return SectionPreview(
        section_id=section_id,
        source_section_id=section_id,
        type_name="straight",
        previous_id=section_id - 1 if section_id > 0 else None,
        next_id=section_id + 1 if section_id < 1 else None,
        start=(start_x, 0.0),
        end=(start_x + 1.0, 0.0),
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
        polyline=[(start_x, 0.0), (start_x + 1.0, 0.0)],
    )


class _DummySectionManager:
    def __init__(self, sections: list[SectionPreview]) -> None:
        self.sections = list(sections)
        self.sampled_centerline = [
            point for section in sections for point in section.polyline
        ]
        self.sampled_bounds = (0.0, 0.0, 2.0, 0.0)
        self.sampled_dlongs = [0.0, 1.0, 2.0]
        self.centerline_index = object()

    def set_sections(self, sections, *, changed_indices=None):
        _ = changed_indices
        self.sections = list(sections)
        self.sampled_centerline = [
            point for section in self.sections for point in section.polyline
        ]
        return True


class _DummySelection:
    def update_context(self, *_args, **_kwargs) -> None:
        return


class _DummyRuntime(_RuntimeEditPreviewOpsMixin):
    def __init__(self, sections: list[SectionPreview]) -> None:
        self._section_manager = _DummySectionManager(sections)
        self._selection = _DummySelection()
        self._fsects_by_section = [[] for _ in sections]
        self._sampled_bounds = None
        self._sampled_centerline = []
        self._track_length = 2.0
        self._start_finish_mapping = None
        self._start_finish_dlong = None
        self._context = SimpleNamespace(request_repaint=lambda: None)
        self._has_unsaved_changes = False
        self._emit_sections_changed = None
        self._sgfile = object()
        self._refresh_calls = 0

    def _clear_split_hover(self) -> None:
        return

    def _normalize_section_dlongs(self, sections):
        return sections

    def _current_start_finish_dlong(self):
        return None

    def _realign_fsects_after_recalc(self, _old_sections, _old_fsects) -> None:
        return

    def _update_start_finish_mapping(self, _start_dlong) -> None:
        return

    def _update_fit_scale(self) -> None:
        return

    def _update_node_status(self) -> None:
        return

    def _ensure_default_elevations(self, _sections) -> None:
        return

    def _bump_sg_version(self) -> None:
        return

    def refresh_fsections_preview_lightweight(self) -> bool:
        self._refresh_calls += 1
        return True


def test_set_sections_refreshes_fsects_when_centerline_changes() -> None:
    runtime = _DummyRuntime([_section(0, start_x=0.0), _section(1, start_x=1.0)])

    updated = [_section(0, start_x=0.5), _section(1, start_x=1.5)]
    runtime.set_sections(updated)

    assert runtime._refresh_calls == 1


def test_set_sections_refreshes_fsects_when_section_count_changes() -> None:
    runtime = _DummyRuntime([_section(0, start_x=0.0), _section(1, start_x=1.0)])

    runtime.set_sections([_section(0, start_x=0.0)])

    assert runtime._refresh_calls == 1


def test_set_sections_skips_refresh_when_centerline_unchanged() -> None:
    runtime = _DummyRuntime([_section(0, start_x=0.0), _section(1, start_x=1.0)])

    runtime.set_sections([_section(0, start_x=0.0), _section(1, start_x=1.0)])

    assert runtime._refresh_calls == 0

