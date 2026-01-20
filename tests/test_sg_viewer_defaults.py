import pytest

try:  # pragma: no cover - allows tests to be skipped in headless CI without PyQt5
    from sg_viewer.ui.preview_widget_qt import PreviewWidgetQt
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_new_track_has_default_xsects(qapp):
    sgfile = PreviewWidgetQt._create_empty_sgfile()

    assert list(sgfile.header[:4]) == [int.from_bytes(b"\x00\x00GS", "little"), 1, 1, 0]
    assert sgfile.num_xsects == 2
    assert list(sgfile.xsect_dlats) == [-300_000, 300_000]

    template = [0] * (58 + 2 * sgfile.num_xsects)
    section = sgfile.Section(template, sgfile.num_xsects)
    assert section.alt == [0, 0]
    assert section.grade == [0, 0]
