"""Diagnostic orthographic line drawings; intentionally NOT game/BSP rendering.

Only geometric edges from the semantic report are drawn. No OpenGL/Qt and no
modification of textures, source assets or actual triangle/material ordering.
"""
from __future__ import annotations

from pathlib import Path


def render_views(geometry, output_dir, *, width=1100, height=800,
                 max_edges=30000):
    from PIL import Image, ImageDraw, ImageFont

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Car convention is X forward/backward, Y left/right, Z height; diagnostic
    # axes only, not proof of a particular vehicle's authoring orientation.
    projections = {
        "side": (0, 2, "X", "Z"),
        "top": (0, 1, "X", "Y"),
        "front": (1, 2, "Y", "Z"),
    }
    faces = geometry["polygons"]
    for name, (ix, iy, ax, ay) in projections.items():
        image = Image.new("RGB", (width, height), (252, 253, 255))
        draw = ImageDraw.Draw(image)
        bounds = geometry.get("bounds")
        if not bounds or not faces:
            draw.text((32, 32), "No polygon geometry", fill=(25, 32, 42))
            image.save(output_dir / f"{name}.png")
            continue
        low = (bounds["min"][ix], bounds["min"][iy])
        high = (bounds["max"][ix], bounds["max"][iy])
        span_x = max(high[0] - low[0], 1.0)
        span_y = max(high[1] - low[1], 1.0)
        margin = 55
        scale = min((width - 2 * margin) / span_x,
                    (height - 2 * margin) / span_y)
        pad_x = (width - span_x * scale) / 2
        pad_y = (height - span_y * scale) / 2

        def point(pt):
            return (
                round(pad_x + (pt[ix] - low[0]) * scale),
                round(height - pad_y - (pt[iy] - low[1]) * scale),
            )

        # Every polygon edge can be valuable evidence; cap extremely large
        # tracks deterministically so image generation remains bounded.
        count = sum(len(p["vertices_world"]) for p in faces)
        stride = max(1, (count + max_edges - 1) // max_edges)
        edge_index = 0
        drawn = 0
        for polygon in faces:
            pts = polygon["vertices_world"]
            if len(pts) < 2:
                continue
            for a, b in zip(pts, pts[1:] + pts[:1]):
                if edge_index % stride == 0:
                    draw.line((point(a), point(b)), fill=(45, 64, 86), width=1)
                    drawn += 1
                edge_index += 1
        draw.rectangle((12, 12, width - 12, height - 12),
                       outline=(185, 199, 214), width=1)
        draw.text((25, 21), f"{name.upper()}  ({ax}/{ay})  |  raw Papyrus units",
                  fill=(20, 30, 40))
        draw.text((25, height - 35),
                  f"Wireframe, no BSP/visibility or MIP sampling | {drawn}/{count} edges",
                  fill=(68, 80, 94))
        image.save(output_dir / f"{name}.png")
