import pytest

try:  # pragma: no cover
    from PyQt5 import QtGui, QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from sg_viewer.replacecolors import DEFAULT_TRACK3D_COLORS
from sg_viewer.ui.track3d_colors_dialog import Track3DColorDefinitionsDialog


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _sample_palette() -> list[QtGui.QColor]:
    return [QtGui.QColor(i, i, i) for i in range(256)]


def test_select_index_from_palette_updates_spinbox(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    _ = qapp
    dialog = Track3DColorDefinitionsDialog({}, _sample_palette())
    key = next(iter(DEFAULT_TRACK3D_COLORS))
    dialog._spin_boxes[key].setValue(10)

    class FakePaletteDialog:
        def __init__(self, *_args, **_kwargs):
            self.selected_index = 77

        def exec_(self) -> int:
            return QtWidgets.QDialog.Accepted

    monkeypatch.setattr("sg_viewer.ui.track3d_colors_dialog.PaletteColorDialog", FakePaletteDialog)

    dialog._select_index_from_palette(key)

    assert dialog._spin_boxes[key].value() == 77


def test_select_index_from_palette_does_not_change_on_cancel(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    _ = qapp
    dialog = Track3DColorDefinitionsDialog({}, _sample_palette())
    key = next(iter(DEFAULT_TRACK3D_COLORS))
    dialog._spin_boxes[key].setValue(15)

    class FakePaletteDialog:
        def __init__(self, *_args, **_kwargs):
            self.selected_index = 120

        def exec_(self) -> int:
            return QtWidgets.QDialog.Rejected

    monkeypatch.setattr("sg_viewer.ui.track3d_colors_dialog.PaletteColorDialog", FakePaletteDialog)

    dialog._select_index_from_palette(key)

    assert dialog._spin_boxes[key].value() == 15
