from sg_viewer.services.tsd_objects import (
    TsdDashedLinesObject,
    TsdDoubleSolidLineObject,
    TsdTransverseLineObject,
    TsdZebraCrossingObject,
    tsd_object_from_payload,
    tsd_object_to_payload,
)


def test_zebra_crossing_generates_stripes_with_consistent_dlong_span() -> None:
    obj = TsdZebraCrossingObject(
        name="Crossing",
        start_dlong=1000,
        right_dlat=12000,
        left_dlat=-12000,
        stripe_width_500ths=4000,
        stripe_length_500ths=20000,
        stripe_spacing_500ths=1000,
    )

    lines = obj.generated_lines()

    assert len(lines) == obj.stripe_count
    assert all(line.start_dlong == 1000 for line in lines)
    assert all(line.end_dlong == 21000 for line in lines)
    assert [line.start_dlat for line in lines] == [10000, 5000, 0, -5000, -10000]
    assert [line.end_dlat for line in lines] == [10000, 5000, 0, -5000, -10000]


def test_zebra_crossing_stops_at_left_bound() -> None:
    obj = TsdZebraCrossingObject(
        name="Bounded",
        start_dlong=0,
        right_dlat=10000,
        left_dlat=2000,
        stripe_width_500ths=3000,
        stripe_length_500ths=5000,
        stripe_spacing_500ths=1000,
    )

    lines = obj.generated_lines()

    assert len(lines) == 2
    assert [line.start_dlat for line in lines] == [8500, 4500]


def test_zebra_crossing_allows_explicit_bound_margins() -> None:
    obj = TsdZebraCrossingObject(
        name="Margins",
        start_dlong=0,
        right_dlat=-10000,
        left_dlat=12000,
        stripe_width_500ths=2000,
        stripe_length_500ths=5000,
        stripe_spacing_500ths=2000,
        right_margin_500ths=1500,
        left_margin_500ths=2500,
    )

    lines = obj.generated_lines()

    assert [line.start_dlat for line in lines] == [-7500, -3500, 500, 4500, 8500]


def test_zebra_crossing_payload_back_compat_center_dlat() -> None:
    payload = {
        "type": "zebra_crossing",
        "name": "Legacy",
        "start_dlong": 500,
        "center_dlat": 0,
        "stripe_width_500ths": 3000,
        "stripe_length_500ths": 8000,
        "stripe_spacing_500ths": 1000,
        "color_index": 36,
        "command": "Detail",
    }

    obj = tsd_object_from_payload(payload)

    assert obj.right_dlat == -4000
    assert obj.left_dlat == 4000


def test_zebra_crossing_optional_end_transverse_lines() -> None:
    obj = TsdZebraCrossingObject(
        name="With End Caps",
        start_dlong=1000,
        right_dlat=-6000,
        left_dlat=6000,
        stripe_width_500ths=2000,
        stripe_length_500ths=10000,
        stripe_spacing_500ths=1000,
        transverse_line_thickness_500ths=1500,
    )

    lines = obj.generated_lines()

    assert len(lines) == obj.stripe_count + 2
    assert lines[-2].start_dlong == 1000
    assert lines[-2].end_dlong == 2500
    assert lines[-2].start_dlat == 0
    assert lines[-2].end_dlat == 0
    assert lines[-2].width_500ths == 12000
    assert lines[-1].start_dlong == 11000
    assert lines[-1].end_dlong == 12500
    assert lines[-1].start_dlat == 0
    assert lines[-1].end_dlat == 0
    assert lines[-1].width_500ths == 12000


def test_zebra_crossing_payload_round_trip_transverse_line_thickness() -> None:
    payload = {
        "type": "zebra_crossing",
        "name": "Crossing",
        "start_dlong": 1200,
        "right_dlat": -9000,
        "left_dlat": 9000,
        "stripe_width_500ths": 3000,
        "stripe_length_500ths": 7000,
        "stripe_spacing_500ths": 800,
        "transverse_line_thickness_500ths": 2200,
        "color_index": 36,
        "command": "Detail",
    }

    obj = tsd_object_from_payload(payload)
    serialized = tsd_object_to_payload(obj)

    assert isinstance(obj, TsdZebraCrossingObject)
    assert obj.transverse_line_thickness_500ths == 2200
    assert obj.right_margin_500ths == 0
    assert obj.left_margin_500ths == 0
    assert serialized["transverse_line_thickness_500ths"] == 2200
    assert serialized["right_margin_500ths"] == 0
    assert serialized["left_margin_500ths"] == 0


def test_transverse_line_generates_single_line() -> None:
    obj = TsdTransverseLineObject(
        name="Lane Marker",
        section_index=4,
        adjusted_dlong=12000,
        line_width_500ths=1500,
        right_dlat_bound=-18500,
        left_dlat_bound=23500,
        color_index=11,
    )

    lines = obj.generated_lines()

    assert len(lines) == 1
    assert lines[0].start_dlong == 12000
    assert lines[0].end_dlong == 13500
    assert lines[0].start_dlat == 2500
    assert lines[0].end_dlat == 2500
    assert lines[0].width_500ths == 42000
    assert lines[0].color_index == 11


