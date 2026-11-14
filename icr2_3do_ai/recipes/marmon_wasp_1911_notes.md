# 1911 Marmon Wasp — texture-first ICR2 body, revision 16

**Scope:** a deliberately simple, editable 1911 Marmon Wasp #32 geometry blockout for Papyrus ICR2. This is a visual approximation, not a measured historical reconstruction. The previous 120-polygon revision is retained in Git history.

## Rev 16 — mirror face yellow, shaded bodywork, black index 49

**User-directed livery and palette change.** Previous dark pieces used palette 0, but the user specifies that index 0 has game-reserved functions and requests black 49 instead. This supersedes earlier prototype palette advice. No game or track palette files are modified.

### Verified common palette assignments
- **49**, shared sunny/gamepal RGB (19,19,19): *all* intended black polygons, including radiator grille and frame, chassis, cockpit floor, beam axles, leaf springs, both front/rear tire meshes and wheel hubs. Former palette 0 assignments are entirely removed from generated body and wheel sources. The user's game-specific use of 0 is respected even though the PCX RGB entry is black.
- **159**, RGB (235,203,0), **darker yellow**: bonnet outer sides, tapered tail outer sides, entire rounded vertical rear fin, broad U-cockpit exterior panels, and the steel disc covers of both front and rear wheels.
- **158**, RGB (255,223,35), **brighter yellow**: bonnet and tail top crowns and sloping upper shoulders, narrow top rims of both cockpit side panels, the twin mirror support struts, and the mirror's **forward-facing (+X) front end cap**.
- **40**, RGB (167,167,167), **gray metal**: mirror's rear-facing (−X) end cap and its thin perimeter/edge surfaces.
- **27**: stock-game ground shadow polygons, unchanged. The ground shadow's original game-specific treatment is separate from the intended-black-material rule.

### Editable geometry and per-face N3 color changes
- In the Stage 2 master body recipe, the bonnet and tail base component color is 159; the fin and all five source cockpit side panels are also 159, with opposite panels mirrored. The chassis, floor, axle, spring, radiator and all tire/hub source components use 49. Both front/rear wheel recipe disc coverings use 159.
- Stage 2 loft creates a six-sided body ring (bottom, vertical side, upper slope, crown, upper slope, vertical side). Assembly code `icr2_3do_ai/assemble_wasp.py::_paint_wasp_upper_surfaces` selectively recolors upper slope/crown triangles (`p0005..p0010` and `p0017..p0022`) to 158, retaining dark vertical sides 159. The yellow body keeps exactly the same geometry and number of faces.
- Each of 10 cockpit panel components (five per side) retains broad dark-159 side faces; its pair of narrow top-edge triangles `p0003` and `p0004` is recolored to 158 so the U opening has a subtle bright upper lip.
- The mirror housing is extruded along local X and reoriented into the game's +X-forward system: the game-forward cap `mirror_housing_p0000` at X=6360 raw is recolored from 40 to yellow 158. Its aft-facing cap `mirror_housing_p0009` at X=6000 and the other 8 perimeter triangles remain gray 40. The two supporting struts remain bright yellow 158.
- Strict named-polygon assertions and compiled-palette checks are now part of GitHub Actions, including both independent wheel binaries. No material, MIP, new polygon, wheel placement, shadow, radiator FACE rule, or BSP hierarchy changes are made.

**Scope limitations:** These are flat solid-color Papyrus polygons; the palette's in-game lighting and track color behavior remain under the game engine's control. The front/back designations for the mirror here refer to the **car's forward +X axis**, not the driver's direction of view. Any requested distinction of the reflective surface may require reversing that cap assignment.

## Rev 15 — radiator near-side frame visible, far-side frame culled

**Reported issue:** The Rev 13 front-only FACE gate was applied to the entire radiator rim, so the black trim disappeared entirely in the side view, even when the nearer rim edge should remain visible. The corrected front-only culling of the grille is retained, but applying the same visibility rule to a hexagonal shell was too aggressive.

**Source geometry:** The radiator is a 6-vertex hexagonal cross-section extruded between game X=42660 (front) and X=41700 (rear). It has one solid-color hexagonal grille (p0000), twelve perimeter triangles in six pairs (p0001..p0012), and an absent rear cap (p0013). The six perimeter pairs are ordered bottom, negative-Y vertical, negative-Y upper shoulder, top, positive-Y upper shoulder, positive-Y vertical. The winding of each first triangle produces an outward-facing normal in the YZ plane (slightly +X because of the gentle taper).

