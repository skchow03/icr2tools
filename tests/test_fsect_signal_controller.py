from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from types import SimpleNamespace

from sg_viewer.ui.viewer_controller import SGViewerController


def test_controller_consumes_fsect_intent_and_mutates_preview() -> None:
    calls: list[tuple] = []

    preview = SimpleNamespace(
        update_fsection_dlat=lambda *args, **kwargs: calls.append((args, kwargs)),
        refresh_fsections_preview=lambda: calls.append(("refresh", {})),
    )
    window = SimpleNamespace(
        preview=preview,
        update_selected_section_fsect_table=lambda: calls.append(("table", {})),
    )

    controller = SGViewerController.__new__(SGViewerController)
    controller._window = window

    controller._on_fsect_diagram_dlat_change_requested(1, 4, "end", 88.0, False, False)
    controller._on_fsect_diagram_drag_commit_requested(1, 4, "start", 99.0)

    assert calls[0] == ((1, 4), {"end_dlat": 88.0, "refresh_preview": False, "emit_sections_changed": False})
    assert calls[1] == ((1, 4), {"start_dlat": 99.0, "refresh_preview": False, "emit_sections_changed": True})
    assert calls[2] == ("refresh", {})
    assert calls[3] == ("table", {})


def test_sections_changed_syncs_section_editing_menu_actions() -> None:
    class DummyToggle:
        def __init__(self, enabled: bool) -> None:
            self._enabled = enabled

        def isEnabled(self) -> bool:
            return self._enabled

    class DummyAction:
        def __init__(self) -> None:
            self.enabled: bool | None = None

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

    sections_controller_calls = 0
    sync_after_calls = 0

    controller = SGViewerController.__new__(SGViewerController)
    controller._window = SimpleNamespace(
        new_straight_button=DummyToggle(True),
        new_curve_button=DummyToggle(False),
        split_section_button=DummyToggle(True),
        move_section_button=DummyToggle(True),
        delete_section_button=DummyToggle(False),
        set_start_finish_button=DummyToggle(True),
    )
    controller._new_straight_mode_action = DummyAction()
    controller._new_curve_mode_action = DummyAction()
    controller._split_section_mode_action = DummyAction()
    controller._move_section_mode_action = DummyAction()
    controller._delete_section_mode_action = DummyAction()
    controller._set_start_finish_action = DummyAction()
    controller._sections_controller = SimpleNamespace()

    def _on_sections_changed() -> None:
        nonlocal sections_controller_calls
        sections_controller_calls += 1

    def _sync_after_section_mutation() -> None:
        nonlocal sync_after_calls
        sync_after_calls += 1

    controller._sections_controller.on_sections_changed = _on_sections_changed
    controller._sync_after_section_mutation = _sync_after_section_mutation

    controller._on_sections_changed()

    assert sections_controller_calls == 1
    assert sync_after_calls == 1
    assert controller._new_straight_mode_action.enabled is True
    assert controller._new_curve_mode_action.enabled is False
    assert controller._split_section_mode_action.enabled is True
    assert controller._move_section_mode_action.enabled is True
    assert controller._delete_section_mode_action.enabled is False
    assert controller._set_start_finish_action.enabled is True
