from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

from sg_viewer.ui.viewer_controller import SGViewerController


class _Preview:
    def __init__(self) -> None:
        self.repaint_requests = 0

    def request_repaint_throttled(self, *, min_interval_ms: int) -> None:
        assert min_interval_ms == 33
        self.repaint_requests += 1


class _ElevationPanelController:
    def __init__(self) -> None:
        self.refresh_profile_calls: list[bool] = []

    def refresh_elevation_profile(self, *, refresh_table: bool = True) -> None:
        self.refresh_profile_calls.append(refresh_table)


class _SectionEditingCoordinator:
    def __init__(self) -> None:
        self.update_xsect_table_calls = 0

    def update_xsect_table(self) -> None:
        self.update_xsect_table_calls += 1


def _controller() -> SGViewerController:
    controller = SGViewerController.__new__(SGViewerController)
    controller._window = SimpleNamespace(preview=_Preview())
    controller._last_tsd_adjusted_to_sg_ranges = ([1], [2])
    controller._elevation_panel_controller = _ElevationPanelController()
    controller._section_editing_coordinator = _SectionEditingCoordinator()
    return controller


def test_live_xsect_value_sync_updates_open_xsect_table_window() -> None:
    controller = _controller()

    controller._sync_after_xsect_value_change_lightweight()

    assert controller._elevation_panel_controller.refresh_profile_calls == [False]
    assert controller._section_editing_coordinator.update_xsect_table_calls == 1
    assert controller._last_tsd_adjusted_to_sg_ranges == ([], [])
    assert controller._window.preview.repaint_requests == 1


def test_committed_xsect_value_sync_updates_open_xsect_table_window() -> None:
    controller = _controller()
    calls: list[str] = []
    controller._refresh_elevation_profile = lambda: calls.append("profile")
    controller._refresh_xsect_elevation_panel = lambda: calls.append("panel")
    controller._refresh_xsect_elevation_table = lambda: calls.append("table")

    controller._sync_after_xsect_value_change()

    assert calls == ["profile", "panel", "table"]
    assert controller._section_editing_coordinator.update_xsect_table_calls == 1
    assert controller._last_tsd_adjusted_to_sg_ranges == ([], [])
