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
    assert "[Space: Freeze]" in overlay


def test_query_track_overlay_includes_boundary_elevations() -> None:
    _app()
    window = SGViewerWindow(wire_features=False)

    text = window._format_query_track_text(
        {
            "section_index": 0,
            "adjusted_dlong": 1000.0,
            "centerline_elevation": 3000.0,
            "boundary_dlats": (("B0", -500.0, 2800.0), ("B1", 500.0, None)),
        }
    )

    assert "Boundary DLATs: B0: -500.0, B1: 500.0" in text
    assert "Boundary Elevations: B0: 2800.0, B1: –" in text


def test_query_track_spacebar_toggles_frozen_mode() -> None:
    _app()
    window = SGViewerWindow(wire_features=False)
    window._query_track_mode_active = True

    window._toggle_query_track_info_freeze()
    assert window._query_track_info_frozen is True

    window._toggle_query_track_info_freeze()
    assert window._query_track_info_frozen is False


def test_query_track_overlay_shows_unfreeze_hint_when_frozen() -> None:
    _app()
    window = SGViewerWindow(wire_features=False)
    window._query_track_mode_active = True
    window._query_track_info_frozen = True
    window._query_track_result = {
        "section_index": 1,
        "adjusted_dlong": None,
        "centerline_elevation": None,
        "boundary_dlats": (),
    }

    window._refresh_query_track_info_label()

    overlay = window._preview.query_track_overlay_message
    assert "[Space: Unfreeze]" in overlay


def test_ruler_button_transitions_to_clear_when_ruler_is_frozen() -> None:
    _app()
    window = SGViewerWindow(wire_features=False)
    start = (0.0, 0.0)
    end = (3000.0, 4000.0)

    window._update_ruler_overlay(start, end)
    window._ruler_frozen = True
    window._update_ruler_button_state()

    assert window.ruler_button.text() == "Clear Ruler"
    assert window._preview.ruler_start_point == start
    assert window._preview.ruler_end_point == end
    assert window._preview.ruler_label == "8.3 ft"


def test_clear_ruler_button_resets_overlay_and_button_text() -> None:
    _app()
    window = SGViewerWindow(wire_features=False)
    window._update_ruler_overlay((0.0, 0.0), (1.0, 1.0))
    window._ruler_frozen = True
    window._update_ruler_button_state()

    window._on_ruler_button_clicked()

    assert window.ruler_button.text() == "Ruler"
    assert window._preview.ruler_start_point is None
    assert window._preview.ruler_end_point is None
    assert window._preview.ruler_label == ""
