from __future__ import annotations

from dataclasses import dataclass

from sg_viewer.services.tsd_io import TrackSurfaceDetailLine, normalize_tsd_command


@dataclass(frozen=True)
class TsdZebraCrossingObject:
    name: str
    start_dlong: int
    center_dlat: int
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
        half_length = int(round(length / 2.0))
        start_dlat = int(self.center_dlat) - half_length
        end_dlat = int(self.center_dlat) + half_length

        lines: list[TrackSurfaceDetailLine] = []
        current_dlong = int(self.start_dlong)
        for _index in range(count):
            lines.append(
                TrackSurfaceDetailLine(
                    color_index=int(self.color_index),
                    width_500ths=width,
                    start_dlong=current_dlong,
                    start_dlat=start_dlat,
                    end_dlong=current_dlong,
                    end_dlat=end_dlat,
                    command=command,
                )
            )
            current_dlong += width + spacing
        return tuple(lines)


def tsd_object_to_payload(obj: TsdZebraCrossingObject) -> dict[str, object]:
    return {
        "type": "zebra_crossing",
        "name": obj.name,
        "start_dlong": int(obj.start_dlong),
        "center_dlat": int(obj.center_dlat),
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
    return TsdZebraCrossingObject(
        name=str(payload.get("name") or "Zebra Crossing"),
        start_dlong=int(payload["start_dlong"]),
        center_dlat=int(payload["center_dlat"]),
        stripe_count=max(1, int(payload["stripe_count"])),
        stripe_width_500ths=max(1, int(payload["stripe_width_500ths"])),
        stripe_length_500ths=max(1, int(payload["stripe_length_500ths"])),
        stripe_spacing_500ths=max(0, int(payload["stripe_spacing_500ths"])),
        color_index=int(payload.get("color_index", 36)),
        command=normalize_tsd_command(str(payload.get("command", "Detail"))),
    )
