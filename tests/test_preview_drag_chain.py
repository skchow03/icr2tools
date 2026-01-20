import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:  # pragma: no cover - allows tests to be skipped in headless CI without PyQt5
    from PyQt5 import QtWidgets
    from sg_viewer.ui.preview_widget_qt import PreviewWidgetQt
    from sg_viewer.sg_model import SectionPreview
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def _make_section(idx: int, prev: int, next_: int) -> SectionPreview:
    return SectionPreview(
        section_id=idx,
        type_name="straight",
        previous_id=prev,
        next_id=next_,
        start=(0.0, 0.0),
        end=(0.0, 0.0),
        start_dlong=0.0,
        length=0.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=None,
        end_heading=None,
        polyline=[],
    )


def test_drag_chain_open_track(qapp):
    widget = PreviewWidgetQt()
    widget._sections = [
        _make_section(0, -1, 1),
        _make_section(1, 0, 2),
        _make_section(2, 1, -1),
    ]

    chain = widget._get_drag_chain(1)

    assert chain == [0, 1, 2]


def test_drag_chain_closed_loop(qapp):
    widget = PreviewWidgetQt()
    widget._sections = [
        _make_section(0, 2, 1),
        _make_section(1, 0, 2),
        _make_section(2, 1, 0),
    ]

    chain = widget._get_drag_chain(1)

    assert set(chain) == {0, 1, 2}
    assert len(chain) == 3
