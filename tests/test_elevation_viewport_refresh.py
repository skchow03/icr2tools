from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

from sg_viewer.preview.runtime_ops.op_preview import _RuntimeCoreMixin
from sg_viewer.ui.viewer_controller import SGViewerController


class _Preview:
    def __init__(self) -> None:
        self.refresh_calls: list[bool] = []

    def refresh_after_elevation_change(self, *, throttled: bool = False) -> None:
        self.refresh_calls.append(throttled)


class _Window:
    def __init__(self) -> None:
        self.preview = _Preview()
        self.adjusted_cache_invalidations = 0

    def invalidate_adjusted_section_range_cache(self) -> None:
        self.adjusted_cache_invalidations += 1


def _controller_with_window(window: _Window) -> SGViewerController:
    controller = SGViewerController.__new__(SGViewerController)
    controller._window = window
    controller._last_tsd_adjusted_to_sg_ranges = ([1], [2])
    controller._refresh_elevation_profile = lambda: None
    controller._refresh_xsect_elevation_panel = lambda: None
    controller._refresh_xsect_elevation_table = lambda: None
    controller._elevation_panel_controller = SimpleNamespace(
        refresh_elevation_profile=lambda *, refresh_table: None
    )
    return controller


def test_full_xsect_value_sync_refreshes_elevation_viewport() -> None:
    window = _Window()
    controller = _controller_with_window(window)

    controller._sync_after_xsect_value_change()

    assert window.adjusted_cache_invalidations == 1
    assert controller._last_tsd_adjusted_to_sg_ranges == ([], [])
    assert window.preview.refresh_calls == [False]


def test_lightweight_xsect_value_sync_refreshes_elevation_viewport_throttled() -> None:
    window = _Window()
    controller = _controller_with_window(window)

    controller._sync_after_xsect_value_change_lightweight()

    assert window.adjusted_cache_invalidations == 1
    assert controller._last_tsd_adjusted_to_sg_ranges == ([], [])
    assert window.preview.refresh_calls == [True]


def test_runtime_refresh_after_elevation_change_invalidates_gradient_cache_and_repaints() -> None:
    repaint_calls = 0

    def request_repaint() -> None:
        nonlocal repaint_calls
        repaint_calls += 1

    runtime = _RuntimeCoreMixin.__new__(_RuntimeCoreMixin)
    runtime._elevation_color_version = 4
    runtime._context = SimpleNamespace(request_repaint=request_repaint)

    runtime.refresh_after_elevation_change(section_id=2)

    assert runtime.elevation_color_version == 5
    assert repaint_calls == 1


def test_runtime_refresh_after_elevation_change_can_request_throttled_repaint() -> None:
    repaint_calls = 0
    throttled_calls: list[int] = []

    def request_repaint() -> None:
        nonlocal repaint_calls
        repaint_calls += 1

    def request_repaint_throttled(*, min_interval_ms: int) -> None:
        throttled_calls.append(min_interval_ms)

    runtime = _RuntimeCoreMixin.__new__(_RuntimeCoreMixin)
    runtime._elevation_color_version = 9
    runtime._context = SimpleNamespace(
        request_repaint=request_repaint,
        request_repaint_throttled=request_repaint_throttled,
    )

    runtime.refresh_after_elevation_change(throttled=True)

    assert runtime.elevation_color_version == 10
    assert throttled_calls == [33]
    assert repaint_calls == 0
