from __future__ import annotations

from sg_viewer.preview.runtime_ops.base_context import logger


class _RuntimeCoreValidationMixin:
    def _validate_section_fsects_alignment(self) -> None:
        if len(self._section_manager.sections) != len(self._fsects_by_section):
            raise RuntimeError(
                "Section/Fsect desync: "
                f"{len(self._section_manager.sections)} sections vs "
                f"{len(self._fsects_by_section)} fsect blocks"
            )

    def _mark_xsect_bounds_dirty(self, xsect_index: int) -> None:
        for cache_key, dirty in self._elevation_xsect_bounds_dirty.items():
            if cache_key[1] == self._sg_version:
                dirty.add(xsect_index)
        for cache_key in list(self._elevation_bounds_cache):
            if cache_key[1] == self._sg_version:
                self._elevation_bounds_cache.pop(cache_key, None)

    def _mark_elevation_profile_sections_dirty(
        self, section_index: int, xsect_index: int
    ) -> None:
        self._mark_elevation_profile_span_dirty(
            start_section=section_index,
            end_section=section_index,
            xsect_index=xsect_index,
        )

    def _mark_elevation_profile_span_dirty(
        self,
        *,
        start_section: int,
        end_section: int,
        xsect_index: int,
    ) -> None:
        sg_data = self._document.sg_data
        if sg_data is None:
            return
        total_sections = len(sg_data.sects)
        if total_sections <= 0:
            return

        start = max(0, min(int(start_section), total_sections - 1))
        end = max(0, min(int(end_section), total_sections - 1))
        if start > end:
            start, end = end, start

        # Each section contributes both endpoints to the profile samples; include
        # the boundary section immediately after the span so endpoint values stay
        # coherent without invalidating the entire profile.
        dirty_sections = set(range(start, end + 1))
        if end + 1 < total_sections:
            dirty_sections.add(end + 1)

        for cache_key, dirty in self._elevation_profile_dirty.items():
            if cache_key[1] == self._sg_version and cache_key[2] == xsect_index:
                dirty.update(dirty_sections)

    def validate_document(self) -> bool:
        try:
            self._document.validate()
        except ValueError as exc:
            logger.exception("Validation failed after edit", exc_info=exc)
            return False
        return True
