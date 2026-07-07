import pytest

try:  # pragma: no cover - allows tests to be skipped without PyQt5
    from sg_viewer.ui.main_window import SGViewerWindow
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


class BadRepr:
    def __repr__(self):
        raise RuntimeError("repr unavailable")


def _window_without_qt_init():
    window = object.__new__(SGViewerWindow)
    window._current_measurement_unit = lambda: "feet"
    return window


def test_section_subindex_start_label_identifies_bad_metadata_without_crashing():
    window = _window_without_qt_init()

    message = window._format_section_subindex_start_label(7, 2, "not-a-dlong")

    assert "section=7" in message
    assert "SubIndex=2" in message
    assert "type=str" in message
    assert "value='not-a-dlong'" in message
    assert "SectionList DLONG metadata" in message


def test_section_subindex_start_label_handles_unrepresentable_value_without_crashing():
    window = _window_without_qt_init()

    message = window._format_section_subindex_start_label(3, 0, BadRepr())

    assert "section=3" in message
    assert "SubIndex=0" in message
    assert "type=BadRepr" in message
    assert "value=<unrepresentable BadRepr: repr unavailable>" in message


def test_section_subindex_start_label_formats_zero_dlong():
    window = _window_without_qt_init()

    assert window._format_section_subindex_start_label(0, 0, 0) == "0.0 ft"
