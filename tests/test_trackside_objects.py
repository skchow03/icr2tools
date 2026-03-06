from sg_viewer.services.trackside_objects import (
    TracksideObject,
    normalize_trackside_filename,
    serialize_objects_txt,
    trackside_object_from_payload,
    trackside_object_to_payload,
)


def test_trackside_filename_normalization_removes_3do_suffix_case_insensitive() -> None:
    assert normalize_trackside_filename("car.3do") == "car"
    assert normalize_trackside_filename("TRUCK.3DO") == "TRUCK"
    assert normalize_trackside_filename("plain_name") == "plain_name"


def test_trackside_payload_and_export_use_filename_without_extension() -> None:
    obj = TracksideObject(filename="tower.3do", x=1, y=2, z=3, yaw=4, pitch=5, tilt=6)

    payload = trackside_object_to_payload(obj)
    assert payload["filename"] == "tower"

    restored = trackside_object_from_payload(payload)
    assert restored.filename == "tower"

    text = serialize_objects_txt([obj])
    assert 'EXTERN "tower";' in text
    assert ".3do" not in text
