import pytest

try:
    from PyQt5 import QtWidgets
    from sg_viewer.ui.mrk_textures_dialog import MrkTexturePatternDialog
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_add_inserts_below_selected_entry(qapp):
    dialog = MrkTexturePatternDialog(None, ["A", "B"], ["A", "A"])
    try:
        dialog._combo.setCurrentText("B")
        dialog._list.setCurrentRow(0)

        dialog._add_selected()

        assert dialog.selected_pattern() == ["A", "B", "A"]
    finally:
        dialog.close()


def test_add_appends_when_no_selection(qapp):
    dialog = MrkTexturePatternDialog(None, ["A", "B"], ["A"])
    try:
        dialog._combo.setCurrentText("B")
        dialog._list.setCurrentRow(-1)

        dialog._add_selected()

        assert dialog.selected_pattern() == ["A", "B"]
    finally:
        dialog.close()


def test_remove_all_clears_pattern(qapp):
    dialog = MrkTexturePatternDialog(None, ["A", "B"], ["A", "B", "A"])
    try:
        dialog._remove_all()

        assert dialog.selected_pattern() == []
    finally:
        dialog.close()
