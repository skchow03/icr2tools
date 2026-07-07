from types import SimpleNamespace

from sg_viewer.services.mrk_logic import auto_detect_mrk_side, mrk_target_length_for_surface_type, normalize_mrk_side


def test_normalize_mrk_side_defaults_to_left() -> None:
    assert normalize_mrk_side(" right ") == "Right"
    assert normalize_mrk_side("unexpected") == "Left"


def test_auto_detect_mrk_side_uses_boundary_mean_dlat() -> None:
    model = SimpleNamespace(
        fsects=[SimpleNamespace(boundaries=[SimpleNamespace(attrs={"dlat_start": -20, "dlat_end": -10})])]
    )
    assert auto_detect_mrk_side(model, 0, 0) == "Right"
    assert auto_detect_mrk_side(model, 0, 99) == "Left"


def test_mrk_target_length_for_surface_type_uses_wall_or_armco_height() -> None:
    assert mrk_target_length_for_surface_type(8, length_multiplier=2, armco_height_500ths=30, wall_height_500ths=10) == 60
    assert mrk_target_length_for_surface_type(4, length_multiplier=2, armco_height_500ths=30, wall_height_500ths=10) == 20
    assert mrk_target_length_for_surface_type(4, length_multiplier=0, armco_height_500ths=30, wall_height_500ths=5) == 1
