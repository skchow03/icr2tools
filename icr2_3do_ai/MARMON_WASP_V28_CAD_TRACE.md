# Marmon Wasp V28 — precise CAD side-trace revision

These six points come directly from the user's 3D CAD trace in the assembled Papyrus N3 **game-coordinate system**. Forward is +X; stock ground plane Z=-8756. They supersede the earlier photograph-derived illustrative dimensions.

| Trace reference | Game X (raw) | Game Z (raw) |
| --- | ---: | ---: |
| Tail tip (upper crown) | -38248 | 12040 |
| Rear deck top at back of driver's seat | -3000 | 13902 |
| Driver's seat (aft seatback plane) | -3000 | — |
| Dashboard top | 13013 | 14071 |
| First bonnet roof cross section after dashboard | 19444 | 12421 |
| Front bonnet crown | 41700 (unchanged X) | 11967 |

The *interpretation* of each Z as the upper outside roof crown is explicit. The user did not supply Y widths or intermediate crown heights; those are retained or smoothly estimated from the V27 silhouette to maintain an outward-facing, connected shell. The tail tip is a very narrow but nondegenerate hexagonal terminal cross-section with crown at exact Z12040.

## Coordinate transform
- The Stage 2 source recipe uses 6000 raw units/foot, +design X from radiator toward rear.
- Final assembled frame: `game_x = 45000 - round(design_x_ft*6000)`; `game_z = round(design_height_ft*6000) - 8756`.
- Traced dashboard X13013 => design X5.3311666667 ft; top Z14071 => height 3.8045 ft.
- Traced next bonnet X19444 => design X4.2593333333 ft; top Z12421 => height 3.5295 ft.
- Rear seat/rear deck X=-3000 => design X8.0 ft; crown Z13902 => height 3.7763333333 ft.
- Tail tip X=-38248 => design X13.8746666667 ft; crown Z12040 => height 3.466 ft.

## Changes
1. Bonnet contains four loft rings instead of five, and 36 exterior surface triangles plus one visible rear dashboard cap. The final two stations match the exact traced X/Z. The previously requested 25%-of-bonnet ramp is replaced by the more specific CAD points; the last roof span covers about 22.4% of the new bonnet length.
2. Cockpit sections and seatback connect directly to X=-3000 at rear, and dashboard shell to X13013 ahead. The shoulder and inner panel heights follow the revised top profiles. Driver torso rear geometry is tucked ahead of the new seatback; helmet remains at Z12824.
3. Rear deck starts at X=-3000 and tapers through the old intermediate station to the tip X=-38248. Crown heights are matched exactly at start and tip; the rest of the width and crown contours are approximations from the preceding V27 silhouette.
4. Fin is a **true single planar 6-sided polygon** at Y=0 in the assembled editable WASP.3D, painted on both sides without a FACE gate. The former editable Stage 2 fin outline (a shallow extrusion used to generate the control-point shape) is converted by the assembly adapter, which removes 13 unwanted side and duplicate-cap polygons plus unused back vertices. This decreases the rendered fin polygon count from 14 to 1 and avoids duplicate Z fighting.
5. Rearward dashboard FACE gate and rear seat closure positions updated; wheels, mirror, helmet, brown suit, yellow palette, fixed black33, and the stock eight PMP head assets unchanged.

**Overall geometry:** The front tire leading edge remains X=-6200 in the Stage 2 frame, while the traced tail endpoint becomes design X83248 raw, making the geometric overall length 178.896 inches. This intentionally replaces the older 187-inch illustrative fit; it does not change the independently maintained 116-inch wheelbase.

## Testing
- Compile N3 to 3DO with the repository's canonical Stage 2 tool.
- Validate the exact traced X/Z values and seatback X in both generated source and compiled coordinates.
- Assert exactly one 2D fin polygon, six coplanar vertices and visibility from both sides.
- Assert bonnet and tail surfaces remain outward and no transverse hidden bulkheads reappear.
- Preserve all existing head-last painter, wheel sorting, and radiator/mirror/front/rear camera checks.
- Real ICR2 rendering and the photographic interpretation of Y widths remain separate visual QA.
