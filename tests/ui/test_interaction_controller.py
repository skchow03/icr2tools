from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sg_viewer.model.track_model import TrackModel, TrackSection
from sg_viewer.ui.controllers.interaction_controller import InteractionController


def test_drag_updates_model(tmp_track_model):
    ic = InteractionController(tmp_track_model)
    original = tmp_track_model.get_section(0)
    ic.start_drag(0, "end")
    ic.update_drag(10.0, 5.0)
    ic.end_drag()
    updated = tmp_track_model.get_section(0)
    assert updated.end == (10.0, 5.0)
    assert updated != original


def test_drag_updates_start_handle(tmp_track_model):
    ic = InteractionController(tmp_track_model)
    ic.start_drag(0, "start")
    ic.update_drag(1.0, 2.0)
    ic.end_drag()
    updated = tmp_track_model.get_section(0)
    assert updated.start == (1.0, 2.0)


import pytest


@pytest.fixture
def tmp_track_model():
    return TrackModel([TrackSection(start=(0.0, 0.0), end=(3.0, 4.0))])
