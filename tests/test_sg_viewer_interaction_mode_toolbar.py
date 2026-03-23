import pytest

try:
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from sg_viewer.ui.app_bootstrap import bootstrap_window
from sg_viewer.ui.viewer_controller import InteractionMode


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_interaction_mode_toolbar_defaults_to_select(qapp):
    window = bootstrap_window()
    try:
        assert window.interaction_mode_button("select").isChecked()
        assert len(window.interaction_mode_action_group.actions()) == 7
        assert window.controller._current_interaction_mode == InteractionMode.SELECT
    finally:
        window.close()


def test_interaction_mode_toolbar_is_mutually_exclusive(qapp):
    window = bootstrap_window()
    try:
        window.interaction_mode_button("move_point").click()
        assert window.controller._current_interaction_mode == InteractionMode.MOVE_POINT
        assert window.interaction_mode_button("move_point").isChecked()
        assert not window.interaction_mode_button("select").isChecked()

        window.interaction_mode_button("delete").click()
        assert window.controller._current_interaction_mode == InteractionMode.DELETE
        assert window.interaction_mode_button("delete").isChecked()
        assert not window.interaction_mode_button("move_point").isChecked()
        assert window.delete_section_button.isChecked()
    finally:
        window.close()
