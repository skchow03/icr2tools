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
