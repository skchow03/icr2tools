from __future__ import annotations

from typing import Iterable, Sequence

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.preview.geometry import curve_angles
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.model.preview_fsection import PreviewFSection

def apply_preview_to_sgfile(
    sgfile: SGFile,
    sections: Iterable[SectionPreview],
    fsects_by_section: Sequence[Sequence[PreviewFSection]] | None = None,
) -> SGFile:
    sections_list = list(sections)
    if not sections_list:
        raise ValueError("No sections available to save.")

    alt_grade_snapshot: list[
        tuple[list[int], list[int], tuple[int, int], tuple[int, int], int]
    ] = []
    for sect in sgfile.sects:
        alt_grade_snapshot.append(
            (
                list(getattr(sect, "alt", [])),
                list(getattr(sect, "grade", [])),
                (
                    int(round(getattr(sect, "start_x", 0))),
                    int(round(getattr(sect, "start_y", 0))),
                ),
                (
                    int(round(getattr(sect, "end_x", 0))),
                    int(round(getattr(sect, "end_y", 0))),
                ),
                int(getattr(sect, "sec_next", -1)),
            )
        )

    def _apply_fsects(
        dest: SGFile.Section, fsects: Sequence[PreviewFSection] | None
    ) -> None:
        fsects = list(fsects or [])
        dest.num_fsects = len(fsects)
        dest.ftype1 = [int(fsect.surface_type) for fsect in fsects]
        dest.ftype2 = [int(fsect.type2) for fsect in fsects]
        dest.fstart = [int(round(fsect.start_dlat)) for fsect in fsects]
        dest.fend = [int(round(fsect.end_dlat)) for fsect in fsects]

        dest.ground_ftype = []
        dest.ground_fstart = []
        dest.ground_fend = []
        dest.bound_ftype1 = []
        dest.bound_ftype2 = []
        dest.bound_fstart = []
        dest.bound_fend = []

        for fsect in fsects:
            if int(fsect.surface_type) in {0, 1, 2, 3, 4, 5, 6}:
                dest.ground_ftype.append(int(fsect.surface_type))
                dest.ground_fstart.append(int(round(fsect.start_dlat)))
                dest.ground_fend.append(int(round(fsect.end_dlat)))
            else:
                dest.bound_ftype1.append(int(fsect.surface_type))
                dest.bound_ftype2.append(int(fsect.type2))
                dest.bound_fstart.append(int(round(fsect.start_dlat)))
                dest.bound_fend.append(int(round(fsect.end_dlat)))

        dest.num_ground_fsects = len(dest.ground_ftype)
        dest.num_boundaries = len(dest.bound_ftype1)

    def _clone_fsects(source: SGFile.Section, dest: SGFile.Section) -> None:
        dest.num_fsects = int(getattr(source, "num_fsects", 0))
        dest.ftype1 = list(getattr(source, "ftype1", []))
        dest.ftype2 = list(getattr(source, "ftype2", []))
        dest.fstart = list(getattr(source, "fstart", []))
        dest.fend = list(getattr(source, "fend", []))

        dest.ground_ftype = list(getattr(source, "ground_ftype", []))
        dest.ground_fstart = list(getattr(source, "ground_fstart", []))
        dest.ground_fend = list(getattr(source, "ground_fend", []))
        dest.bound_ftype1 = list(getattr(source, "bound_ftype1", []))
        dest.bound_ftype2 = list(getattr(source, "bound_ftype2", []))
        dest.bound_fstart = list(getattr(source, "bound_fstart", []))
        dest.bound_fend = list(getattr(source, "bound_fend", []))
        dest.num_ground_fsects = len(dest.ground_ftype)
        dest.num_boundaries = len(dest.bound_ftype1)

    desired_section_count = len(sections_list)
    current_section_count = len(sgfile.sects)

    if desired_section_count != current_section_count:
        section_record_length = 58 + 2 * sgfile.num_xsects
        if desired_section_count > current_section_count:
            template_section = [0] * section_record_length
            for _ in range(desired_section_count - current_section_count):
                new_section = SGFile.Section(template_section, sgfile.num_xsects)
                if sgfile.sects:
                    _clone_fsects(sgfile.sects[-1], new_section)
                sgfile.sects.append(new_section)
        else:
            sgfile.sects = sgfile.sects[:desired_section_count]

    sgfile.num_sects = desired_section_count
    if len(sgfile.header) > 4:
        sgfile.header[4] = desired_section_count

    def _as_int(value: float | int | None, fallback: int = 0) -> int:
        if value is None:
            return fallback
        return int(round(value))

    def _is_reversed_orientation(
        source_start: tuple[int, int],
        source_end: tuple[int, int],
        dest_start: tuple[int, int],
        dest_end: tuple[int, int],
    ) -> bool:
        return source_start == dest_end and source_end == dest_start

    reverse_track_mode = bool(sections_list)
    for preview_section in sections_list:
        source_index = getattr(preview_section, "source_section_id", -1)
        if source_index is None or not (0 <= source_index < len(alt_grade_snapshot)):
            reverse_track_mode = False
            break

        source_start = alt_grade_snapshot[source_index][2]
        source_end = alt_grade_snapshot[source_index][3]
        dest_start = (
            _as_int(preview_section.start[0]),
            _as_int(preview_section.start[1]),
        )
        dest_end = (
            _as_int(preview_section.end[0]),
            _as_int(preview_section.end[1]),
        )
        if not _is_reversed_orientation(source_start, source_end, dest_start, dest_end):
            reverse_track_mode = False
            break

    for index, (sg_section, preview_section) in enumerate(
        zip(sgfile.sects, sections_list)
    ):
        sg_section.type = 2 if preview_section.type_name == "curve" else 1
        sg_section.sec_prev = _as_int(preview_section.previous_id, -1)
        sg_section.sec_next = _as_int(preview_section.next_id, -1)

        start_x, start_y = preview_section.start
        end_x, end_y = preview_section.end
        sg_section.start_x = _as_int(start_x)
        sg_section.start_y = _as_int(start_y)
        sg_section.end_x = _as_int(end_x)
        sg_section.end_y = _as_int(end_y)

        sg_section.start_dlong = _as_int(preview_section.start_dlong)
        sg_section.length = _as_int(preview_section.length)

        center_x, center_y = preview_section.center or (0.0, 0.0)
        sg_section.center_x = _as_int(center_x)
        sg_section.center_y = _as_int(center_y)

        start_heading = (
            (preview_section.sang1, preview_section.sang2)
            if preview_section.sang1 is not None and preview_section.sang2 is not None
            else preview_section.start_heading
        )
        end_heading = (
            (preview_section.eang1, preview_section.eang2)
            if preview_section.eang1 is not None and preview_section.eang2 is not None
            else preview_section.end_heading
        )

        sang1 = sang2 = eang1 = eang2 = None
        if preview_section.type_name == "curve" and preview_section.center is not None:
            sang1, sang2, eang1, eang2 = curve_angles(
                (start_x, start_y),
                (end_x, end_y),
                (center_x, center_y),
                preview_section.radius or 0.0,
            )
        else:
            sang1 = start_heading[0] if start_heading else None
            sang2 = start_heading[1] if start_heading else None
            eang1 = end_heading[0] if end_heading else None
            eang2 = end_heading[1] if end_heading else None

        sg_section.sang1 = _as_int(sang1)
        sg_section.sang2 = _as_int(sang2)
        sg_section.eang1 = _as_int(eang1)
        sg_section.eang2 = _as_int(eang2)

        sg_section.radius = _as_int(preview_section.radius)

        sg_section.recompute_curve_length()

        source_index = getattr(preview_section, "source_section_id", -1)
        if source_index is not None and 0 <= source_index < len(alt_grade_snapshot):
            altitude_source_index = source_index

            if reverse_track_mode:
                previous_index = _as_int(getattr(sgfile.sects[source_index], "sec_prev", -1), -1)
                if 0 <= previous_index < len(alt_grade_snapshot):
                    altitude_source_index = previous_index

            source_alt = list(alt_grade_snapshot[altitude_source_index][0])
            source_grade = list(alt_grade_snapshot[altitude_source_index][1])
            source_start = alt_grade_snapshot[source_index][2]
            source_end = alt_grade_snapshot[source_index][3]
            dest_start = (sg_section.start_x, sg_section.start_y)
            dest_end = (sg_section.end_x, sg_section.end_y)

            should_reverse_orientation = _is_reversed_orientation(
                source_start,
                source_end,
                dest_start,
                dest_end,
            ) or reverse_track_mode

            if should_reverse_orientation:
                # Canonicalization can reverse traversal. Mirror altitude and grade
                # samples to keep each xsect value aligned with the mirrored DLATs.
                source_alt = list(reversed(source_alt))
                source_grade = [-grade for grade in reversed(source_grade)]

            sg_section.alt = source_alt
            sg_section.grade = source_grade

        if fsects_by_section is not None and index < len(fsects_by_section):
            _apply_fsects(sg_section, fsects_by_section[index])

    return sgfile
