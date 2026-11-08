# 1911 Marmon Wasp — texture-first ICR2 body, revision 5

**Scope:** a deliberately simple, editable 1911 Marmon Wasp #32 geometry blockout for Papyrus ICR2. This is a visual approximation, not a measured historical reconstruction. The previous 120-polygon revision is retained in Git history.

## Rev 5 — mirror attachment and aspect-ratio correction

- Geometry audit revealed two actual errors in Rev 4: the mirror supports started at z=3.305–3.415 ft, floating over the cowl shoulder near y=±1.06; and the mirror was 18 inches wide by just 1.92 inches high.
- Both supports now start inside the sloped dashboard/cowl at **x=6.105 ft**, **y=±1.17 ft**, and **z=2.970 ft**, with cross-sections reaching z=3.016 ft. At this y, the bonnet cross-section surface is ~z=3.071 ft (about **0.655 inches of deliberate overlap** with the end face; the support rises out of the body toward the mirror). This eliminates the floating support.
- Both struts end at **x=6.460 ft**, **y=±0.236 ft**, **z=4.100 ft** and penetrate the mirror housing at x=6.44–6.50, y=±0.333, z=4.060–4.477 ft. This explicitly verifies the upper strut/housing intersection too.
- The housing width changes from **18 inches to 8 inches**, and its visible height from **1.92 inches to 5 inches**. An attributed historical account reports that the original mirror measured 5 by 8 inches; see [Supercars.net's historical summary](https://www.supercars.net/blog/motoring-masterpiece-1932-marmon-v16-victoria-coupe/2/). While this secondary source is not an engineering drawing, its 8:5 aspect matches museum detail photographs ([Hagerty Drivers Foundation](https://driversfoundation.org/register/13)). Treat it as reported, not independently measured.
- **Polygon budget remains 174 polygons, 15 editable components**, including the same four wheel location markers. Nothing else is remodeled. Surface details remain for future textures.

## Rev 4 corrections — black chassis, two mirror struts, rounded body crown

- Added a single **exposed_black_chassis** solid-color underbody box from x=0.62 to x=8.91 ft, y=±1.06 ft and z=0.97–1.58 ft. The yellow bonnet starts at z≈1.50–1.52 ft, so its side elevation now reveals a black lower chassis band. This is a simplified representation of the visible chassis structure, not complete mechanical frame rails.
- Replaced the centrally mounted **mirror_mast** with two thin struts: **mirror_strut_left** starts at the left dashboard/cowl edge (x=6.12, y=-1.06, z=3.36) and meets the left portion of the rearview mirror (x=6.46, y=-0.60, z=4.10); **mirror_strut_right** is its mirrored counterpart. The housing position is unchanged. Both supports have only eight polygons each (caps omitted where they join the body/mirror).
- Changed radiator, long bonnet and pointed-tail cross-sections from rectangular (four-vertex) outlines to **six-vertex convex chamfered shoulders with a narrower flat crown**. This softens the body's profile without decorative tessellation or new textures. The cross-section ring counts remain unchanged: 2 radiator, 3 bonnet, 3 tail.
- Retains the taller cockpit-front bonnet lip, raised pointed rear tip, six-point faceted rounded fin and four separately replaceable wheel-center placeholders from Rev 3.
- **Budget: 174 polygons, 15 named components**, compared with Rev 3's 134 polygons. Of these, 32 polygons are the removable wheel center locators. All new surfaces use verified shared palette black index 48 (RGB 31,31,31), existing yellow 158/159 unchanged. No MIP or texture assignments were introduced.
- In-game color/material rendering, draw order, BSP and LOD remain unverified by the build pipeline.

## Rev 3 corrections (request: higher pointed tail, rounded fin, higher cockpit front)

- Raised the **rear tip** from z=1.94–2.18 ft to z=2.44–2.71 ft. The pointed taper in plan view is unchanged.
- Added **rounded_tail_fin** at x=12.25–14.43 ft, rising to z=3.72 ft, with a six-point convex outline (five short sloping segments across its upper contour). This makes a faceted, rounded dorsal fin / tail number plaque instead of the former triangular shape. At 0.11 ft thickness, the fin stays low-poly and requires only 14 polygons. Its `#32` should be supplied by texture later.
- Raised the **rear edge of the bonnet immediately in front of the cockpit** from z=3.10 ft to 3.42 ft, approximately +3.8 inches. The floor, cockpit length and wheel locations are unchanged.
- Kept all surface detail out of geometry. Bonnet straps, ventilation, seams, grille pattern, number decals and fin lettering are intended for a later mapped texture.

## Complexity

Evolution: original 444 polygons → Rev 2 at 120 → Rev 3 at 134 → **Rev 4 at 174 polygons across 15 named components** including four removable wheel-center markers (32 polygons). The body, fin, chassis and mirror use 142 polygons. This remains a no-texture solid-color prototype, not a finished textured appearance.

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
