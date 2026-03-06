from __future__ import annotations

from dataclasses import dataclass


ROTATION_POINT_CENTER = "center"
ROTATION_POINT_TOP_LEFT = "top_left"
ROTATION_POINT_TOP_RIGHT = "top_right"
ROTATION_POINT_BOTTOM_LEFT = "bottom_left"
ROTATION_POINT_BOTTOM_RIGHT = "bottom_right"

ROTATION_POINTS = (
    ROTATION_POINT_CENTER,
    ROTATION_POINT_TOP_LEFT,
    ROTATION_POINT_TOP_RIGHT,
    ROTATION_POINT_BOTTOM_LEFT,
    ROTATION_POINT_BOTTOM_RIGHT,
)


@dataclass(frozen=True)
class TracksideObject:
    filename: str
    x: int
    y: int
    z: int
    yaw: int
    pitch: int
    tilt: int
    description: str = ""
    bbox_length: int = 0
    bbox_width: int = 0
    rotation_point: str = ROTATION_POINT_CENTER

    def to_objects_txt_line(self, index: int) -> str:
        return (
            f'__TSO{index}: DYNAMIC {self.x}, {self.y}, {self.z}, {self.yaw}, '
            f'{self.pitch}, {self.tilt}, 1, EXTERN "{normalize_trackside_filename(self.filename)}";'
        )


def normalize_trackside_filename(filename: str) -> str:
    normalized = filename.strip()
    if normalized.lower().endswith(".3do"):
        normalized = normalized[:-4]
    return normalized


def trackside_object_to_payload(obj: TracksideObject) -> dict[str, object]:
    return {
        "filename": normalize_trackside_filename(obj.filename),
        "x": obj.x,
        "y": obj.y,
        "z": obj.z,
        "yaw": obj.yaw,
        "pitch": obj.pitch,
        "tilt": obj.tilt,
        "description": obj.description,
        "bbox_length": obj.bbox_length,
        "bbox_width": obj.bbox_width,
        "rotation_point": normalize_rotation_point(obj.rotation_point),
    }


def trackside_object_from_payload(payload: dict[str, object]) -> TracksideObject:
    filename = normalize_trackside_filename(str(payload.get("filename", "")))
    if not filename:
        raise ValueError("Trackside object filename is required.")
    return TracksideObject(
        filename=filename,
        x=int(payload.get("x", 0)),
        y=int(payload.get("y", 0)),
        z=int(payload.get("z", 0)),
        yaw=int(payload.get("yaw", 0)),
        pitch=int(payload.get("pitch", 0)),
        tilt=int(payload.get("tilt", 0)),
        description=str(payload.get("description", "")),
        bbox_length=max(0, int(payload.get("bbox_length", 0))),
        bbox_width=max(0, int(payload.get("bbox_width", 0))),
        rotation_point=normalize_rotation_point(str(payload.get("rotation_point", ROTATION_POINT_CENTER))),
    )


def normalize_rotation_point(rotation_point: str) -> str:
    normalized = rotation_point.strip().lower()
    if normalized not in ROTATION_POINTS:
        return ROTATION_POINT_CENTER
    return normalized


def serialize_objects_txt(objects: list[TracksideObject]) -> str:
    return "\n".join(obj.to_objects_txt_line(index) for index, obj in enumerate(objects))
