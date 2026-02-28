from sg_viewer.services.tsd_objects import TsdZebraCrossingObject, tsd_object_from_payload


def test_zebra_crossing_generates_stripes_with_consistent_dlong_span() -> None:
    obj = TsdZebraCrossingObject(
        name="Crossing",
        start_dlong=1000,
        right_dlat=12000,
        left_dlat=-12000,
        stripe_count=3,
        stripe_width_500ths=4000,
        stripe_length_500ths=20000,
        stripe_spacing_500ths=1000,
    )

    lines = obj.generated_lines()

    assert len(lines) == 3
    assert all(line.start_dlong == 1000 for line in lines)
    assert all(line.end_dlong == 21000 for line in lines)
    assert [line.start_dlat for line in lines] == [12000, 7000, 2000]
    assert [line.end_dlat for line in lines] == [12000, 7000, 2000]


def test_zebra_crossing_stops_at_left_bound() -> None:
    obj = TsdZebraCrossingObject(
        name="Bounded",
        start_dlong=0,
        right_dlat=10000,
        left_dlat=2000,
        stripe_count=10,
        stripe_width_500ths=3000,
        stripe_length_500ths=5000,
        stripe_spacing_500ths=1000,
    )

    lines = obj.generated_lines()

    assert len(lines) == 3
    assert [line.start_dlat for line in lines] == [10000, 6000, 2000]


def test_zebra_crossing_payload_back_compat_center_dlat() -> None:
    payload = {
        "type": "zebra_crossing",
        "name": "Legacy",
        "start_dlong": 500,
        "center_dlat": 0,
        "stripe_count": 2,
        "stripe_width_500ths": 3000,
        "stripe_length_500ths": 8000,
        "stripe_spacing_500ths": 1000,
        "color_index": 36,
        "command": "Detail",
    }

    obj = tsd_object_from_payload(payload)

    assert obj.right_dlat == -4000
    assert obj.left_dlat == 4000