**Revision:** Keep the positive-X-only grille FACE at X=42600 (0.12 inch behind the grille). Replace the previous single 13-polygon front-only FACE wrapper with a compound radiator LIST containing that **grille FACE** plus six **individual surface-normal FACE nodes**, each wrapping a two-polygon rim strip. Each new FACE plane is defined by actual radiator mesh vertices front_a, front_b, rear_b, so it reliably matches the corresponding visible frame surface. It is not necessary to rebuild the radiator geometry or change its palette.

**Expected viewpoint behavior:** Direct side +Y sees the near positive-Y vertical and upper shoulder rim strips; side -Y sees the near negative-Y strips. Higher camera views may also see the top strip. Opposite/far-side rim strips are culled. The front grille appears only from +X, while a side/rearward camera can still see physically outward-facing rim side surfaces. This preserves legitimate frame trim without the phantom full radiator hexagonal outline.

**Compiled regression gates:** Exactly seven FACE nodes (1 grille + 6 exterior rim strips), exactly 13 unique reachable radiator polygon definitions and no back cap. Twenty source-camera tests (X = 100000, 42610, 42590, 0, -100000; Y = +/-90000; Z=3500 and 12000) assert grille front visibility, at least one near-side rim strip and no far-side rim strips. Four DYNAMIC wheel placements, 8 stock shadow patches, far-wheel/chassis/yellow-body/near-wheel BSP ordering and yellow mirror supports are retained.

**Limits:** The repository compiler validates binary tree traversal, not DOS ICR2's actual rasterization. New in-game screenshots can expose edge cases, including near-end-on angles and physically intersecting radiator/bonnet polygons. The independent wheel objects, wheelbase/overall dimensions and all other components are unchanged.

## Rev 14 — far wheel/black chassis draw order and yellow mirror supports

**Reported in-game behavior:** A rear/far-side yellow wheel center appears over the car's black lower chassis in a user screenshot, even though that wheel should be visually behind the chassis in that viewing direction. The dashboard mirror supports are black but should be yellow.

**Cause confirmed in the N3 hierarchy:** Rev 13 used `root: LIST {wasp_ground_shadow, wasp_black_frame, wasp_vehicle_sort}`. Because `wasp_vehicle_sort` contained all four DYNAMIC wheel instances, even the **far-side pair** was painted after the chassis. The flat painter renderer therefore allows far-side wheel polygons to overwrite the near visible chassis. The existing body BSP correctly sorted *far wheels vs body vs near wheels*, but the chassis was outside that BSP and always drew first.

**Correction:** Root now has `LIST {wasp_ground_shadow, wasp_vehicle_sort}`. Inside the camera-dependent vehicle BSPA, the middle child becomes `wasp_frame_and_body: LIST {wasp_black_frame, wasp_body_ysort}`. Regardless of the camera's Y side, drawing order is exactly: ground shadow, far-side pair of DYNAMIC wheels, 114 black chassis/suspension polygon surfaces, yellow/cockpit body BSP, and near-side pair of DYNAMIC wheels. The wheel models and their 4 child placements are unchanged.

**Paint:** Stage 2 recipe component `mirror_strut_left` changes from common index 0 black to shared sunny/gamepal **index 158 yellow, RGB (255,223,35)**. The opposite support `mirror_strut_right` is mirrored from it, so both become yellow. The mirror housing stays gray index 40.

**Regression validation:** The assembly checks real compiled N3 record hierarchy for root `[LIST shadow, BSPA car]`; camera BSP middle layer is `[LIST chassis, BSPA painted body]`; and actual traversal events from both +Y/-Y cameras enforce `far wheels < black frame < yellow body < near wheels`, plus stock shadow first, all 114 black-frame faces and two yellow struts. Distances, wheelbase 116in, total length 187in, tire height, stock shadow Z/color, radiator full 13-polygon FACE culling, and object names unchanged.

**Limit:** These tests verify structural painter ordering in repository's compiler/parser, not the final DOS game's image. Some surfaces intersect physically and may need finer BSP or geometry changes if artifacts persist in-game. Three compiled objects remain independent (WASP, FWHEEL, RWHEEL).

## Rev 13 — hide complete radiator outline from the sides

**In-game observation:** The previous Rev 12 successfully hid the front radiator hexagon on the side and rear, but the 12 perimeter/rim triangles still displayed as an unwanted black upright frame in front of the yellow bonnet. The in-game screenshot clearly shows this black outline when viewing the Wasp broadside.

