---
name: icr2-mip-art-director
description: Produce and verify historically grounded, UV-aligned, palette-safe ICR2 car MIP art. Use for liveries, grilles, bonnet panels, number plates and texture cleanup on existing 3DO models.
---

# ICR2 MIP Art Director

Use icr2_3do_ai/mip_workbench.py and follow
icr2_3do_ai/MIP_WORKBENCH.md. This complements, rather than replaces, the
3DO Modeler and existing CAD editor.

## Required workflow

1. Inspect source assets. Identify the actual compiled 3DO, driver wrapper
   if any, target MIP and in-game palette. Distinguish model evidence,
   period-photo evidence and visual approximation.
2. Export the UV template using python -m icr2_3do_ai.mip_workbench export.
   Inspect manifest.json, uv_guide.png and uv_preview_4x.png. Record exact
   instance/polygon IDs and UV vertices. Guessed texture regions do not
   count as established mappings.
3. Map semantic parts manually. Make an explicit part-to-UV table and check
   orientation, seam neighbors, shared texels and body-paintable flags.
   Do not paint wheel or helmet MIPs as car bodywork.
4. Create artwork one part at a time. Use image generation for visually rich
   source motifs (radiator mesh, bonnet hardware, weathered metal).
   Request front/side orthographic tiles without perspective, extraneous
   objects or text. Use deterministic drawing for numbers and trim geometry.
5. Compose through a JSON art plan. Specify the real PNG, verified rectangle
   and scaling mode for every change. Never ask image generation to recreate
   the complete assembled atlas from memory.
6. Build and validate. The builder refuses overwrites, checks source hashes,
   quantizes changed pixels to legal palette indices, preserves untouched
   level-zero indices and verifies MIP round trip. Read the change report.
7. Visual regression. Reopen the new MIP on the real model in CAD. Inspect
   side, front, rear, top and two oblique views, then actual in-game views.
   Check mirrored/reversed artwork, seams, LOD and unintended changes.
   Only then call a livery finished.

## Rules for agents

- Do not generate or replace a full sheet when one component is requested.
- Do not fabricate UV placement or historical component colors.
- Ask the image generator for source art, not byte-exact binary game assets.
- Deterministic tooling owns coordinate placement, alpha composition,
  palette restriction, MIP writing and round-trip verification.
- Original input MIPs and 3DOs remain immutable. Write new outputs.
- Do not assert working in-game from a UV overlay or standalone CAD preview.
- Report unresolved areas as unresolved rather than guessing.
- Report the MIP, 3DO, palette, part, polygon IDs, verified UV region, output
  tile, pixel-change counts and comparison screenshots. Distinguish polygon
  RECOLOR indices from MIP texel palette indices.
