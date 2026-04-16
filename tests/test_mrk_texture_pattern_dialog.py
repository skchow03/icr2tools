import pytest

try:
    from PyQt5 import QtWidgets
    from sg_viewer.ui.mrk_textures_dialog import (
        MrkTextureDefinition,
        MrkTexturePatternDialog,
        MrkTexturesDialog,
    )
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


def test_blank_pattern_adds_first_texture_from_first_combo_selection(qapp):
    dialog = MrkTexturePatternDialog(None, ["A", "B"], [])
    try:
        dialog._combo.setCurrentText("B")

        dialog._on_combo_activated()

        assert dialog.selected_pattern() == ["B"]
    finally:
        dialog.close()


def test_move_buttons_reorder_pattern(qapp):
    dialog = MrkTexturePatternDialog(None, ["A", "B"], ["A", "B", "A"])
    try:
        dialog._list.setCurrentRow(1)
        dialog._move_selected_up()
        assert dialog.selected_pattern() == ["B", "A", "A"]

        dialog._move_selected_down()
        assert dialog.selected_pattern() == ["A", "B", "A"]
    finally:
        dialog.close()


def test_texture_definitions_move_buttons_reorder_rows(qapp):
    dialog = MrkTexturesDialog(
        None,
        (
            MrkTextureDefinition("A", "a", 0, 0, 1, 1, "#FF0000"),
            MrkTextureDefinition("B", "b", 0, 0, 1, 1, "#00FF00"),
        ),
    )
    try:
        dialog._table.selectRow(1)
        dialog._move_selected_row_up()
        assert [definition.texture_name for definition in dialog.texture_definitions()] == ["B", "A"]

        dialog._move_selected_row_down()
        assert [definition.texture_name for definition in dialog.texture_definitions()] == ["A", "B"]
    finally:
        dialog.close()