**Root cause:** Rev 12 split radiator_face_p0000 (front hexagon) from radiator_face_geo (12 rim triangles) and applied the one-sided front FACE to only the first polygon. The rim triangles were still in an unconditional LIST, so they remained visible when the front hexagon was culled.

**Fix:** Preserve the open-back geometry (p0013 remains absent). Make radiator_face_geo a 13-polygon LIST containing p0000 and all p0001..p0012 rim triangles. Place that entire list under the +X-facing FACE at game X=42600 (60 raw units/0.12 inch behind the front hexagon at X=42660). This one FACE controls both the front radiator and its edge frame. Side and rear views do not draw any radiator triangles. Bonnet and chassis geometry are unchanged. The shared middle-of-car BSPA/BSPN still handles near/far geometry order and is not a visibility plane.

**Regression checks:** The generated WASP binary must have one front radiator FACE node of type 5, wrapping a list with exactly 13 polygons; first member is the six-vertex front cap. It must have normal +X at X=42600. The compiler's original BSP traversal tests 12 camera positions across both Y sides: front X=100000 and X=42610 draw exactly 13 radiator polygons, while X=42590, 41000, 0 and -100000 draw zero. These are verified by geometry-offset membership, not by assuming all black polygons belong to the radiator.

**Unchanged:** Three editable .3D files with compiled .3do counterparts, four external wheel references, 8 stock-style shadow polygons, early black chassis painter ordering, cockpit origin, +X forward orientation, 116-inch wheelbase and 187-inch overall length. Structural compilation tests cannot guarantee all in-game angles or DOS renderer-specific behavior.
## Rev 12 — front radiator face culling at the physical radiator

**Observed issue:** The Wasp's black radiator front appeared when the camera rotated toward the rear of the car, disappearing only after crossing a sorting partition. In the Rev 11 source, the shared `wasp_x_*` triangle defined a **BSPN** at **game X=0** (cockpit origin); the physical front cap is instead at **X=+42,660**. Crucially, a **BSPN is only a near/far ordering node, not a visibility gate**, so moving that shared plane alone would not reliably fix the grille.

**Correction (final assembled `WASP.3D` only):**
- Keep the common middle-of-car X=0 BSPN/BSPA planes for nose/tail and front/rear wheel *ordering*.
- Separate the six-vertex `radiator_face_p0000` front cap from `radiator_face_geo`: that original group now contains **only the 12 side-shell triangles**, which remain drawable from all sides.
- Create `wasp_rad_front_only: FACE (wasp_rad_face_a, wasp_rad_face_b, wasp_rad_face_c), radiator_face_p0000;` and group it with the radiator shell under `wasp_radiator_surfaces`. This one-sided `FACE` accepts camera viewpoints only from the **+X/front** half-space.
- The three oriented visibility-plane points are at **game X=+42,600**, a mere **60 Papyrus units = 0.12 inch immediately behind the front cap (X=+42,660)**. Their winding yields positive +X plane normal. The rear radiator hexagon was already removed in Rev 11 and remains absent.
- Because these operations happen in `assemble_wasp.py` after transforming the design recipe to stock ICR2 coordinates, the *game-ready* WASP parent has the new one-sided front grille without changing the independent wheel models or the Stage 2 body recipe.

**CI regression validation:** The compiled binary must have exactly one positive-X `FACE` at X=42,600 and exactly one reachable front hexagon at X=42,660. For both Y camera sides, test front viewpoints (X=100,000 and 42,610) where that cap is present; rear viewpoints (X=42,590, 41,000, 0, and −100,000) where it is absent. All tests run with the real compiled Papyrus node traversal, not text-string matching. The parent still contains 8 stock-style ground shadow faces, early black chassis geometry and four referenced wheel instances; **no polygon count change** from Rev 11.

**Remaining limitation:** CI reproduces the repository parser's ICR2 face-plane evaluation but does not execute DOS ICR2. The result should still be inspected in-game, especially at extreme grazing angles and with the selected track's palette.

## Rev 11 — stock-style shadow, invisible radiator back, chassis-first drawing

**Stock source:** The user's original indycar.3do (15,364 bytes) has exactly eight flat shadow POLY records at body offsets 10760, 10812, 10836, 10864, 10892, 10920, 10948 and 10976. All use color index 27 and Z=-8501 raw, 255 units above the documented stock tire contact at Z=-8756. The original uses a central decagonal body patch, pointed front nose, nose/tail patches and four wheel-shadow patches.

