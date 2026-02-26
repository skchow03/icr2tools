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

    def _sync_samples(self) -> None:
        self.sampled_centerline = [
            point for section in self.sections for point in section.polyline
        ]

    def set_sections(self, sections, *, changed_indices=None):
        _ = changed_indices
        self.sections = list(sections)
        self._sync_samples()
        return True

    def update_drag_preview(self, sections):
        self.sections = list(sections)
        self._sync_samples()
        return True


class _DummySelection:
    def update_context(self, *_args, **_kwargs) -> None:
        return


class _DummyRuntime(_RuntimeEditPreviewOpsMixin):
    def __init__(self, sections: list[SectionPreview], *, show_tsd_lines: bool = False) -> None:
        self._section_manager = _DummySectionManager(sections)
        self._selection = _DummySelection()
        self._fsects_by_section = [[] for _ in sections]
        self._sampled_bounds = None
        self._sampled_centerline = []
        self._track_length = 2.0
        self._start_finish_mapping = None
        self._start_finish_dlong = None
        self._repaint_calls = 0
        self._throttled_repaint_calls = 0
        self._context = SimpleNamespace(
            request_repaint=self._count_repaint,
            request_repaint_throttled=self._count_throttled_repaint,
        )
        self._has_unsaved_changes = False
        self._emit_sections_changed = None
        self._sgfile = object()
        self._refresh_calls = 0
        self._show_tsd_lines = show_tsd_lines
        self._trk_overlay = SimpleNamespace(has_overlay=lambda: show_tsd_lines)


    def _count_repaint(self) -> None:
        self._repaint_calls += 1

    def _count_throttled_repaint(self, *, min_interval_ms: int = 33) -> None:
        _ = min_interval_ms
        self._throttled_repaint_calls += 1

    def _should_throttle_interaction_repaint(self) -> bool:
        return bool(self._show_tsd_lines and self._trk_overlay.has_overlay())

    def _request_interaction_repaint(self, min_interval_ms: int = 33) -> None:
        if self._should_throttle_interaction_repaint():
            self._context.request_repaint_throttled(min_interval_ms=min_interval_ms)
            return
        self._context.request_repaint()

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



def test_update_drag_preview_uses_throttled_repaint_for_tsd_overlay() -> None:
    runtime = _DummyRuntime([_section(0, start_x=0.0), _section(1, start_x=1.0)], show_tsd_lines=True)

    runtime.update_drag_preview([_section(0, start_x=0.3), _section(1, start_x=1.3)])

    assert runtime._throttled_repaint_calls == 1
    assert runtime._repaint_calls == 0


def test_update_drag_preview_uses_immediate_repaint_without_tsd_overlay() -> None:
    runtime = _DummyRuntime([_section(0, start_x=0.0), _section(1, start_x=1.0)], show_tsd_lines=False)

    runtime.update_drag_preview([_section(0, start_x=0.3), _section(1, start_x=1.3)])

    assert runtime._repaint_calls == 1
    assert runtime._throttled_repaint_calls == 0
