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
