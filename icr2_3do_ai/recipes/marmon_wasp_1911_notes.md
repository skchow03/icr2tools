# 1911 Marmon Wasp — texture-first ICR2 body, revision 3

**Scope:** a deliberately simple, editable 1911 Marmon Wasp #32 geometry blockout for Papyrus ICR2. This is a visual approximation, not a measured historical reconstruction. The previous 120-polygon revision is retained in Git history.

## Rev 3 corrections (request: higher pointed tail, rounded fin, higher cockpit front)

- Raised the **rear tip** from z=1.94–2.18 ft to z=2.44–2.71 ft. The pointed taper in plan view is unchanged.
- Added **rounded_tail_fin** at x=12.25–14.43 ft, rising to z=3.72 ft, with a six-point convex outline (five short sloping segments across its upper contour). This makes a faceted, rounded dorsal fin / tail number plaque instead of the former triangular shape. At 0.11 ft thickness, the fin stays low-poly and requires only 14 polygons. Its `#32` should be supplied by texture later.
- Raised the **rear edge of the bonnet immediately in front of the cockpit** from z=3.10 ft to 3.42 ft, approximately +3.8 inches. The floor, cockpit length and wheel locations are unchanged.
- Kept all surface detail out of geometry. Bonnet straps, ventilation, seams, grille pattern, number decals and fin lettering are intended for a later mapped texture.

## Complexity

The original blockout was 444 polygons, the texture-first revision was 120, and this revised version is **134 polygons over 13 components**, including four removable wheel markers (32 polygons). The body and mirror/fin contain 102 polygons. This is a no-texture solid-color prototype, not a finished textured appearance.

## Coordinate conventions

- x forward radiator -> rear pointed tip; y left/right; z upward.
- Recipe unit **feet**, coordinate_scale=6000 raw Papyrus units/ft.
- Documented wheelbase **116 inches**: front wheel center x=1.40 ft, rear x=11.066667 ft. Wheel-center marker heights span z=1.31–1.52 ft around the nominal center derived from documented 34-inch tires.
- Front markers y=±2.90 ft, rear y=±2.80 ft are *estimates*, not measured track widths.
- The tail shape, cockpit cowl elevation, and fin contour are illustrative adjustments guided by period/museum reference views, not dimensions taken from an orthographic survey.

## Materials and palette

Shared `sunny.pcx` indices checked against the repository's `icr2_3do_cad/gamepal.pcx` trailing PCX palette (blob SHA `8784dc6278cb7c057cd717c7b786301a8aa8890a`); see [ICR2 palette guide](https://skchow.com/indy/palette/).

| index | RGB | applied to |
| --- | --- | --- |
| 158 | (255,223,35) | bonnet, cockpit sills, rounded fin |
| 159 | (235,203,0) | boat-tail |
| 48 | (31,31,31) | radiator and mirror mast |
| 49 | (19,19,19) | cockpit floor |
| 40 | (167,167,167) | mirror housing and wheel markers |

No MIP texture exists in the current output. The fin and other surfaces are solid color.

## Historical sources

- [Indianapolis Motor Speedway, 1910 crash](https://www.indianapolismotorspeedway.com/news-multimedia/news/2020/06/15/06-15-the-wreck-of-the-marmon-wasp): notes that the 1910 machine **did not yet have the tail fin**; the 1911 configuration did.
- [HVA / Indianapolis Motor Speedway Museum Wasp sheet](https://s07.static-shell.com/content/dam/royaldutchshell/documents/sema/1911-marmon-wasp.pdf): documents 116-inch wheelbase and pointed tail.
- [Hagerty Drivers Foundation National Historic Vehicle Register](https://www.driversfoundation.org/registry/1911-marmon-wasp): photo references, wheel/tire details and livery.
- [Library of Congress HAER IN-115](https://loc.gov/pictures/item/in0548/): measured drawings for eventual dimensional refinement. This shape has **not** been traced to those drawings.

## Model assembly & limitations

The four named `wheel_*_locator` objects are only temporary small cuboids, **not** finished wheels, and should be removed/replaced with separately modeled wheel 3DOs. The Stage 2 compiler generates independent LIST groups, not a view-dependent BSP hierarchy. Structural compiler/reparser validation is required; in-game polygon visibility, back-face culling, draw order and LOD are not yet verified.
