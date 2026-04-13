from __future__ import annotations

from dataclasses import dataclass

from sg_viewer.services.tsd_io import TrackSurfaceDetailLine, normalize_tsd_command


@dataclass(frozen=True)
class TsdTransverseLineObject:
    name: str
    section_index: int
    adjusted_dlong: int
    line_width_500ths: int
    right_dlat_bound: int
    left_dlat_bound: int
    color_index: int = 36
    command: str = "Detail"

    @property
    def center_dlat(self) -> int:
        return int(round((int(self.left_dlat_bound) + int(self.right_dlat_bound)) * 0.5))

    @property
    def tsd_width_500ths(self) -> int:
        return max(1, int(round(abs(int(self.left_dlat_bound) - int(self.right_dlat_bound)))))

    def generated_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        command = normalize_tsd_command(self.command)
        start_dlong = int(self.adjusted_dlong)
        line_width = max(1, int(self.line_width_500ths))
        end_dlong = start_dlong + line_width
        return (
            TrackSurfaceDetailLine(
                color_index=int(self.color_index),
                width_500ths=max(1, int(self.tsd_width_500ths)),
                start_dlong=start_dlong,
                start_dlat=int(self.center_dlat),
                end_dlong=end_dlong,
                end_dlat=int(self.center_dlat),
                command=command,
            ),
        )


@dataclass(frozen=True)
class TsdDoubleSolidLineObject:
    name: str
    start_adjusted_dlong: int
    end_adjusted_dlong: int
    dlat: int
    line_width_500ths: int
    color_index: int = 36
    command: str = "Detail"

    @property
    def lateral_offset_500ths(self) -> int:
        return max(1, int(self.line_width_500ths))

    def generated_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        command = normalize_tsd_command(self.command)
        line_width = max(1, int(self.line_width_500ths))
        center_dlat = int(self.dlat)
        offset = int(self.lateral_offset_500ths)
        left_dlat = center_dlat + offset
        right_dlat = center_dlat - offset
        start_dlong = int(self.start_adjusted_dlong)
        end_dlong = int(self.end_adjusted_dlong)
        return (
            TrackSurfaceDetailLine(
                color_index=int(self.color_index),
                width_500ths=line_width,
                start_dlong=start_dlong,
                start_dlat=left_dlat,
                end_dlong=end_dlong,
                end_dlat=left_dlat,
                command=command,
            ),
            TrackSurfaceDetailLine(
                color_index=int(self.color_index),
                width_500ths=line_width,
                start_dlong=start_dlong,
                start_dlat=right_dlat,
                end_dlong=end_dlong,
                end_dlat=right_dlat,
                command=command,
            ),
        )


@dataclass(frozen=True)
class TsdZebraCrossingObject:
    name: str
    start_dlong: int
    right_dlat: int
    left_dlat: int
    stripe_width_500ths: int
    stripe_length_500ths: int
    stripe_spacing_500ths: int
    color_index: int = 36
    command: str = "Detail"

    @property
    def stripe_count(self) -> int:
        width = max(1, int(self.stripe_width_500ths))
        spacing = max(0, int(self.stripe_spacing_500ths))
        stride = width + spacing
        if stride <= 0:
            return 1
        span = abs(int(self.left_dlat) - int(self.right_dlat))
        return max(1, (span // stride) + 1)

    def generated_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        command = normalize_tsd_command(self.command)
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
        for _ in range(self.stripe_count):
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


def tsd_object_to_payload(
    obj: TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject,
) -> dict[str, object]:
    if isinstance(obj, TsdDoubleSolidLineObject):
        return {
            "type": "double_solid_line",
            "name": obj.name,
            "start_adjusted_dlong": int(obj.start_adjusted_dlong),
            "end_adjusted_dlong": int(obj.end_adjusted_dlong),
            "dlat": int(obj.dlat),
            "line_width_500ths": int(obj.line_width_500ths),
            "color_index": int(obj.color_index),
            "command": normalize_tsd_command(obj.command),
        }
    if isinstance(obj, TsdTransverseLineObject):
        return {
            "type": "transverse_line",
            "name": obj.name,
            "section_index": int(obj.section_index),
            "adjusted_dlong": int(obj.adjusted_dlong),
            "line_width_500ths": int(obj.line_width_500ths),
            "right_dlat_bound": int(obj.right_dlat_bound),
            "left_dlat_bound": int(obj.left_dlat_bound),
            "center_dlat": int(obj.center_dlat),
            "tsd_width_500ths": int(obj.tsd_width_500ths),
            "color_index": int(obj.color_index),
            "command": normalize_tsd_command(obj.command),
        }
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


def tsd_object_from_payload(
    payload: dict[str, object],
) -> TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject:
    payload_type = payload.get("type")
    if payload_type == "double_solid_line":
        return TsdDoubleSolidLineObject(
            name=str(payload.get("name") or "Double Solid Line"),
            start_adjusted_dlong=int(payload["start_adjusted_dlong"]),
            end_adjusted_dlong=int(payload["end_adjusted_dlong"]),
            dlat=int(payload["dlat"]),
            line_width_500ths=max(1, int(payload["line_width_500ths"])),
            color_index=int(payload.get("color_index", 36)),
            command=normalize_tsd_command(str(payload.get("command", "Detail"))),
        )
    if payload_type == "transverse_line":
        right_bound = payload.get("right_dlat_bound")
        left_bound = payload.get("left_dlat_bound")
        if right_bound is None or left_bound is None:
            center = int(payload.get("center_dlat", 0))
            width = max(1, int(payload.get("tsd_width_500ths", 1)))
            half_width = int(round(width / 2.0))
            right_bound = center - half_width
            left_bound = center + half_width
        return TsdTransverseLineObject(
            name=str(payload.get("name") or "Transverse Line"),
            section_index=max(0, int(payload.get("section_index", 0))),
            adjusted_dlong=int(payload["adjusted_dlong"]),
            line_width_500ths=max(1, int(payload["line_width_500ths"])),
            right_dlat_bound=int(right_bound),
            left_dlat_bound=int(left_bound),
            color_index=int(payload.get("color_index", 36)),
            command=normalize_tsd_command(str(payload.get("command", "Detail"))),
        )
    if payload_type != "zebra_crossing":
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
        stripe_width_500ths=max(1, int(payload["stripe_width_500ths"])),
        stripe_length_500ths=max(1, int(payload["stripe_length_500ths"])),
        stripe_spacing_500ths=max(0, int(payload["stripe_spacing_500ths"])),
        color_index=int(payload.get("color_index", 36)),
        command=normalize_tsd_command(str(payload.get("command", "Detail"))),
    )