def test_transverse_line_payload_round_trip() -> None:
    payload = {
        "type": "transverse_line",
        "name": "Transverse A",
        "section_index": 3,
        "adjusted_dlong": 2222,
        "line_width_500ths": 3000,
        "right_dlat_bound": -10000,
        "left_dlat_bound": 8000,
        "color_index": 9,
        "command": "Detail",
    }

    obj = tsd_object_from_payload(payload)
    serialized = tsd_object_to_payload(obj)

    assert isinstance(obj, TsdTransverseLineObject)
    assert serialized["type"] == "transverse_line"
    assert serialized["section_index"] == 3
    assert serialized["adjusted_dlong"] == 2222
    assert serialized["right_dlat_bound"] == -10000
    assert serialized["left_dlat_bound"] == 8000


def test_transverse_line_payload_back_compat_center_and_width() -> None:
    payload = {
        "type": "transverse_line",
        "name": "Legacy Transverse",
        "section_index": 1,
        "adjusted_dlong": 5000,
        "line_width_500ths": 2500,
        "center_dlat": -1000,
        "tsd_width_500ths": 18000,
        "color_index": 9,
        "command": "Detail",
    }

    obj = tsd_object_from_payload(payload)

    assert isinstance(obj, TsdTransverseLineObject)
    assert obj.right_dlat_bound == -10000
    assert obj.left_dlat_bound == 8000


def test_double_solid_line_generates_two_lines_with_line_width_gap() -> None:
    obj = TsdDoubleSolidLineObject(
        name="Double Yellow",
        start_adjusted_dlong=1000,
        end_adjusted_dlong=9000,
        dlat=500,
        line_width_500ths=2000,
        color_index=14,
    )

    lines = obj.generated_lines()

    assert len(lines) == 2
    assert [line.start_dlat for line in lines] == [2500, -1500]
    assert [line.end_dlat for line in lines] == [2500, -1500]
    assert all(line.start_dlong == 1000 for line in lines)
    assert all(line.end_dlong == 9000 for line in lines)
    assert all(line.width_500ths == 2000 for line in lines)
    assert all(line.color_index == 14 for line in lines)


def test_double_solid_line_payload_round_trip() -> None:
    payload = {
        "type": "double_solid_line",
        "name": "DSL",
        "start_adjusted_dlong": 100,
        "end_adjusted_dlong": 9900,
        "dlat": -250,
        "line_width_500ths": 1500,
        "color_index": 4,
        "command": "Detail",
    }

    obj = tsd_object_from_payload(payload)
    serialized = tsd_object_to_payload(obj)

    assert isinstance(obj, TsdDoubleSolidLineObject)
    assert serialized["type"] == "double_solid_line"
    assert serialized["start_adjusted_dlong"] == 100
    assert serialized["end_adjusted_dlong"] == 9900
    assert serialized["dlat"] == -250


def test_dashed_lines_generates_multiple_segments_from_ratio() -> None:
    obj = TsdDashedLinesObject(
        name="Dashed",
        start_adjusted_dlong=1000,
        end_adjusted_dlong=12000,
        start_dlat=0,
        end_dlat=0,
        line_thickness_500ths=600,
        line_length_500ths=2000,
        gap_to_line_ratio=0.5,
        color_index=8,
    )

    lines = obj.generated_lines()

    assert [line.start_dlong for line in lines] == [1000, 4000, 7000, 10000]
    assert [line.end_dlong for line in lines] == [3000, 6000, 9000, 12000]
    assert all(line.width_500ths == 600 for line in lines)
    assert all(line.start_dlat == 0 for line in lines)
    assert all(line.end_dlat == 0 for line in lines)
    assert all(line.color_index == 8 for line in lines)


def test_dashed_lines_payload_round_trip() -> None:
    payload = {
        "type": "dashed_lines",
        "name": "Dashed",
        "start_adjusted_dlong": 123,
        "end_adjusted_dlong": 4567,
        "start_dlat": -250,
        "end_dlat": 1250,
        "line_thickness_500ths": 890,
        "line_length_500ths": 1200,
        "gap_to_line_ratio": 1.25,
        "color_index": 7,
        "command": "Detail",
    }

    obj = tsd_object_from_payload(payload)
    serialized = tsd_object_to_payload(obj)

    assert isinstance(obj, TsdDashedLinesObject)
    assert serialized["type"] == "dashed_lines"
    assert serialized["start_adjusted_dlong"] == 123
    assert serialized["end_adjusted_dlong"] == 4567
    assert serialized["start_dlat"] == -250
    assert serialized["end_dlat"] == 1250
    assert serialized["line_thickness_500ths"] == 890
    assert serialized["line_length_500ths"] == 1200
    assert serialized["gap_to_line_ratio"] == 1.25


def test_dashed_lines_payload_defaults_match_editor_defaults() -> None:
    obj = tsd_object_from_payload({"type": "dashed_lines", "name": "Dashed"})

    assert isinstance(obj, TsdDashedLinesObject)
    assert obj.start_dlat == 0
    assert obj.end_dlat == 0
    assert obj.line_thickness_500ths == 3000
    assert obj.line_length_500ths == 60000
    assert obj.gap_to_line_ratio == 3.0


def test_pit_stalls_payload_defaults_preserve_right_negative_left_positive() -> None:
    payload = {
        "type": "pit_stalls",
        "name": "Pit",
    }

    obj = tsd_object_from_payload(payload)

    assert obj.right_dlat == -20000
    assert obj.left_dlat == 20000
