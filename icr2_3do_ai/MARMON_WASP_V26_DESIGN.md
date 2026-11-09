# Marmon Wasp V26 — bonnet-quarter dashboard cowl

## Revision request
The raised dashboard scuttle in V25 was only 0.27 ft long and visibly too steep. V26 extends the same raised rear cockpit bulkhead **1.40 ft forward** from design X=6.09 to X=4.69. The bonnet spans X=.55 to X=6.15 feet, so the rise now covers exactly **25%** of its nominal length (1.40/5.60). This is a geometric interpretation of the user-supplied side photo, not a published 1911 engineering measurement.

## Geometry
The named editable Stage 2 loft `dashboard_cowl_riser` has three cross-section rings, two transitions with 12 triangles per span, and the existing rear-facing cap at X=6.09. Its upstream cap at X=4.69 is omitted so there is no hidden partition beneath the bonnet. The rear bulkhead stays protected by the rear-facing `FACE` node.

| Design X (ft) | Shoulder height (ft) | Crown height (ft) |
| ---: | ---: | ---: |
| 4.69 | 2.962 | 3.386 |
| 5.39 | 3.290 | 3.718 |
| 6.09 | 3.650 | 4.030 |

The first ring meets the existing bonnet near its local roof top. The intervening ring is a gradual intermediate step. Keep the existing bonnet, fixed 33 black, 148 brown suit and 149 gloves, 158/159 yellow, mirror, fin, external wheels and HELMET sprite. Helmet attachment remains at exactly game Z=12824 and last-painted within the body.

## Exact original PMP sprites
The user provided all eight `helm0001.pmp`–`helm0008.pmp` files in the V26 conversation. They are unmodified external sprite resources and deliberately **not checked into this repository**. Instead, the chat release archive places the eight original files alongside the four compiled 3DOs, the editable sources, and the manifest. The stock `HELMET.3do` references the same eight names and is not modified. Actual sprite appearance is camera/view dependent and still requires a game render check.

## Checks
Regenerate the Stage 2 recipe and assembled WASP.3D/3do through CI; verify all 3 loft ring coordinates in compiled binary, both upper sets of six bright-yellow triangles, the one new rear-facing cap at game X=8460, the missing front cap, face-based visibility from front and back, and unchanged helmet painter order. CI parsing does not verify in-game rasterization.