### New Wasp ground shadow
- The assembled WASP.3D now has eight flat upward-facing shadow polygons at the same Z=-8501 and palette index 27 as the stock model. Their silhouettes are scaled/rearranged to the historic Wasp proportions; no existing stock game geometry is copied.
- The main ground shadow is a ten-point polygon, plus a nose triangle, radiator and tail patches, and four wheel-contact rectangles. All appear as the first parent root LIST child.
- The stock game has a shadow LOD branch, but this version does not add distance switching. No fourth 3D file or texture is needed.

### Radiator rear face removed
- The rear hexagonal radiator cap, radiator_face_p0013 (the original x=0.55-ft plane; x=41700 in final game coordinates), is removed from the final assembled N3 declaration and its pointer from radiator_face_geo. The front-facing radiator polygon p0000 and twelve edge-shell triangles remain.
- This is genuinely absent geometry, not just a visual color override. A compiled binary check rejects any reachable six-sided black cap at x=41700.

### Black chassis always draws before the body
- The final parent root is LIST {wasp_ground_shadow, wasp_black_frame, wasp_vehicle_sort}, retaining the vehicle's camera-dependent near/far wheel BSPA under the third child.
- The black chassis has 13 named components: exposed chassis, floor, two beam axles, rear chassis extension, and eight half-leaf segments. Their 114 polygon faces (palette 0) now draw before the yellow bodywork from both camera sides, instead of being mixed into body or near-side lists.
- Radiator front face and mirror struts remain in body groups for silhouette purposes.
- The assembler verifies from both side cameras that the first eight visible polygons are shadow index 27, followed by all 114 chassis faces index 0, with far wheels before and near wheels after yellow bodywork.

### Unchanged and unverified
- Three editable source files, three binaries, four DYNAMIC wheel references, +X nose direction, cockpit origin, 116-inch wheelbase, 187-inch length, and stock tire contact Z=-8756 remain intact.
- Compilation, binary reparse, external instance resolution and geometry diagnostics pass CI. Actual DOS ICR2 shadow appearance, per-polygon clipping and in-game sorting must be tested by the user; compiler structural validation does not prove runtime correctness.

## Rev 10 — stock ICR2 origin, forward direction and wheel-contact height

**Problem:** the Wasp faced backward in ICR2, used a nose-side origin rather than one near the cockpit, and its wheel/ground geometry was too high. The new calibration is derived directly from the user's uploaded three unmodified game binaries (stock indycar.3do, fwheel(1).3do and rwheel(1).3do). The stock files themselves are not copied to the repository.

### Exact measurements from stock 3DO record trees

- **+X is forward.** IndyCar front wheel centers at x=+32,284, rear x=−29,426, confirming the standard game orientation; the original Wasp model had increasing X toward the tail.
- Stock IndyCar wheel DYNAMIC centers are z=−2,253 raw. Front wheels x=+32,284, y=±17,497; rear x=−29,426, y=±16,248. Original front/rear wheel child meshes both have **radius 6,503 raw** in the XZ plane, yielding **stock ground Z=−8,756 raw**.
- Stock body vertices span X −47,082..+57,171, Y ±19,998, Z −8,501..+10,316 raw.
- Papyrus recipe coordinates have 6,000 units per foot. The historic Wasp has a *larger* 34-inch tire radius of 8,500 raw, so it needs a *higher* axle center than the default IndyCar for the tire bottoms to match the original game's track-ground plane.

### Transformation of the generated source

- Stage 2 recipe remains authored in a nose-to-tail design frame. The final game-ready **WASP.3D parent source** is rotated rigidly 180° around the vertical Z axis and shifted, preserving all polygon winding: **new X=45,000−design X, new Y=−design Y, new Z=design Z−8,756**. All BSP partition vertices undergo exactly the same transformation.
- The origin maps from **design x=45,000**, inside the solid U cockpit opening (36,600..53,880 raw), to game X=0; it is no longer near the radiator.
- Four wheel DYNAMIC translations and orientations are transformed together, including 180° heading specified as N3 value 1800 tenths of a degree (binary signed −2,147,483,648).
- Final front wheel centers: **(+42,700, ±17,400, −256)**. Rear: **(−15,300, ±16,800, −256)**. Tire bottoms equal **−256−8,500=−8,756**, precisely matching stock original wheel contact plane.
- Wasp body-only bounds after transformation: x≈−42,300..+47,140, z≈−2,936..+18,104. Larger height compared with 1995 IndyCar is expected for 1911 body; user should test actual wheel-ground contact in-game.
- Wheelbase remains **58,000 raw = 116 inches**; total length remains **93,500 raw = 187 inches**.
- Front and rear wheel meshes remain two separate 3D objects; main parent still references four wheel instances. Black components remain reserved palette index 0 and camera-dependent BSP sorting from Revision 9 is retained.
- Assembly code asserts forward orientation, cockpit origin, matching wheel/ground plane, wheelbase, external DYNAMIC references, and compiled left/right painter order.

