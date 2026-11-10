# Marmon Wasp V30h: wheel RES compatibility experiment

## Why this variant exists

The user reports that wheels are absent on the normal Marmon Wasp but appear when the game switches to `dindycar.3do` after crash damage. This establishes that at least one wheel-rendering path works in-game, but it does **not** yet establish that `dindycar.3do` loads the exact same wheel model or wheel proxy. Avoid concluding that the Wasp's custom wheel files are correct from this observation alone.

Binary inspection of the uploaded actual stock `fwheel.3do` and `rwheel.3do` shows a root `RES` distance switch with 3 child `LIST` nodes at thresholds 280000, 113750, and 0. The custom Wasp `FWHEEL.3do`/`RWHEEL.3do` from V30g have a direct `BSPA` root, 114 solid polygon records, and centered geometry. Both shapes are parsable by our tools, but an ICR2 native wheel loader may place stricter requirements on the root hierarchy. That is a hypothesis, not a documented game guarantee.

## V30h modifications

`wasp_v30h_wheel_lod.py` produces source-editable `FWHEEL.3D` and `RWHEEL.3D` with a root `SWITCH DISTANCE` / `RES` at thresholds 280000, 113750 and 0. Each branch points to a **distinct LIST record** that wraps the same existing BSPA wheel shape. No original polygons, dimensions, colors, UVs, local origin, or windings change. The aim is to isolate native root/LOD compatibility before changing wheel design or optimizing real lower-detail LODs.

`WASP.3do`, `SFRONT.3do`, `SREAR.3do`, `MARMON.3do`, `MARMON.mip`, and `HELMET.3do` remain byte identical to V30g. Wheel wrappers point at `wheel1.mip`; the supplied original wheel mesh files are alternate **diagnostic choices**, not necessary additions to V30h.

## Recommended controlled in-game tests

1. Back up the active carset. Leave the current V30g `WASP.3do`, appearance wrapper, `MARMON.mip`, `SFRONT.3do`, `SREAR.3do` and helmet unchanged. Replace **only** `FWHEEL.3do` and `RWHEEL.3do` with the V30h `RES`-root versions. Make sure the game is actually loading these files (DAT entry vs loose files), then test undamaged Wasp and crashed Wasp.
2. If no wheels show, restore V30g copies and test the *uploaded original stock* `fwheel.3do` and `rwheel.3do` under those names, again replacing **only** the two meshes. The stock wheels have a 6503 raw-unit radius rather than the Wasp custom 8500 radius, so this is a visibility test, not an intended final appearance.
3. If stock wheels appear but custom `RES` wheels do not, there is a further incompatibility within custom wheel geometry or the game's wheel loader. Inspect one-sided faces, RES branches/LOD logic, and texture/palette conventions. If neither show but `dindycar.3do` renders its tires, compare the actual loaded normal carshape and damaged carshape `SUPEROBJ`/DYNAMIC records. Ask for the exact damaged 3DO and installed normal carshape rather than guessing.

**Important:** `FWHEEL.3do` and `RWHEEL.3do` can be shared across every car in a carset. Do not replace global originals in a production carset without a backup or test copy. Keep alternate binaries in a named diagnostic folder until needed.

## Validation

The CI build and parser check the `RES` root, matching thresholds, three distinct immediate LIST children, a shared original BSPA graph, 114 unchanged polygons and identical colors/UVs/XYZ, then evaluate near/mid/far RES selection. The unchanged normal carshape uses 63 textured polygons in group 16 and original stock wheel proxies. Thirteen filled camera previews ensure all linked preview assets resolve. **This does not prove in-game wheels**.

PR: https://github.com/skchow03/icr2tools/pull/1964