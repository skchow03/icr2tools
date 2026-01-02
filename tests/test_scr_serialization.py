"""Tests for SCR segment serialization helpers."""

from icr2_core.cam.helpers import _serialize_scr_segments
from track_viewer.model.camera_models import CameraViewEntry, CameraViewListing


def test_serialize_scr_segments_prefers_type_index_and_camera_type() -> None:
    """Ensure type-specific identifiers are written instead of global indices."""

    views = [
        CameraViewListing(
            view=2,
            label="TV2",
            entries=[
                CameraViewEntry(
                    camera_index=12,
                    type_index=0,
                    camera_type=7,
                    start_dlong=100,
                    end_dlong=200,
                    mark=None,
                )
            ],
        )
    ]

    # The serialized segment should reference the type-specific index (0)
    # and use the camera type as the mark (7), not the global camera index (12).
    assert _serialize_scr_segments(views) == [1, 1, 7, 0, 100, 200]
