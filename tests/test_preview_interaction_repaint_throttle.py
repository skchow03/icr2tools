from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

from sg_viewer.preview.runtime_ops.op_preview import _RuntimeCorePreviewMixin


class _DummyRuntime(_RuntimeCorePreviewMixin):
    def __init__(self, *, show_tsd_lines: bool, has_overlay: bool) -> None:
        self._show_tsd_lines = show_tsd_lines
        self._trk_overlay = SimpleNamespace(has_overlay=lambda: has_overlay)
        self.repaint_calls = 0
        self.throttled_repaint_calls = 0
        self._context = SimpleNamespace(
            request_repaint=self._request_repaint,
            request_repaint_throttled=self._request_repaint_throttled,
        )

    def _request_repaint(self) -> None:
        self.repaint_calls += 1

    def _request_repaint_throttled(self, *, min_interval_ms: int = 33) -> None:
        _ = min_interval_ms
        self.throttled_repaint_calls += 1


def test_interaction_repaint_throttled_when_tsd_overlay_is_visible() -> None:
    runtime = _DummyRuntime(show_tsd_lines=True, has_overlay=True)

    runtime._request_interaction_repaint()

    assert runtime.throttled_repaint_calls == 1
    assert runtime.repaint_calls == 0


def test_interaction_repaint_immediate_without_tsd_overlay() -> None:
    runtime = _DummyRuntime(show_tsd_lines=False, has_overlay=True)

    runtime._request_interaction_repaint()

    assert runtime.repaint_calls == 1
    assert runtime.throttled_repaint_calls == 0


def test_interaction_repaint_immediate_without_trk_overlay() -> None:
    runtime = _DummyRuntime(show_tsd_lines=True, has_overlay=False)

    runtime._request_interaction_repaint()

    assert runtime.repaint_calls == 1
    assert runtime.throttled_repaint_calls == 0
