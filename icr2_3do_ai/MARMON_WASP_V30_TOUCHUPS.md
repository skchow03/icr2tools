# Marmon Wasp V30 — radiator and painter-depth touchups

This is a **derived revision of the verified V29 assembly**, not a rewrite of V29 or its frozen Stage 2 recipe. Source of truth for the changes is `icr2_3do_ai/wasp_v30_touchups.py`.

## Requested changes

1. **Radiator front X = 43,671** raw Papyrus game coordinates (V29 X = 42,660; +1,011 raw = 2.022 inches at 6,000 units/foot). The frontal grille and six front rim vertices move together.
2. **Close the radiator/bonnet seam:** The six rear ring vertices at X = 41,700 are set equal to the existing six corresponding bonnet front station vertices. The loft spans the extended front to this exact perimeter; the black front grille remains its own face and rear cap is still absent.
3. **Rear helmet/tail occlusion:** Replace the fixed final helmet layer with an X-view-dependent BSPA grouping: `wasp_rear_upper` (tail roof, fin), `wasp_driver_helmet` (original DYNAMIC), `wasp_front_upper` (bonnet roof, mirrors/struts and radiator). For rear cameras the tail now paints after the helmet; from the front the tail paints first.
4. **Low camera/front radiator occlusion:** When camera X is positive, mirror and helmet paint before the forward radiator, so the +X-only grille covers them. The six existing rim FACE gates and both mirror-cap gates remain intact.

Wheel models, wheel placement, helmet anchor (-600, 0, 12824), stock helmet and its PMP assets, rear fin shape, CAD body contour, shadow and Wasp palette are unchanged.

## Build

Run the existing V29 Stage 2 recipe generation and `python -m icr2_3do_ai.assemble_wasp` exactly as documented, then:

```sh
python -m icr2_3do_ai.wasp_v30_touchups \
  --baseline /path/to/v29-complete \
  --output /path/to/v30-complete
```

The output contains new **editable `WASP.3D`**, compiler-generated **`WASP.3do`**, original `FWHEEL.3do`, `RWHEEL.3do`, `HELMET.3do`, and a manifest. The V29 binaries and recipe stay available and byte-identical to their benchmark.

The CI inspector additionally makes nine filled orthographic previews and nine V29→V30 image comparisons in `3do-ai-generated-models`; the V29 Phase 4 release-candidate artifact remains the historical unchanged-baseline package, **not** the V30 package.

## Validation limits

The V30 builder compiles/reparses the N3 and tests front/rear painter event order for 32 elevated, low, and side-oblique camera positions. CI verifies byte-identical wheel/helmet dependencies, parser warnings, 32 painter tests, and nonzero front camera difference. The filled CPU preview is not identical to ICR2's in-game scanline/sprite renderer: **actual in-game verification is still required**, particularly near-side radiator rim coverage and sprite occlusion at intermediate side/rear-low views.

The exact front X value is user-specified. Rear-ring perimeter matching is a geometrical junction correction; it is **not** a claim about precise historical radiator dimensions.
