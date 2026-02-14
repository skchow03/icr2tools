import pytest

pytest.importorskip("PyQt5")

from sg_viewer.services.fsect_generation_service import build_generated_fsects


def test_generated_fsects_end_dlat_matches_start_for_all_templates() -> None:
    templates = ("street", "oval", "road")

    for template in templates:
        fsects = build_generated_fsects(
            template=template,
            track_width=30.0,
            left_grass=10.0,
            right_grass=10.0,
            grass_surface_type=0,
            wall_surface_type=7,
            wall_width=1.0,
            fence_enabled=False,
        )

        assert fsects
        assert all(fsect.end_dlat == fsect.start_dlat for fsect in fsects)
