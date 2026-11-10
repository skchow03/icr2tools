# Marmon Wasp V30e — user MARMON.mip texture map

Build target: \`feature/marmon-wasp-v30-radiator-occlusion-20261109\`, PR #1964. This stage uses validated **V30d** as input, changing no underlying bonnet/tail contours, radiator, wheels, cockpit, driver or painter ordering.

The user-supplied \`marmon.mip\` is 128×165 with seven LODs. The original 28,846 bytes are represented **losslessly** in \`marmon_mip_asset.py\`, verified against SHA-256 \`46a6a8bd7e0cd969417710a51c10fa7be8bfa727dcb5935566f178ac12e06d39\`, and copied to \`MARMON.mip\` with exactly the same bytes for installation. It is user artwork, not an inferred stock game texture.

## Atlas coordinates (inclusive pixel bounds)

| Component | U | V | Projection |
| --- | --- | --- | --- |
| Radiator grille front hexagon | 0–47 | 0–42 | Horizontal across ±Y; vertical from grille crown down |
| Bonnet side and roof (30 triangles) | 47–127 | 0–72 | Cross-sectional U unwrap, front at v=0 (top of texture), cockpit dashboard at v=72 |
| Tail side and roof (30 triangles) | 47–127 | 74–127 | Same cross-sectional U profile, cockpit at v=74, point at v=127 |
| Dorsal fin numeral | 104–127 | 131–154 | 9-vertex flat fin silhouette, crown at top, root at bottom |

The bonnet image is rotated **90° clockwise relative to the car** so that forward appears at the atlas's upper boundary. Its right-hand printed numeral appears reversed with the normal +Y vertical-side projection; the +Y lower side therefore samples the left-side numeral strip \`U=47..63\` with opposite cross-section U ordering. This intentionally reuses that subregion to make both side numbers readable without changing the supplied MIP.

Source engine semantics: native \`POLY [T]\` and \`[<X,Y,Z>, T=<U,V>]\` declarations, with an enclosing \`MATERIAL MIP="MARMON"\` node. Every textured polygon has independent UV-bearing vertices, leaving original shared geometry and all existing V30c roof/cockpit FACE plane points unchanged.

The original single flat two-sided tail-fin polygon is replaced **in the compiled scene** by two coincident \`POLY [T]\` polygons with opposite \`FACE\` gates. Both sides draw their respective version of the number without mirrored lettering. The unreferenced historical source fin remains in the editable N3 for traceability.

**Textured polygons:** 63 in total (30 bonnet + 30 tail + 1 radiator + 2 fin faces). The floor, underside, dashboard, cockpit sidewalls, wheels, mirrors, mirror struts, helmet sprite and shadows remain untextured.

## Build and validate

\`\`\`sh
python -m icr2_3do_ai.wasp_v30e_texture \
  --baseline /tmp/3do-ai-recipes/marmon_wasp_v30d \
  --output /tmp/3do-ai-recipes/marmon_wasp_v30e
\`\`\`

The resulting folder contains the exact original MIP, editable \`WASP.3D\`, compiled \`WASP.3do\`, unchanged external \`FWHEEL.3do\`, \`RWHEEL.3do\`, and \`HELMET.3do\`, and \`v30e_manifest.json\`.

GitHub Actions checks exact MIP SHA, one MARMON material, all 63 reachable textured faces, 80 directional FACE gates (78 old + 2 fin), independent fin visibility on both car sides, 32 painter camera positions, external binary identity, no parser warnings, and 13 sprite-aware before/after orthographic views.

**In-game validation:** Papyrus ICR2's scanline renderer, low-angle occlusion and texture sampling can differ from the CPU preview. Test the radiator number, both bonnet number orientations, and both fin sides under the game's actual rendering. Do not merge the PR or publish the carset without explicit approval.
