import pytest

try:
    from PyQt5 import QtCore, QtWidgets
    from sg_viewer.services.tsd_objects import TsdTransverseLineObject
    from sg_viewer.ui.dialogs.tsd_object_dialog import TsdObjectDialog
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


class _Controller:
    _editing_tsd_object_index = None
    _tsd_objects = []
    _tsd_object_dialog_preview_object = None

    def _refresh_tsd_preview_lines(self) -> None:
        pass


def test_transverse_width_is_visible_and_sets_ending_dlong(qapp):
    parent = QtWidgets.QWidget()
    controller = _Controller()
    existing = TsdTransverseLineObject(
        name="Start line",
        section_index=2,
        adjusted_dlong=10_000,
        line_width_500ths=2_500,
        right_dlat_bound=-20_000,
        left_dlat_bound=20_000,
    )

    def edit_and_accept() -> None:
        dialog = next(
            widget
            for widget in qapp.topLevelWidgets()
            if isinstance(widget, QtWidgets.QDialog)
            and widget.windowTitle() == "TSD Object Attributes"
        )
        form = dialog.layout()
        width_row = next(
            row
            for row in range(form.rowCount())
            if form.itemAt(row, QtWidgets.QFormLayout.LabelRole).widget().text()
            == "Transverse Line Width (500ths)"
        )
        width_spin = form.itemAt(width_row, QtWidgets.QFormLayout.FieldRole).widget()
        assert width_spin.isVisible()
        width_spin.setValue(4_000)
        dialog.accept()

    QtCore.QTimer.singleShot(0, edit_and_accept)
    result = TsdObjectDialog(
        parent,
        controller,
        object_count=1,
        selected_section_index=2,
        existing=existing,
    ).get_payload()

    assert isinstance(result, TsdTransverseLineObject)
    assert result.line_width_500ths == 4_000
    generated_line = result.generated_lines()[0]
    assert generated_line.start_dlong == 10_000
    assert generated_line.end_dlong == 14_000

