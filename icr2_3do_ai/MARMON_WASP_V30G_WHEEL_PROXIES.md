# Marmon Wasp V30g — stock wheel-proxy dependencies

## What the uploaded stock files establish

The user's uploaded `roadcar.3do` is a base carshape with a `SUPEROBJ` root. Its five `DYNAMIC` children point to `sfront` twice, `srear` twice, and `helmet` once. The four small uploaded 52-byte wrappers are **not wheel geometry**: each has a root `MATERIAL` pointing directly to a negative external wheel geometry ref.

| Wrapper | MIP name | External geometry | Material color word |
| --- | --- | --- | --- |
| sfront.3do | wheel1 | fwheel | 0x01080808 |
| srear.3do | wheel1 | rwheel | 0x01080808 |
| sfrontf.3do | wheel1f | fwheel | 0x01080C08 |
| srearf.3do | wheel1f | rwheel | 0x01080C08 |

The uploaded stock `fwheel.3do` and `rwheel.3do` are wheel geometry models (2,912 bytes each). The Wasp's custom yellow wheels are separate compatible-named geometry files (5,788 bytes each). These two geometry versions should not be confused.

The repository's *synthetic* fixture `icr2_3do_cad/fixtures/sfront.3do` uses material color 45, unlike the **uploaded original** color word; test both structural variants but preserve the uploaded original's opaque value. The installed carset may also need `wheel1.mip`; it was not supplied with the new uploads.

## V30g change

In `icr2_3do_ai/wasp_v30g_wheel_proxies.py`:
- `WASP.3do` retains all 372 original carshape polygons, 63 group-16 textured polygons, MARMON material separation, and 80 directional FACE gates.
- Only wheel names in the five-child `SUPEROBJ` change: `FWHEEL` → `SFRONT`, `RWHEEL` → `SREAR`. The two +Y wheels rotate by 0 and the two −Y wheels by 1800 N3 angular units, copying the original `roadcar.3do` pattern. Wheel centers and helmet anchor are unchanged.
- Generates `SFRONT.3do`, `SREAR.3do` plus optional `SFRONTF.3do`, `SREARF.3do` using source-level N3 `MATERIAL MIP, COLOR, EXTERN`. The N3 compiler now preserves the optional explicit signed material color word; previous MATERIAL syntax remains unchanged.
- The stock original wrappers have a root at body offset 0 and are 52 bytes. Our compiler emits a functionally equivalent root record at body offset 4 after its standard NIL prefix, making them 56 bytes. They have identical MIP, external, and material-color record fields. **When available, exact user-uploaded stock 52-byte wrappers may be safer to install for in-game validation.**
- `MARMON.3do`, `MARMON.mip`, `HELMET.3do`, and both custom wheel meshes remain byte-identical to V30f.
- `SFRONTF` and `SREARF` are optional; the new Wasp `SUPEROBJ` refers only to regular `SFRONT` and `SREAR`.

## How to test in ICR2

Back up the carset's original resources. Put the revised `WASP.3do`, the existing working `MARMON.3do` and `MARMON.mip`, both wheel wrapper `SFRONT.3do` and `SREAR.3do`, the two custom `FWHEEL.3do` and `RWHEEL.3do`, and the existing `HELMET.3do` in the same game-visible object resource scope (either files inside the carset or appropriately repacked DAT entries). Merely placing files in a directory that ICR2 is not using will not resolve the external pointers. The individual-car appearance file still must reference `WASP` / `MARMON`, as verified when textures appeared in V30f.

If still invisible, test with the **uploaded stock** `fwheel.3do` and `rwheel.3do` temporarily in place of the custom Wasp meshes (keep the wrappers and Wasp itself unchanged). If stock wheels appear, investigate custom wheel N3 root/RES structure or culling. If neither appears, investigate game resource search and DAT inclusion, or whether the active appearance actually references the updated shared carshape.

## Verification limits

GitHub Actions compiles and reparses the new model and four wheel-proxy sources, confirms the stock-style root and dependency chain against the `roadcar`/`sfront`/`srear` fixtures, checks the actual uploaded color-word values, and renders/compares thirteen filled preview cameras with strict assets. The CPU preview resolves wrappers but **does not establish in-game visibility**; the V30f and V30g CPU images can be identical despite the latter's more authentic engine object chain.

Do not merge until the user has tested wheel visibility and helmet/tail occlusion in ICR2.
