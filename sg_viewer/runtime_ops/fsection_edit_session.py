from __future__ import annotations

import copy
from dataclasses import replace

from sg_viewer.model.sg_document import SGDocument
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.preview.fsection_preview_builder import build_fsection_preview
from sg_viewer.sg_document_fsects import FSection


class FSectionEditSession:
    def __init__(self, sg_document: SGDocument, section_id: int) -> None:
        self._sg_document = sg_document
        self.section_id = section_id
        self.original_fsections: list[PreviewFSection] = []
        self.preview_fsections: list[PreviewFSection] = []

    def begin(self) -> None:
        self.original_fsections = build_fsection_preview(
            self._sg_document, self.section_id
        )
        self.preview_fsections = copy.deepcopy(self.original_fsections)

    def update_preview(self, index: int, **fields: object) -> None:
        if index < 0 or index >= len(self.preview_fsections):
            raise IndexError("F-section index out of range.")
        self.preview_fsections[index] = replace(
            self.preview_fsections[index], **fields
        )

    def commit(self) -> None:
        fsects: list[FSection] = [
            {
                "start_dlat": fsect.start_dlat,
                "end_dlat": fsect.end_dlat,
                "surface_type": fsect.surface_type,
                "type2": fsect.type2,
            }
            for fsect in self.preview_fsections
        ]
        self._sg_document.replace_fsections(self.section_id, fsects)
        self.original_fsections = copy.deepcopy(self.preview_fsections)

    def cancel(self) -> None:
        self.preview_fsections = copy.deepcopy(self.original_fsections)
