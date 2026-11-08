# 1911 Marmon Wasp — texture-first ICR2 low-poly revision

**Purpose:** retain only the large silhouette and necessary 3D features. This is an **approximate** Ray Harroun 1911 Marmon Wasp #32 body blockout, not a measured reconstruction. It revises the earlier 444-polygon version, preserving the prior Git revision. The model does not yet include a body texture or the four wheel models.

## Geometry budget

- **120 polygons, 12 editable components** including four removable, open-ended wheel-center markers (32 polygons). No modeled tires, spokes, axle beams, driver, or steering mechanism.
- Bonnet: 3 rectangular four-point section rings (18 triangles/caps).
- Rear pointed boat-tail: 3 four-point rings (18 triangles/caps). **No vertical fin**; the "Wasp" tail is pointed in plan view.
- Radiator: one plain dark front piece; any grille mesh pattern belongs on a texture.
- Cockpit: flat dark recessed floor and two simple side sills. Open cockpit is a gap between bonnet and tail, not a boolean-cut hole.
- Single rear-view mirror and a simple mast (important silhouette feature). Reflective glass finish is a later texture detail.
- No surface-detail polygons for hood louvres, straps, panel seams, number 32, seat stitching, grille slats, or rear trim.

## Coordinates

- x increases from the front radiator toward the pointed rear; y is lateral; z is vertical.
- Recipe dimensions in **feet** (6000 raw Papyrus units per foot).
- Wheel centers front **x=1.4 ft**, rear **x=11.066667 ft**, wheelbase **116 in** (documented); center height ~1.4167 ft derives from **34-inch tire outer diameter** (documented).
- Front track placeholder centers **y=±2.90 ft**, rear **y=±2.80 ft**, and all body cross-sections are *illustrative estimates*. They are not authoritative measurements of track width or silhouette.
- The four wheel placeholders are separately selectable, removable, capless small cuboids; replace with separately built 3DO wheel objects at these center coordinates.
- No in-game validation; Stage 2 emits LIST groups, not view-dependent BSP or LOD.

## Suggested later texture pass

Paint **#32**, the yellow/black paint transitions, bonnet straps, simulated hood vents and radiator mesh using game-compatible MIP textures and UV mapping. No texture files are currently claimed or referenced by this recipe; solid colors remain valid when no textures are supplied.

## Common palette verified

Colors below come from repository `icr2_3do_cad/gamepal.pcx` (SHA `8784dc6278cb7c057cd717c7b786301a8aa8890a`), matching the shared `sunny.pcx` common-color range in [the ICR2 palette guide](https://skchow.com/indy/palette/):

| index | RGB | assigned to |
| --- | --- | --- |
| 158 | (255,223,35) | bonnet and cockpit sills |
| 159 | (235,203,0) | yellow boat-tail |
| 48 | (31,31,31) | radiator and mirror mast |
| 49 | (19,19,19) | cockpit floor |
| 40 | (167,167,167) | mirror housing and removable wheel markers |

## Reference material

- [HVA / Indianapolis Motor Speedway Museum technical sheet](https://s07.static-shell.com/content/dam/royaldutchshell/documents/sema/1911-marmon-wasp.pdf) (116-inch wheelbase, single-seat layout)
- [Hagerty Drivers Foundation vehicle entry](https://www.driversfoundation.org/registry/1911-marmon-wasp) (visual and historic descriptions)
- [Library of Congress HAER IN-115](https://loc.gov/pictures/item/in0548/) (measured drawing resource, not yet digitized into this silhouette)

Before finalizing for ICR2, check the side/top wireframes, individual component visibility, BSP draw order, backface handling and in-game LOD.
