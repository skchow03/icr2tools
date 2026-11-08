# 1911 Marmon Wasp — texture-first ICR2 body, revision 8

**Scope:** a deliberately simple, editable 1911 Marmon Wasp #32 geometry blockout for Papyrus ICR2. This is a visual approximation, not a measured historical reconstruction. The previous 120-polygon revision is retained in Git history.

## Rev 8 — radiator/axle alignment and documented total length

**Reason for change:** The original front wheel center at x=1.400 ft was **12.12 inches behind** the radiator front at x=0.390 ft. This incorrectly made the engine/radiator appear too far in front of the front axle. Historical side views of the actual 1911 Wasp place the axle nearly in line with the radiator's forward face, though no precise radiator-to-axle offset is published in the sources used.

**Published 1911 Marmon Wasp dimensions:**
- **116-inch wheelbase** — Historic Vehicle Association / Indianapolis Motor Speedway Museum ([fact sheet](https://s07.static-shell.com/content/dam/royaldutchshell/documents/sema/1911-marmon-wasp.pdf)).
- **187-inch overall length** and **34-inch diameter tires** — Indianapolis Motor Speedway / INDYCAR 2011 centennial race information, [contemporaneous trackside report preserved at Doctor Indy](https://doctorindy.com/wp-content/uploads/2019/06/2011-newscan.pdf), p. 43.
- **34×4.5-inch tires, 25-inch covered wood wheels** — [Hagerty Drivers Foundation historical vehicle register](https://www.driversfoundation.org/registry/1911-marmon-wasp).
- **Side-view reference photographs** — [Hagerty original Marmon Wasp gallery](https://driversfoundation.org/register/13).
- The Library of Congress [HAER IN-115](https://loc.gov/pictures/item/in0548/) lists two measured drawings, but this revision does **not** claim their full dimensioned views were read. Specific nose-to-axle distance and tail geometry are **inferred**, not verified by engineering measurements.

**Geometry adjustments:**
- Front axle / front `FWHEEL` centers moved **12.2 inches forward**, from x=1.400 ft (8400 raw) to x=0.383333 ft (**2300 raw**). The radiator's leading x=0.390 ft (2340 raw) differs from the axle by only **0.08 inch**, i.e. effectively in line.
- Rear axle / `RWHEEL` centers also moved **12.2 inches forward**, from x=11.066667 ft (66400 raw) to x=10.050 ft (**60300 raw**). This **preserves exactly 116 inches** of center-to-center wheelbase (58000 raw units).
- Front and rear transverse axle meshes and left/right leaf-spring arms were shifted to meet the new wheel centers. The black exposed chassis now reaches forward to x=0.28 ft to intersect the front axle. The rear chassis extension already spans x=8.86–11.76 ft and intersects the relocated rear axle; the black chassis, rear body and tail still join.
- **Did not shorten the yellow body.** Its pointed rear tip stays x=14.55 ft (87300 raw). Because the front tire now projects to x=(2300 − 8500)=−6200 raw, the model's overall extent to the tail is **93500 raw units = 187.0 inches**. This is the reported historical overall dimension, instead of the prior approximately 174.8 inches.
- Kept the shape of the U cockpit, twin-strut mirror, rounded tail fin, two standalone wheel models, wheel diameter, color palette and all other bodywork unchanged.
- `assemble_wasp.py` now checks wheelbase, length, and radiator/front-axle proximity as part of the GitHub Actions assembly build.

**Interpretation:** The user observed a car that appeared overly long and a front axle not aligned to the radiator. The measured length comparison shows that the car was actually **too short overall**; the apparent stretch resulted from **axles too far rearward relative to the nose and tail**. Moving both axles fixes those silhouette relationships while fitting the published overall length. Treat the exact front-axle-to-radiator alignment as a historically motivated approximation, not a documented 0.08-inch offset.

## Rev 7 — solid U-shaped cockpit walls and three separate N3 models

**User request:** cockpit is not a see-through frame; the upper silhouette is a shallow U-shaped dip. Front and rear wheel objects must be authored separately and *actually referenced* from the car.

### Body cockpit

- Removed `cockpit_sill_left` and `cockpit_sill_right` (thin former framing) and all four `wheel_*_locator` cuboids.
- Added a **solid side panel on each cockpit side**, assembled from **five adjacent, solid trapezoid sections**, yellow paint index 158 and rear edge 159. They extend in the y direction between ±1.04 and ±1.37 ft, from the cockpit floor z=1.52 ft up to a continuously lowered U-profile as viewed sideways:
  - x=6.10 ft, upper z=3.38 ft (dashboard/cowl)
  - x=6.53, z=2.78
  - x=7.09, z=2.42
  - x=7.92, z=2.40
  - x=8.44, z=2.66
  - x=8.98, z=3.00 (behind the seat)
- These sidewalls are contiguous and **physically filled** down to the floor, not outline-only pipes. Smoothness is a five-chord low-poly approximation of the real U-shaped cockpit edge. Shape is a photo-derived estimate (not digitized from orthographic survey).

### Wheel objects, detachable and reusable

- New N3 model **`FWHEEL.3D`**: 34×4.5-inch black tire, a yellow ~25-inch diameter sheet-metal covering over wood spokes, and simple small black front hub.
- New N3 model **`RWHEEL.3D`**: same nominal tire and cover dimensions, with a larger black center hub suggesting the rear mechanical drum hardware. Braking mechanical details are not modeled.
- Each object starts at local origin `(0,0,0)` at wheel center. Tire modeled as a 12-sided black cylinder, covers as two 12-sided shallow yellow discs, and hubs as two 8-sided cylinders. All circles are highly simplified, suitable for ICR2 scale. No spokes (covered by the actual car's steel discs), no MIP textures, no steering or wheel spin behavior authored in the placement.
- **`WASP.3D`** parent is built from the Stage 2 body source with `DYNAMIC` inserts for four external children (two references to `FWHEEL`, two to `RWHEEL`). The complete package contains three editable .3D files and matching three compiled .3do binaries. This is a separate source assembly step in `icr2_3do_ai/assemble_wasp.py`, not a Stage 2 recipe primitive. The compiler supports `DYNAMIC ... EXTERN "NAME"`; names are under the 8-character DOS limit.
- Wheel locations in **raw Papyrus** (1ft=6000): front x=8400, y=±17400, z=8500; rear x=66400, y=±16800, z=8500. Front/rear center x separation = 58000 raw units = **116 inches**. These y track widths remain estimates from Rev 1.
- The solid axles and suspension remain part of the parent `WASP` geometry; wheels are separate and intersect the beam-axle ends. Wheel cylinder extends ±0.1875 ft along y from the wheel-center location (total width 4.5 inches).
- The complete wheel references require the **three compiled .3do files alongside each other** in the CAD viewer's objects folder. Editable sources `WASP.3D`, `FWHEEL.3D`, `RWHEEL.3D` are independent.
- Source-model original 116-inch wheelbase and tire/wheel dimensions: [Hagerty Drivers Foundation National Historic Vehicle Register](https://www.driversfoundation.org/registry/1911-marmon-wasp). The original steel-covered wooden spokes are not separately visible from the outside. Side view and cockpit photos: [Hagerty historic photographs](https://driversfoundation.org/register/13).

### Complexity and validation

- Body-only Stage 2 recipe: **320 polygons across 30 components**, including solid walls and suspension; no markers.
- Each wheel external model: **114 polygons**; repeated twice per car via shared `DYNAMIC` references, rather than baking duplicate wheel meshes into the body.
- The complete visible scene should consist of **1 parent plus 4 external wheel instances**. Correct external filenames, placements and compiler-parser round-trip are checked by the assembly script, and GitHub Actions' inspector checks that the compiled scene resolves 5 instances.
- The compiled files may still need hand-authored BSP/LOD, texture work, steering angles and wheel spin. These are static visual blockouts.


## Rev 6 — non-floating wheels, period-style axle and leaf-spring blockout

**Motivation:** the previous iteration provided 4 named wheel location marker cubes but no load path or visible connecting suspension. It also stopped its exposed black underbody at x=8.91 ft, roughly 2.16 ft before the rear wheel center. This revision provides visually and geometrically connected black undercarriage members.

**Added geometry** (11 named components, +94 polygons):
- `front_beam_axle`, a black rectangular-profile solid beam spanning y=−2.88 to +2.88 ft, centered near x=1.40 ft and z=1.38 ft. Its end sections intersect both front marker cubes.
- `rear_beam_axle`, black, spanning y=−2.78 to +2.78 ft, centered at x=11.066667 ft; its ends intersect both rear marker cubes.
- `rear_chassis_extension`, black, x=8.86..11.76 ft, continuing the underbody under the tail and intersecting the rear axle. Existing black chassis ends at x=8.91, so the two pieces overlap by 0.05 ft.
- **Four narrow stylized longitudinal leaf-spring assemblies**, each with two flat angled segments meeting beneath the axle, one spring per wheel side. Component names: `front_leaf_fore_left`, `front_leaf_aft_left`, `rear_leaf_fore_left`, `rear_leaf_aft_left` and four mirrored right-side copies. Their inner y positions (−1.20..−1.03 ft and corresponding positive range) slightly overlap the chassis sides (y=±1.06 ft). Thin side-facing extrusions are 0.10 ft deep in z; end caps omitted to save polygons. Front springs run x≈0.66..2.54; rear springs x≈9.68..12.24; the axle beams intersect the springs near their centers.

**Appearance and fidelity:** Period photographs of the Wasp show exposed frame and transverse axle pieces, and leaf-spring assemblies are characteristic of cars of the era. However, the specific original Wasp spring lengths, shackle connections, exact types, damping hardware, steering linkage and chassis attachment geometry are **not verified** from the evidence used. These are **illustrative** mechanical blockouts, not a reconstruction of measured suspension. The simplified spring packs are meant to provide visual structure at ICR2 scale, not simulate actual suspension travel or steering.

**Complexity:** **268 polygons, 26 named components**, of which 32 polygons remain the four removable wheel locator cubes. Original version was 444 polygons; Rev 5 was 174. Axles are deliberately part of the body model; the four wheel locator parts can be removed independently when separate wheel 3DOs are attached. Surface texture tasks are unchanged.

**Palette:** new axles and rear frame use verified common sunny/gamepal index **48** (31,31,31 dark black); spring leaf packs use index **47** (51,51,51 dark gray). Colors decoded previously from repository `icr2_3do_cad/gamepal.pcx`, PCX palette blob SHA `8784dc6278cb7c057cd717c7b786301a8aa8890a`.

**References / scope:** 
- [Hagerty Drivers Foundation 1911 Marmon Wasp register](https://driversfoundation.org/registry/1911-marmon-wasp) (original Wasp photos, 34x4.5-inch tires and rear-wheel mechanical drums)
- [1911 Wasp photos, Hagerty Drivers Foundation](https://driversfoundation.org/register/13) (visible axle/frame/spring assemblies)
- [HAER IN-115, Library of Congress](https://loc.gov/pictures/item/in0548/) (measured survey resource, not translated into these suspension positions)
- [Wasp replica, Marmon Holdings](https://www.marmon.com/news/our-replica-marmon-wasp-is-complete/) (replica construction reference only, not proof of original mechanics)
- Note: a well-documented commercially sold "Marmon Wasp Re-Creation" uses an *early Nash chassis*, so its reported elliptical springs and radius rods should **not** be assumed to document the genuine 1911 car.

**Validation limits:** the Stage 2 compiler and inspector can verify N3/3DO structure and static geometry diagnostics; they do not verify wheel model mating, renderer BSP ordering, physics or in-game display. Axle-to-marker overlap is asserted by recipe coordinate review.


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

Evolution: original 444 polygons → Rev 2 at 120 → Rev 3 at 134 → **Rev 4 at 174 polygons across 15 named components** including four removable wheel-center markers (32 polygons). For Rev 6 the main geometry plus new suspension totals 236 polygons excluding the 32 wheel locator polygons. This remains a no-texture solid-color prototype, not a finished textured appearance.

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