**Limits:** Structurally validated in CAD compiler/parser and inspector, **not yet tested in the user's actual ICR2 executable**. In-game stance, external wheel behavior, clipping and per-polygon BSP draw order may still require targeted changes.

## Rev 9 — in-game palette/occlusion correction (2026-11-08)

**Evidence:** a user-supplied screenshot from ICR2 shows the undercarriage and tire rubber in vivid blue, plus obvious incorrect occlusion of wheel, body and frame surfaces. The old three .3D sources were verified to be flat `LIST` hierarchies without BSP orientation sorting. This is inappropriate for overlapping 3D objects in Papyrus's painter's algorithm, even though compilation and geometry diagnostics were green.

### Black palette correction

- Checked the actual PCX trailing RGB palette from repository blob `icr2_3do_cad/gamepal.pcx` SHA `8784dc6278cb7c057cd717c7b786301a8aa8890a`. Entries **47=(51,51,51)**, **48=(31,31,31)** and **49=(19,19,19)** are neutral grays in the reference palette; **0=(0,0,0)** is explicitly reserved black in both `gamepal.pcx` and `sunny.pcx` (see the [ICR2 palette guide](https://skchow.com/indy/palette/)). The screenshot's large saturated blue surfaces resemble palette hues 126–127 much more than gray 47–49. This is consistent with a runtime palette mismatch/remapping or rendering issue but not proof of the specific mechanism.
- Changed all body/suspension/mirror-strut black recipes using indices 47,48,49 to **0**, including cockpit floor, radiator face, exposed chassis, front/rear axles, leaf springs, and front/rear tire + hub meshes. Yellow remains **158/159** and the mirror metal housing **40** (167,167,167).
- No track palette, shared palette files, colors beyond the affected dark components, or MIP textures were modified.

### Painter sorting in the assembled N3

- **`WASP.3D`** now uses top-level **`BSPA`** partition at y=0 instead of one flat `LIST`. The opposite-side pair of DYNAMIC wheels is painted behind the body; the camera-side wheels are drawn afterward. Within the body, a second y=0 `BSPA` sorts the solid cockpit sidewall pieces, mirror supports and left/right leaf-spring detail around the main chassis and shell.
- An **x≈7.5 ft `BSPA`** sorts the nose, cockpit/chassis and rear shell based on view direction; an **`BSPN`** manages bonnet/radiator ordering and each near/far wheel pair's front/rear relative depth.
- **`FWHEEL.3D` and `RWHEEL.3D`** now use a y=0 `BSPA` to draw the far cover/hub first, then the black tire, then the near cover/hub. This avoids the old fixed-order two-face overlap when the camera changes side.
- Source-side colored polygon counts and wheel placements unchanged: **WASP=320**, **FWHEEL=114**, **RWHEEL=114** unique polygons, instantiated in scene as body + four wheels = **776** polygons viewed across 5 instances. 116-in wheelbase and 187-in overall length preserved. No extra mesh tessellation.
- The assembly script compiles through the repository's actual N3 compiler and reparses; it now explicitly verifies top-level flavor 8 (`BSPA`) for each object and tests parent DYNAMIC event ordering from both positive and negative Y view positions. The inspector reports structural diagnostic issues, but it is **not a substitute for in-game rendering tests**.

### Remaining draw-order limitations

This is **coarse component-level BSP** to fix the principal painter-order errors, not a polygon-level BSP splitting solution. Each Stage 2 primitive's internal triangles remain grouped in a `LIST`; individual back-facing or intersecting surfaces may still need proper per-polygon BSP visibility/culling and/or geometry cleanup based on new in-game screenshots. The CAD inspector's wireframes do not emulate the 1995 renderer. We cannot claim the blue/overlap issue is fully fixed until the user replaces all three compiled model files together and checks in ICR2.

**Technical references:** [Papyrus N3/3DO creation notes](https://www.icr2.net/tutorials/tools/3d_file_creation.pdf) on `LIST`, `BSPA`, `BSPN` and painter ordering; [ICR2 forum on when to use BSP sorting](https://www.icr2.net/forum/showthread.php?page=51&tid=1315); [ICR2 palette guide](https://skchow.com/indy/palette/).

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
