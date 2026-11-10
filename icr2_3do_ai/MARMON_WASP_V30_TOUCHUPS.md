# Marmon Wasp V30 — radiator and painter-depth touchups

This is a **derived revision of the verified V29 assembly**, not a rewrite of V29 or its frozen Stage 2 recipe. Source of truth for the changes is `icr2_3do_ai/wasp_v30_touchups.py`.

## Requested changes

1. **Radiator front X = 43,671** raw Papyrus game coordinates (V29 X = 42,660; +1,011 raw = 2.022 inches at 6,000 units/foot). The frontal grille and six front rim vertices move together.
2. **Close the radiator/bonnet seam:** The six rear ring vertices at X = 41,700 are set equal to the existing six corresponding bonnet front station vertices. The loft spans the extended front to this exact perimeter; the black front grille remains its own face and rear cap is still absent.
3. **Rear helmet/tail occlusion:** The V30b X-dependent BSPA is nested within the Y-sorted body: `wasp_rear_depth` contains the complete tail exterior and fin, `wasp_pilot_depth` contains the driver and unchanged HELMET DYNAMIC, and `wasp_front_depth` contains the complete bonnet, mirror supports and radiator. Unlike the earlier final overlay, this includes the lower side shell.
4. **Low camera/front radiator occlusion:** From ahead of the grille FACE plane, the front radiator paints over the mirror and helmet, while retaining six rim FACE gates and two mirror-cap gates.
5. **V30c inward-facing surface culling:** 36 exterior upper bonnet/tail triangles and 20 cockpit armrest-top triangles are individually wrapped in outward-wound native `FACE` gates. This is required because a raw N3 `POLY` otherwise renders from either side, even if its normal points up. Body-side walls, cockpit inner panels, wheels and the flat fin remain unchanged.

Wheel models, wheel placement, helmet anchor (-600, 0, 12824), stock helmet and its PMP assets, rear fin shape, CAD body contour, shadow and Wasp palette are unchanged.

## Build

Run the existing V29 Stage 2 recipe generation and `python -m icr2_3do_ai.assemble_wasp` exactly as documented, then:

```sh
python -m icr2_3do_ai.wasp_v30_touchups \
  --baseline /path/to/v29-complete \
  --output /path/to/v30-complete
```

The output contains new **editable `WASP.3D`**, compiler-generated **`WASP.3do`**, original `FWHEEL.3do`, `RWHEEL.3do`, `HELMET.3do`, and a manifest. The V29 binaries and recipe stay available and byte-identical to their benchmark.

The CI inspector additionally makes 13 filled orthographic previews and 13 V29→V30c image comparisons in `3do-ai-generated-models`; the V29 Phase 4 release-candidate artifact remains the historical unchanged-baseline package, **not** the V30 package.

## Validation limits

The V30c builder compiles/reparses the N3 and tests front/rear painter event order for 32 elevated, low, and side-oblique camera positions. It additionally validates 56 new independent compiled FACE nodes (78 total) and **112 per-polygon outward/inward halfspace camera tests**. CI verifies the exact geometry count, byte-identical wheel/helmet dependencies, no parser warnings, 32 painter tests, 13 filled camera views, and before/after image differences. The filled CPU preview is not identical to ICR2's in-game scanline/sprite renderer: **actual in-game verification is still required**, particularly near-side radiator rim coverage and sprite occlusion at intermediate side/rear-low views.

The exact front X value is user-specified. Rear-ring perimeter matching is a geometrical junction correction; it is **not** a claim about precise historical radiator dimensions.
