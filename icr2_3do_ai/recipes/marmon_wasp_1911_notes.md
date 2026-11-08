# 1911 Marmon Wasp — ICR2 body blockout

This is a **low-poly, Stage 2 illustration** of Ray Harroun's 1911 Marmon Wasp #32. It is not a fully measured replica or in-game-tested carshape. The wheels are **not modeled**: there are four named small wheel-center locator cuboids only, so separate wheel 3DOs can be attached later.

## Historical evidence
- [Historic Vehicle Association / Indianapolis Motor Speedway Museum specification sheet](https://s07.static-shell.com/content/dam/royaldutchshell/documents/sema/1911-marmon-wasp.pdf): 116-inch wheelbase, pointed single-seat tail, rearview mirror, steel-covered wooden wheels.
- [Hagerty Drivers Foundation, National Historic Vehicle Register entry](https://www.driversfoundation.org/registry/1911-marmon-wasp): original yellow/black finish, 25-inch wheels with steel covers and 34 x 4.5-inch tires, black cabin.
- [Library of Congress, HAER IN-115](https://loc.gov/pictures/item/in0548/): original measured drawings (two sheets), useful for subsequent silhouette refinements.
- [Hagerty photo register](https://driversfoundation.org/register/13): museum side and three-quarter views.

## Coordinates and estimated geometry
- x axis: forward radiator to rear stinger; increasing x goes to the rear.
- y axis: left and right; centerline y=0.
- z axis: height above ground; ground at z=0.
- Recipe coordinates are **feet**; 1 foot = 6000 raw Papyrus units.
- Front wheel-center x=1.400 ft; rear wheel-center x=11.066667 ft; x spacing 9.666667 ft = 116 in, documented.
- Wheel center z=1.4167 ft derived from 34-inch tire outer diameter; no tire geometry is emitted.
- Lateral locator y coordinates (front ±2.90 ft, rear ±2.80 ft), hood width, section heights, body length (~14.35 ft), fin and cockpit details: **estimated from reference photographs**, not verified measurements.
- Overall body x bounds ~0.27 to 14.62 ft, excluding wheel tires; 34-inch tires would project outside these body bounds once modeled.

## Palette evidence
The color indices below were decoded from the **actual** repository file `icr2_3do_cad/gamepal.pcx` (Git blob SHA `8784dc6278cb7c057cd717c7b786301a8aa8890a`), using its 256-entry trailing PCX RGB palette. The user's [palette guide](https://skchow.com/indy/palette/) verifies shared `gamepal` and `sunny` indices 0 and 25–175.

| Index | RGB | Use |
|---|---|---|
| 158 | 255,223,35 | bright yellow bonnet, cockpit front and fins |
| 159 | 235,203,0 | darker yellow rear boat-tail panels |
| 48 | 31,31,31 | black frame, straps and engine vents |
| 47 | 51,51,51 | radiator grille |
| 49 | 19,19,19 | seat and cockpit floor |
| 40 | 167,167,167 | simple gray mirror and wheel-center locators |
| 148 | 163,103,63 | brown steering-wheel crossbar |

All solid color indices are in the common palette set, chosen for their material. No painted #32 lettering is created: apply a small texture or CAD geometry separately.

## Composition and next steps
The body parts are separate named components; convex cross sections avoid custom binary editing. The engine is enclosed rather than modeled. Hood ventilation holes are represented by separate dark colored inserts. The cockpit void is a deliberate space between the main hood and tail, bridged by low side sills; the Stage 2 generator does not support Boolean cuts.

**Wheels:** make four external 3DOs, with historical 34-inch OD and 4.5-inch nominal tire section width, replacing or removing the four `wheel_*_locator` parts. Align to documented fore/aft centers above. Do not mistake placeholder marker width for final wheel or track width.

The Stage 2 generated LIST structure lacks automated view-dependent BSP and LOD; verify occlusion and backface drawing in CAD and ICR2 before release.
