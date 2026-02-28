from __future__ import annotations

from dataclasses import dataclass

from sg_viewer.services.tsd_io import TrackSurfaceDetailLine, normalize_tsd_command


@dataclass(frozen=True)
class TsdZebraCrossingObject:
    name: str
    start_dlong: int
    right_dlat: int
    left_dlat: int
    stripe_count: int
    stripe_width_500ths: int
    stripe_length_500ths: int
    stripe_spacing_500ths: int
    color_index: int = 36
    command: str = "Detail"

    def generated_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        command = normalize_tsd_command(self.command)
        count = max(1, int(self.stripe_count))
        width = max(1, int(self.stripe_width_500ths))
        length = max(1, int(self.stripe_length_500ths))
        spacing = max(0, int(self.stripe_spacing_500ths))
        start_dlong = int(self.start_dlong)
        end_dlong = start_dlong + length

        right_dlat = int(self.right_dlat)
        left_dlat = int(self.left_dlat)
        stride = width + spacing
        direction = 1 if left_dlat >= right_dlat else -1

        lines: list[TrackSurfaceDetailLine] = []
        current_dlat = right_dlat
        for _ in range(count):
            if direction > 0 and current_dlat > left_dlat:
                break
            if direction < 0 and current_dlat < left_dlat:
                break
            lines.append(
                TrackSurfaceDetailLine(
                    color_index=int(self.color_index),
                    width_500ths=width,
                    start_dlong=start_dlong,
                    start_dlat=current_dlat,
                    end_dlong=end_dlong,
                    end_dlat=current_dlat,
                    command=command,
                )
            )
            current_dlat += direction * stride
        return tuple(lines)


def tsd_object_to_payload(obj: TsdZebraCrossingObject) -> dict[str, object]:
    return {
        "type": "zebra_crossing",
        "name": obj.name,
        "start_dlong": int(obj.start_dlong),
        "right_dlat": int(obj.right_dlat),
        "left_dlat": int(obj.left_dlat),
        "stripe_count": int(obj.stripe_count),
        "stripe_width_500ths": int(obj.stripe_width_500ths),
        "stripe_length_500ths": int(obj.stripe_length_500ths),
        "stripe_spacing_500ths": int(obj.stripe_spacing_500ths),
        "color_index": int(obj.color_index),
        "command": normalize_tsd_command(obj.command),
    }


def tsd_object_from_payload(payload: dict[str, object]) -> TsdZebraCrossingObject:
    if payload.get("type") != "zebra_crossing":
        raise ValueError("Unsupported TSD object type.")
    right_dlat = payload.get("right_dlat")
    left_dlat = payload.get("left_dlat")
    if right_dlat is None or left_dlat is None:
        center = int(payload.get("center_dlat", 0))
        length = max(1, int(payload["stripe_length_500ths"]))
        half_length = int(round(length / 2.0))
        right_dlat = center - half_length
        left_dlat = center + half_length

    return TsdZebraCrossingObject(
        name=str(payload.get("name") or "Zebra Crossing"),
        start_dlong=int(payload["start_dlong"]),
        right_dlat=int(right_dlat),
        left_dlat=int(left_dlat),
        stripe_count=max(1, int(payload["stripe_count"])),
        stripe_width_500ths=max(1, int(payload["stripe_width_500ths"])),
        stripe_length_500ths=max(1, int(payload["stripe_length_500ths"])),
        stripe_spacing_500ths=max(0, int(payload["stripe_spacing_500ths"])),
        color_index=int(payload.get("color_index", 36)),
        command=normalize_tsd_command(str(payload.get("command", "Detail"))),
    )
