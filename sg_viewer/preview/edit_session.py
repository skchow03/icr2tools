from __future__ import annotations

from typing import Callable, Iterable

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.preview.geometry import curve_angles
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.model.sg_document import SGDocument


class EditSession:
    def __init__(self, sections: list[SectionPreview]) -> None:
        self._original_sections = list(sections)
        self._sections = list(sections)

    def apply_mutation(self, mutation_fn: Callable[..., list[SectionPreview]], *args, **kwargs) -> None:
        self._sections = mutation_fn(self._sections, *args, **kwargs)

    def commit(self, sg_document: SGDocument) -> None:
        if sg_document.sg_data is None:
            raise ValueError("No SG data loaded.")
        sg_document.set_sg_data(apply_preview_to_sgfile(sg_document.sg_data, self._sections))

    def cancel(self) -> None:
        self._sections = list(self._original_sections)

    def preview_sections(self) -> list[SectionPreview]:
        return list(self._sections)


def apply_preview_to_sgfile(sgfile: SGFile, sections: Iterable[SectionPreview]) -> SGFile:
    sections_list = list(sections)
    if not sections_list:
        raise ValueError("No sections available to save.")

    desired_section_count = len(sections_list)
    current_section_count = len(sgfile.sects)

    if desired_section_count != current_section_count:
        section_record_length = 58 + 2 * sgfile.num_xsects
        if desired_section_count > current_section_count:
            template_section = [0] * section_record_length
            for _ in range(desired_section_count - current_section_count):
                sgfile.sects.append(SGFile.Section(template_section, sgfile.num_xsects))
        else:
            sgfile.sects = sgfile.sects[:desired_section_count]

    sgfile.num_sects = desired_section_count
    if len(sgfile.header) > 4:
        sgfile.header[4] = desired_section_count

    def _as_int(value: float | int | None, fallback: int = 0) -> int:
        if value is None:
            return fallback
        return int(round(value))

    for sg_section, preview_section in zip(sgfile.sects, sections_list):
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

    return sgfile
