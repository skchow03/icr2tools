from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtWidgets

from sg_viewer.ui.main_window import SGViewerWindow


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_window_emits_fsect_intent_signal_on_diagram_change(monkeypatch) -> None:
    _app()
    window = SGViewerWindow(wire_features=False)
    window._fsect_drag_active = False
    monkeypatch.setattr(window, "_update_fsect_dlat_cell", lambda *args, **kwargs: None)

    captured: list[tuple[int, int, str, float, bool, bool]] = []
    window.fsectDiagramDlatChangeRequested.connect(lambda *args: captured.append(args))

    window._on_fsect_diagram_dlat_changed(3, 2, "start", 123.0)

    assert captured == [(3, 2, "start", 123.0, True, True)]


def test_query_track_refresh_updates_overlay_message() -> None:
    _app()
    window = SGViewerWindow(wire_features=False)
    window._query_track_mode_active = True
    window._query_track_result = {
        "section_index": 3,
        "adjusted_dlong": 12000.0,
        "centerline_elevation": 3000.0,
        "boundary_dlats": (("B1", -500.0), ("B2", 500.0)),
    }

    window._refresh_query_track_info_label()

    overlay = window._preview.query_track_overlay_message
    assert "Query Track:" in overlay
    assert "Section #: 3" in overlay
    assert "Boundary DLATs: B1:" in overlay
