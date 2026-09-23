from sg_viewer.services.trackside_objects import (
    TracksideObject,
    trackside_object_from_payload,
    trackside_object_to_payload,
)


def test_land_object_reference_round_trips_in_project_payload() -> None:
    obj = TracksideObject(
        filename="grandstand",
        x=0,
        y=0,
        z=0,
        yaw=0,
        pitch=0,
        tilt=0,
        land_object_name="Grandstand Outline",
    )

    payload = trackside_object_to_payload(obj)
    restored = trackside_object_from_payload(payload)

    assert payload["land_object_name"] == "Grandstand Outline"
    assert restored.land_object_name == "Grandstand Outline"
