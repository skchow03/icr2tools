from pathlib import Path

import pytest

try:
    from PyQt5 import QtWidgets
    from sg_viewer.ui.app import SGViewerWindow
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_file_menu_exposes_import_trk_from_dat(qapp):
    window = SGViewerWindow()
    try:
        file_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "&File"
        )
        labels = [action.text() for action in file_menu.actions()]
        assert "Import TRK from DAT…" in labels
    finally:
        window.close()


def test_import_trk_from_dat_uses_matching_trk_name(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        calls: list[tuple[str, str]] = []

        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: ("/tmp/example.dat", "DAT files (*.dat *.DAT)"),
        )

        def _fake_extract(dat_path: str, target_name: str) -> bytes:
            calls.append((dat_path, target_name))
            return b"dummy-trk-bytes"

        monkeypatch.setattr(
            "sg_viewer.ui.controllers.features.document_controller.extract_file_bytes",
            _fake_extract,
        )
        monkeypatch.setattr(
            "sg_viewer.ui.controllers.features.document_controller.TRKFile.from_bytes",
            lambda raw: "trk-object",
        )

        imported: list[tuple[object, str]] = []
        monkeypatch.setattr(
            controller._document_controller,
            "_import_trk_data",
            lambda trk, source_name: imported.append((trk, source_name)),
        )

        controller._import_trk_from_dat_file_dialog()

        assert calls == [("/tmp/example.dat", "example.trk")]
        assert imported == [("trk-object", "example.trk")]
    finally:
        window.close()


def test_import_trk_from_dat_resets_to_untitled(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        controller._current_path = Path("/tmp/previous.sg")
        controller._is_untitled = False

        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: ("/tmp/example.dat", "DAT files (*.dat *.DAT)"),
        )
        monkeypatch.setattr(
            "sg_viewer.ui.controllers.features.document_controller.extract_file_bytes",
            lambda *_args, **_kwargs: b"dummy-trk-bytes",
        )
        monkeypatch.setattr(
            "sg_viewer.ui.controllers.features.document_controller.TRKFile.from_bytes",
            lambda _raw: "trk-object",
        )
        monkeypatch.setattr(
            controller._document_controller,
            "_import_trk_data",
            lambda *_args, **_kwargs: None,
        )

        controller._import_trk_from_dat_file_dialog()

        assert controller._current_path is None
        assert controller._is_untitled is True
    finally:
        window.close()
