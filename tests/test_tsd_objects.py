from sg_viewer.services.tsd_objects import TsdZebraCrossingObject


def test_zebra_crossing_generates_expected_parallel_stripes() -> None:
    obj = TsdZebraCrossingObject(
        name="Crossing",
        start_dlong=1000,
        center_dlat=0,
        stripe_count=3,
        stripe_width_500ths=4000,
        stripe_length_500ths=20000,
        stripe_spacing_500ths=1000,
    )

    lines = obj.generated_lines()

    assert len(lines) == 3
    assert lines[0].start_dlong == 1000
    assert lines[1].start_dlong == 6000
    assert lines[2].start_dlong == 11000
    assert lines[0].start_dlat == -10000
    assert lines[0].end_dlat == 10000
