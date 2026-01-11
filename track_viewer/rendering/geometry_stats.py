from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GeometryStats:
    surface_polygons: int = 0
    surface_triangles: int = 0
    boundary_segments: int = 0
    centerline_segments: int = 0
    ai_line_segments: dict[str, int] = field(default_factory=dict)

    def total_segments(self) -> int:
        return (
            self.boundary_segments
            + self.centerline_segments
            + sum(self.ai_line_segments.values())
        )
