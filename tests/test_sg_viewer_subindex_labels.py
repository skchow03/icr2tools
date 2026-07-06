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


def test_section_subindex_start_label_error_identifies_bad_metadata():
    window = _window_without_qt_init()

    with pytest.raises(ValueError) as exc_info:
        window._format_section_subindex_start_label(7, 2, "not-a-dlong")

    message = str(exc_info.value)
    assert "selected SG section index=7" in message
    assert "SubIndex ordinal=2" in message
    assert "raw value type=str" in message
    assert "raw value repr='not-a-dlong'" in message
    assert "SectionList DLONG metadata" in message
    assert "loaded .3d file" in message
    assert exc_info.value.__cause__ is not None


def test_section_subindex_start_label_error_handles_unrepresentable_value():
    window = _window_without_qt_init()

    with pytest.raises(ValueError) as exc_info:
        window._format_section_subindex_start_label(3, 0, BadRepr())

    message = str(exc_info.value)
    assert "selected SG section index=3" in message
    assert "SubIndex ordinal=0" in message
    assert "raw value type=BadRepr" in message
    assert "raw value repr=<unrepresentable BadRepr: repr unavailable>" in message
    assert exc_info.value.__cause__ is not None
