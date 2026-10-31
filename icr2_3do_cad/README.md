# v1.9 — Edit colors of existing polygons

In **Polygons / BSP**, select a polygon and edit **Base palette index (0–255)** or click **Palette…** to choose directly from `gamepal.pcx`. Click **Apply** to see the new color immediately. The new field edits existing and newly created polygons, including faces appended by Add Geometry and polygon splits.

For two-sided fins created through FACE2, **Also update opposite FACE2 side** is on by default. The paired face is found through the same immediate FACE2 record, not by finding any overlapping polygon. Turn the box off to assign different colors to the two sides.

Colors are original POLY color fields stored in the base 3DO, not modifications to a separate `ind96.3do` RECOLOR wrapper. When a car appearance is loaded, the inspector shows both the stored index and its effective RECOLOR-mapped index. Saving applies only changed POLY color bytes to the base 3DO, with undo/redo, validation, and backup behavior unchanged. Textured POLY [T] color is also editable but the MIP may cover it visually, depending on material behavior.

This release retains v1.8's creation, BSP, LIST, MIP, DYNAMIC, and disassembly features.

---

# ICR2 3DO CAD v1.8 — Add Geometry and Raw 3DO Inspector

Version 1.8 builds on v1.7. It adds a conservative create-polygon tool,
a triangular-fin shortcut, staged free vertices, and a searchable **read-only**
disassembly tab. The existing split, BSP, texture, wheel, helmet, and RECOLOR
features remain available.

## Creating a fin

1. Open `fixtures/roadcar.3do` or your working `indycar.3do`.
2. Select an engine-cover polygon in **Polygons / BSP**, then open **Add Geometry**.
   The selected polygon becomes the **Anchor POLY**. Or enter its body-relative
   offset manually and click **Find LIST links**.
3. Choose a LIST insertion **occurrence**. Each entry shows a LIST offset, the
   child containing the anchor, and the exact **parent pointer slot** to be
   repointed. For a first test, the first listed nearby occurrence is reasonable.
4. Choose **Paint BEFORE anchor child** or **Paint AFTER anchor child** to set
   the fixed back-to-front order within that LIST.
5. Under **Quick tool: upright triangular fin**, choose two existing numbered
   anchor vertices for the base and enter a positive height in raw Z units.
6. Click **Create fin using anchor edge**. The program appends one new apex
   vertex, two opposite-winding triangles, a `FACE2` node with an integer
   plane equation, and a replacement LIST. Confirm the insertion.
7. Rotate the camera with **BSP preview** enabled. If the fin paints in the
   wrong order, undo and choose another insertion point or BEFORE/AFTER.
8. Save a modified `.3do` and verify it inside ICR2.

The two-sided FACE2 creates alternative front/back surface branches; it does
not simply draw the same geometry twice. New geometry can be selected, moved,
and inspected using the existing vertex and polygon editors.

## Staging free vertices and creating arbitrary polygons

- **Stage a free vertex** enters XYZ (and optional U,V) and assigns a temporary
  identifier, such as `V1`. Drafts appear as aqua point labels in the viewport.
- Enter polygon vertices in winding order in **3. Create polygon**. Separate
  point tokens with semicolons. Examples:

  `@640; @580; V1`

  `(20000,0,7000); (10000,0,7000); (14000,0,12000)`

  `@640; (19000,2000,9000); V1; @580`

  For POLY [T], newly defined vertices require five numbers: `(x,y,z,u,v)`;
  referenced existing vertices must already have UV data. Untextured POLY
  is the default; set color and optional texture group as needed.
- You can select a **single-sided FACE** or a **two-sided FACE2**. For
  two-sided surfaces, the reverse polygon shares vertex locations and uses
  reversed winding.
- **Unconnected drafts are editor-only**, not saved to a 3DO. Draft points are
  appended to the binary only when referenced by a committed polygon.

## Binary writer / safety

The writer appends vertices (only if needed), POLY records, a FACE or FACE2
record, and a new LIST. It changes the 3DO header body size and **one
explicitly selected parent-pointer slot**. Existing geometry, tree records,
other LISTs, and unrelated LOD records retain their original bytes and
body-relative offsets. Only one path through an existing shared LIST is
repointed, rather than every reference to that LIST.

A complete `Model` reparse verifies that all newly inserted records are
reachable. The existing validated save, optional backup replacement,
undo/redo, and plane rebuild report are retained. The source 3DO is never
silently overwritten.

**IMPORTANT LIMITATION:** This version does **not** automatically create
near/far BSP partitions for new objects or split pre-existing geometry at
new partition planes. LIST ordering remains a fixed paint sequence. It may
work well for a simple exposed fin, but it does **not** guarantee correct
occlusion with overlapping body panels from every view. The program reports
this limitation and exposes exact insertion slots for experimentation.
Also, when choosing a LIST occurrence, you must verify that it belongs to
the desired LOD/rendering path. The software does not automatically
synchronize all LOD versions of a new fin.

## Raw 3DO tab

The **Raw 3DO** tab displays a searchable, read-only textual disassembly of
the *reachable* parsed 3DO records: VERTEX, POLY, FACE/BSP planes, LIST
children in back-to-front order, RES/SWITCH branches, MATERIAL, DYNAMIC,
and PMP references. All offsets are body-relative decimal offsets. Enter an
offset and choose **Jump to @offset**. After each topology edit, **Refresh**
updates the listing. This is intentionally not a raw binary hex editor; any
unknown/unreachable data is left uninterpreted.

## Validation

- Eight new backend regression tests pass on stock car files.
- A targeted suite of 37 tests passes across geometry, BSP, and prior split
  features.
- The desktop GUI smoke test passed (fin creation, draft staging,
  read-only disassembly, undo/redo, save-data round-trip).
- An exhaustive in-game ICR2 rendering test has **not** been performed.
- The complete legacy GUI unittest discovery was not completed because it
  stalled under the virtual display; do not interpret that as all tests passing.

## Running

Extract the ZIP and run `RUN_ME_WINDOWS.bat` with Python 3 installed.
Pillow and NumPy are optional for texture preview; they can be installed with
`py -3 -m pip install Pillow numpy`.

---

# ICR2 3DO CAD v1.7 — Split Between Existing Vertices

v1.7 adds a second polygon-splitting method for the case where the previous
edge-split operation has *already created* a vertex on an adjoining polygon.
This new operation uses **only existing vertex references**; it creates no
new vertices or UV coordinates.

## Using the no-new-vertices split

1. Open the geometry 3DO and choose **Polygons / BSP**.
2. Select a polygon with at least four vertices (including a neighboring
   polygon that gained vertices from the previous split).
3. In **Split between existing vertices (no new vertices)**, select
   **Vertex A** and **Vertex B**. The values correspond to the numbered
   polygon vertices displayed in the viewport and vertex table.
4. Choose two *nonadjacent* vertices. A **purple dashed diagonal** previews
   the proposed split. Concave polygons are supported if the diagonal lies
   inside the polygon; an invalid or crossing diagonal is rejected.
5. Click **Split using existing vertices** and confirm. The original polygon
   is replaced in the live hierarchy by an ordered two-child LIST; each
   child polygon retains its original vertex offsets, color, texture group,
   type and UV coordinates. No new vertex records are allocated.
6. Undo/redo work as one topology action. **Save edited copy…** writes a new
   3DO, retaining the existing parse validation and backup flow.

The older **Split selected polygon (adds vertices)** tool is still present
below the new tool and operates exactly as before. You can combine both in
sequence: insert a vertex into a polygon's edge (automatically extending
neighbors), then choose any two nonadjacent existing vertices in the updated
neighbor to divide it without adding more points.

## Binary implementation and limitations

Two POLY records and one LIST record are appended to the 3DO body. Only
actual parent pointer slots and the file's body-size field change in the
existing bytes; the original polygon is left intact but unreferenced.
Vertex records, FACE/BSP planes and SWITCH DISTANCE records are untouched.
This does **not** generate new local BSP planes; the two child faces continue
under their previous ancestor facing/partitioning planes. Altering one half
into a different orientation may require further BSP editing. Existing
polygon shading and texture interpolation can visually change where a
warped polygon is divided; compare with the target game's renderer.

Structural save/reopen testing does not prove in-game compatibility.
Test edited geometry on copies of the car models first.

---

# ICR2 3DO CAD v1.6 — Split Selected Polygon

v1.6 introduces the first **topology editing** operation in the Polygons / BSP
panel. It is intentionally conservative and preserves the existing BSP/LOD
tree rather than attempting to automatically rebuild it.

## Using Split selected polygon

1. Open a regular geometry 3DO, such as `fixtures/roadcar.3do` or the
   `ind96.3do` companion that resolves to `indycar.3do`.
2. Select the **Polygons / BSP** tab and select a polygon in the list or
   click it in the viewport. The existing 1-based vertex labels identify
   the ends of each edge. The panel scrolls if necessary.
3. Under **Split selected polygon**, choose **Edge A** and **Edge B**.
   Edge #i runs from polygon vertex #i to the next vertex, wrapping from
   the last vertex back to #1. Choose *different* edges.
4. Specify a fraction (strictly between `0` and `1`) for each edge. `0.5`
   means halfway. A cyan dashed line previews the proposed cut on the model.
5. Click **Split polygon (append + repoint)**, inspect the summary/warnings,
   and confirm. The two new polygons appear in the polygon list, with new
   vertex records available in the Vertices tab. **Undo** restores the
   original model and **Redo** reapplies the split.
6. Use **Save edited copy…** to write the extended `.3do` with the same
   existing backup-overwrite handling, parse validation, and warnings.

The same tool can split triangles or larger polygons. Both child polygons
inherit the original polygon type, palette color and texture group. New
vertex XYZ coordinates and, for textured polygons, U/V values are interpolated
and stored using the original integer field widths.

## Append-and-repoint output

Each operation appends two vertices, two new polygon records, and a two-child
`LIST` record to the end of the existing 3DO body. It repoints **every live
parent reference** from the original polygon to the new LIST. Any immediately
adjacent polygon with **the same original vertex references** along the cut
edges is replaced with an appended copy that includes a collinear vertex;
its parent references are repointed as well. The original records remain
unmodified and become unreachable from the model root. Header body size is
updated. Any preexisting valid offset remains unchanged.

The editor reloads and checks the newly assembled 3DO **before accepting the
split**. Existing FACE/BSP plane coefficients, SWITCH DISTANCE records,
external objects, polygon colors and material assignments stay unchanged.
The resulting LIST preserves the authored paint order of the two halves.

## Deliberate limits and safety warnings

- **No new FACE/BSP planes yet.** The two halves inherit their existing
  ancestors. Reshaping them so they are no longer approximately coplanar may
  require editing or rebuilding their local BSP tree by hand in a later version.
- **Other LODs are not automatically resculpted.** The chosen polygon is
  edited wherever it is referenced. Neighbor repairs occur only when two
  polygons actually share the same edge vertex *offsets*. Geometrically
  coincident edges with separate vertex records, including UV seams and some
  other LODs, generate a warning and are not silently joined.
- Texture mapping on newly split irregular polygons can differ slightly from
  the original because the preview triangulates polygon interiors.
- Parent 3DOs whose polygon vertex loop repeats its first vertex as a closing
  entry and other malformed/degenerate cases are rejected in this initial tool.
- All file writes and parsing have been validated against the supplied sample
  models. **Actual in-game ICR2 behavior after topology edits remains untested.**

**Validation:** 93 unit tests pass, including eight new topology-specific
checks, plus a desktop GUI integration test covering split, undo/redo, save,
and reopen. The check verifies that original bytes change only in the file-size
field and the actual old polygon/neighbor parent-pointer fields; new records
are appended rather than inserted into the original layout.

---

# ICR2 3DO CAD v1.5 — PMP helmet sprites

This update implements the missing helmet display using the actual uploaded
`helmet.3do`, `helmetp.3do`, and the 16 supplied `helm*.pmp` files. All are
bundled under `fixtures/` along with the existing IndyCar models and wheels.

## Why the helmet was previously invisible

The helmet files contain **eight PMP2 records**, chosen by a `BSP2` tree based
on the viewing direction. They have **no ordinary POLY geometry**. Each PMP2
record supplies a position, sprite size (4,800 raw game units), and a named
`.pmp` picture. The PMP pictures use a palette-indexed color-span format:

- Signature: `4C 38 AA AF`.
- Header contains the payload length and an auxiliary integer.
- Image data is a sequence of `(y, left_x, right_x, palette index)` 8-bit
  records; every record paints a horizontal span, and unpainted pixels remain
  transparent.
- The image terminates with `AF`. The helmet graphics are eight different
  directional views, not a rotating polygonal helmet mesh.

The editor now loads and decodes these transparent pictures using the bundled
`gamepal.pcx` and draws the one selected by the helmet's BSP tree. It does so
**inside the parent's existing DYNAMIC transform and painter-order traversal**.
PMP decoding is cached, and each external model remains read-only.

## Running and limitations

Open `fixtures/ind96.3do` (or `fixtures/indycar.3do` / `roadcar.3do`).
The editor finds the wheel files, `helmet.3do`, and the named PMP files within
`fixtures/` automatically. For your own carset, put helmet 3DO and PMP files in
the same folder, or select the external-object folder in the File menu.
The **Textures** checkbox also controls visibility of PMP sprites.

The Components tab can still edit the **parent** helmet's XYZ position and
Z/Y/X rotations. This does not modify `helmet.3do`, `helmetp.3do`, or PMP data.
There is no sprite-editing interface in this version. `helmetp.3do` is bundled
and parseable; the stock `indycar.3do` reference continues to use `helmet.3do`.

**Preview accuracy limitation:** The sprite is billboarded toward the viewer
and its rendered size is derived from the PMP2 scale and the occupied pixel
bounds. Exact Papyrus sprite scaling and pixel placement have not been
reverse-engineered or checked in game. BSP-selected directional images and
transparency are grounded in the supplied binary structure.

## Verification

- **85 automated tests** passed, including six new PMP tests using the actual
  helmet assets, with GUI verification.
- The v1.5 desktop preview shows all four wheels and one viewpoint-selected
  helmet sprite above the cockpit, with no unresolved external references.
- No geometry or external files are modified merely by displaying PMP sprites.

See `ui_preview_v15_helmet.png` for the new full-car preview.

---

# Earlier release notes (retained for reference)

# ICR2 3DO CAD v1.4 — real wheel loading fix

This release corrects external wheel loading using the supplied **real game files**:
`sfront.3do`, `srear.3do`, `fwheel.3do`, `rwheel.3do`, `wheel1.mip`, and
`wheel1f.mip`. It includes these files under `fixtures/` for immediate testing.

## Why v1.3 showed no wheels

The visible parent car places `sfront` twice and `srear` twice via DYNAMIC.
But these two tiny files are **not meshes**. Each is a 52-byte MATERIAL wrapper
with its root at body offset `0` and a **negative external 3DO pointer (-1)**:

- `sfront.3do` → MATERIAL `wheel1` → external `fwheel.3do`
- `srear.3do` → MATERIAL `wheel1` → external `rwheel.3do`

The v1.3 parser both rejected the negative external pointer and mistook a root
at offset zero for a NIL reference during preview traversal. The new parser
resolves named external pointers recursively at the correct parent DYNAMIC
placement, and inherits the `MATERIAL` texture name through the wrapper.

The actual `fwheel` and `rwheel` meshes also have a **variable-length** RES /
SWITCH DISTANCE root with **three** distance thresholds: `280000`, `113750`,
and `0`. The previous parser assumed four thresholds and read beyond the end
of the 3DO. This is now parsed without discarding the far/medium/near LODs.

## How to run

Open `ind96.3do`, `indycar.3do`, or `roadcar.3do` from `fixtures/`. The editor
will find all bundled wheels and `wheel1.mip` automatically. In your real
installation, put the six supplied wheel assets next to the base car 3DO or
choose **File → Choose external 3DO folder** and select the folder containing
`sfront`, `srear`, `fwheel`, `rwheel`. For textures, choose a MIP folder if
`wheel1.mip` is stored elsewhere. File matching is case-insensitive.

`wheel1f.mip` is included and decodes, but neither supplied wheel wrapper
references it. It is **not** automatically substituted for `wheel1.mip`.

Wheel geometry remains **read-only**. Editing wheel XYZ or Z/Y/X rotation in
the Components tab changes only DYNAMIC transform bytes in the parent car file.
The wheel 3DOs and MIP files are never rewritten.

The helmet remains unresolved if `helmet.3do` is absent; this does not affect
wheel loading. The remaining 3DO preview and BSP methods are still
approximations of the original game renderer.

## Verification

- All **79 automated tests** pass, including four regression tests for the
  original supplied wheel files.
- The GUI was run with `roadcar.3do` and with `ind96.3do`, rendering all four
  actual wheels. With `ind96`, the body uses `ind96.mip` and the wheels use
  `wheel1.mip`.
- No-edit 3DO bytes round-trip unchanged; the external assets remain intact.

See `ui_preview_v14_ind96_real_wheels.png` for the actual wheel preview.

---

# ICR2 3DO CAD v1.3 — External DYNAMIC submodels

This release adds preview and transform editing for referenced external `.3do` models.

## Wheels and helmet

The bundled `indycar.3do`, `roadcar.3do`, `irl.3do` and `panoz.3do`
contain 5 DYNAMIC placements that reference three external models:
`sfront.3do` (two front wheels), `srear.3do` (two rear wheels) and
`helmet.3do` (one helmet). These external meshes are **not** included,
because the originals were not supplied. Extract them as loose `.3do`
files from your ICR2 installation, place them alongside the base car
3DO, or choose **File → Choose external 3DO folder**.

External filename lookup is case-insensitive. The resolver searches the
parent model's folder first, then the chosen folder, then common adjacent
3DO/OBJ/CARS directories. Missing files are reported on the Components
tab; the car body still displays.

## Components tab

Select a DYNAMIC placement by body-relative offset in the list, or click
the visible referenced object in the viewport while the Components tab
is active. Adjust its **X/Y/Z in original integer units** and
**Z/Y/X rotations in degrees**. Apply the transform, reset the selected
placement, or undo/redo with the existing controls. Stock side-to-side
wheel placements use Z rotations of 0° and 180° (the stored signed
angle -2147483648 corresponds to -180°). The preview composes rotations
in Z → Y → X order; non-stock compound rotations remain a
best-effort representation until verified against the game.

The DYNAMIC transform is represented by six signed 32-bit words at
the selected record +4 to +24. Its negative external-file index at +28
and every other byte are retained unchanged. Saving modifies **only
the parent 3DO**, never the referenced wheel or helmet files.
The existing original-file `.bak` confirmation still applies.

External geometry is drawn at the corresponding DYNAMIC site in the
parent's LIST/BSP painter order, with child BSP tests evaluated in the
child's local coordinate system. Nested references are supported to
four levels, with cycle detection. Textured submodels can use their
own MATERIAL references and loose MIP files. The preview remains a
reverse-engineered approximation, not the original Papyrus rasterizer.

## Testing

The regression suite includes DYNAMIC reference decoding, signed-angle
rotation, parent-only byte patches, missing-file safety and read-only
external loading. A GUI smoke test constructs **synthetic test wheels**
in a temporary directory; the `ui_preview_v13_test_geometry.png` image
shows those test shapes, **not authentic game wheel models**.

Run `RUN_ME_WINDOWS.bat`, and use the Components tab after loading a
parent car model.

---

# ICR2 3DO CAD — Polygon, BSP, Vertex/UV, LOD and Texture Editor v1.2

A small Windows-friendly Python desktop program for editing existing binary Papyrus *IndyCar Racing II / CART Racing* `.3do` models. It uses Tkinter for the GUI. **Texture rendering requires Pillow and NumPy**; all existing non-texture editing features remain available without them. The MIP reader and rasterizer were implemented using the format described in `skchow03/icr2tools`.

**The key engineering feature is structure-preserving output**: it opens the original binary, edits referenced vertex coordinates **and optionally 16-bit UV coordinates**, supports explicit polygon-to-FACE/BSP plane recalculation/reversal, conditionally rebuilds other geometric plane equations, and leaves file size, record pointers, polygon colors, tree ordering, and unrelated fields untouched. Unchanged files save byte-for-byte identical.

## Start

Install Python 3.10 or later for Windows from python.org with Tcl/Tk support (included in the standard installer). Unzip this folder and double-click `RUN_ME_WINDOWS.bat`, or run:

```bat
py -3 icr2_3do_cad.py "C:\path\to\roadcar.3do"
```

On Linux, run `python3 icr2_3do_cad.py` with Tkinter available (`python3-tk` on some distributions).

Try the included `fixtures/roadcar.3do` first, or load your own `.3do` via File → Open.

## FIXED in v1.2 — rear-wing BSP2 front/back overdraw and paint order

This correction addresses body-relative **POLY offsets 7136, 7168, 7076, and 7108** in the bundled `roadcar.3do` and its same-layout `irl.3do`/`panoz.3do` variants. (These are **not** polygons at those offsets in `indycar.3do`.)

The four records are actually **two coincident pairs**:

| Endplate | Textured POLY [T] | Plain POLY |
|---|---:|---:|
| Negative-Y | 7136 | 7168 |
| Positive-Y | 7076 | 7108 |

In the original 3DO they are children of BSP2 nodes at 9960 and 10000 for the nearest LOD (and equivalent nodes at 12152/12192 and 13496/13536 in the other LODs). The old editor traversed **all four** binary BSP2 child slots, drawing both textured and plain copies of an endplate and sometimes drawing the intervening wing **after** the near-side endplate. This gave seemingly reversed occlusion. The binary stores the pointers in **A,D,C,B** order relative to N3 source BSP2 A,B,C,D, as documented by the community converters.

With BSP enabled, the corrected preview selects a single appropriate face for each endplate based on the camera's side of that BSP2 plane. It paints the far endplate, then the wing, then the near endplate. For example, at the tested close LOD:

- Looking from negative Y: 7108 (far plain) → wing → 7136 (near textured). Offsets 7076/7168 are hidden.
- Looking from positive Y: 7168 (far plain) → wing → 7076 (near textured). Offsets 7108/7136 are hidden.
- Between the endplates: both inward-facing plain sides (7108 and 7168) are present.

This behavior is checked at raw SWITCH distances 0, 250000, and 400000, in original and rebuilt BSP modes, on all three model files. The **Off (show all)** mode still deliberately traverses all faces for inspection; coplanar surfaces will overlap in that diagnostic mode.

**Important:** This is a reverse-engineered interpretation of BSP2 behavior from the binary relationships and known N3/ICR2 pointer order, **not** proof from live ICR2 renderer disassembly or direct in-game comparison. The editor changes only preview logic and does not edit, repair or rewrite the source BSP tree. A no-edit saved model is byte-identical.

The v1.2 package includes `test_v12_bsp2_wing.py` with dedicated face-selection and far/wing/near ordering checks. All **70 automated tests** pass in a virtual Tk display.

## NEW in v1.1 — Individual car `.3do` RECOLOR wrappers

The user-supplied `ind96.3do` is **not** an ordinary geometry 3DO. Its file header names the external `indycar` geometry and `ind96` MIP. The root is a **MATERIAL** flavor 4 whose child (at body-relative offset **0**) is **RECOLOR** flavor 14, containing **68** original-palette-slot → new-palette-index mappings. For example, original color 1 becomes palette color 49 and original color 7 becomes color 153. This pairing is established from the uploaded binary; other car variants may differ.

**How to use:**

1. Choose **File → Open 3DO** and select `ind96.3do` directly. The editor locates `indycar.3do` alongside the appearance file or in the included `fixtures` directory. If neither exists, it asks you to locate the referenced base geometry.
2. Alternatively, open `indycar.3do` and choose **File → Load individual car RECOLOR 3DO**, or the equivalent button on the Polygons / BSP tab. This preserves existing XYZ/UV/BSP edits. A mismatched geometry filename prompts you to load the referenced model or deliberately apply the appearance as a preview to the current geometry.
3. The editor displays the remapped palette colors of the base polygons, including the `Original → New` color values in the polygon list/inspector. The appearance's `ind96.mip` is located automatically (beside the wrapper, in your chosen MIP folder, beside the base geometry or in packaged fixtures) and applied to the base model's UV-textured polygons. Manual polygon/group MIP assignments still take precedence.
4. **File → Clear individual car RECOLOR preview** removes the mapping and associated default texture without changing the base model. Switch to another geometry with Open 3DO to clear the appearance automatically.

**Scope:** RECOLOR values and MIP references are currently **preview-only**. The editor continues to edit/save the geometry 3DO exactly as before. It does **not** rewrite `ind96.3do`, bake the recoloring into polygon records, modify `ind96.mip` or merge external geometry/appearance into a new model. This separation prevents inadvertently corrupting the original carset structure. Editing RECOLOR entries and saving the individual car 3DO could be added later.

`fixtures/ind96.3do` and `fixtures/ind96.mip` are included for a repeatable demonstration, together with `fixtures/indycar.3do`. The `car_appearance.py` module parses and checks wrappers separately from the geometry editor. Validation: **65 automated regression tests pass** under a virtual Tk desktop, including 11 new tests for this feature; the GUI was launched using the real user-supplied files. In-game rendering is still unverified.

## NEW in v1.0 — faster textured preview

The v0.9 renderer sampled UV textures at full canvas resolution and rebuilt a new
Tk image for every visible textured polygon on every redraw. This was especially
expensive when orbiting, panning, or zooming with a textured car filling the viewport.

**New options:** A **Texture detail** selector appears above the viewport and under
**View → Texture preview quality**:

- **Balanced (75%)** — new default: samples textures at 75% of display resolution
  and enlarges them with pixel-preserving nearest-neighbor interpolation.
- **Fast (50%)** — prioritizes response time for complex models and slower machines.
- **Full (100%)** — uses the original full-resolution per-pixel UV preview.

**Automatic interactive rendering:** During camera orbit, pan, zoom, or vertex
movement, texture sampling temporarily uses a faster resolution (40% for Fast and
Balanced, 55% for Full). On release, or after 180 ms without further input,
full *selected* detail is restored automatically. Mouse-motion events are combined
into at most one pending repaint per 16-ms interval, so a busy computer does not
queue an expensive render for every single mouse event.

**Tile caching:** On a stationary view, textured polygon images are cached and
reused when selecting another polygon or inspecting BSP information. Cached tiles
are invalidated by changes to projected coordinates, UVs, camera, palette,
texture, lighting or sampling quality. The cache is bounded to approximately
16 MiB and 96 entries. No texture pixels are saved to the `.3do` file.

**Painter-order preservation:** Faster previews still traverse the original
BSP/LOD selection and LIST order, with no global depth sort. Only texture
sampling density changes. Polygon click targets, outlines, vertex positions,
UV coordinate values, and saved 3DO contents remain full precision.

**Benchmarks (local Linux virtual desktop, `roadcar.3do` + `ind96.mip`, 1400×940
window, 5× zoom):** v0.9's median draw time was approximately **81–88 ms**
(orthographic/perspective). v1.0 was approximately **37–39 ms** at rest in
Balanced mode and **29–31 ms** during motion. A redraw of an unchanged view
with cached tiles took approximately **14 ms** at 2× zoom. These measurements
include Tk overhead and depend on hardware; they are not guaranteed FPS figures.

**Validation:** 54 automated tests pass, including reduced-resolution texture
sampling, caching, UV/projection invalidation, idle refinement and unchanged
3DO bytes. A GUI smoke test loaded and displayed the real `ind96.mip`.

## FIXED in v0.9 — real ICR2 MIP compatibility

The v0.8 decoder could reject genuine `.MIP` files even though the file was valid. For example, `ind96.mip` begins with a size field of **28,846**, while its physical file is **28,850 bytes**. The size field excludes the initial four-byte length dword. The synthetic v0.8 test texture counted all bytes. The decoder now accepts **both observed conventions**, with strict size/bounds checks. (We do not discard the size check.)

A second fix affects **odd-sized textures**: for height 165, the seven mip levels must be **165 → 83 → 42 → 21 → 11 → 6 → 3**. The decoder now halves each *preceding* dimension with rounding up, instead of dividing the original dimension by powers of two. The latter incorrectly read bottom rows on later mip levels.

The user-supplied `fixtures/ind96.mip` is included as a real-world regression fixture. The MIP reconstructs as a 128×165 indexed-color image using the bundled `gamepal.pcx`; `ind96_texture_preview.png` is an example of the decoded pixels. For models without `MATERIAL` references, use **Polygons / BSP → Assign polygon MIP** or **Assign group MIP** as in v0.8.

**Validation:** 48 automated tests pass, including the real MIP, both size-header conventions, all seven mip levels, and GUI texture assignment with no change to the underlying 3DO. The tests validate editor behavior; they do not establish exact ICR2 scanline interpolation.

## NEW in v0.8 — MIP textures with per-vertex UV mapping

**Install the two optional texture preview dependencies** (once, before launching):

```bat
py -3 -m pip install Pillow numpy
```

Without those packages, 3DO editing and solid-color preview still work. `MIP` artwork simply cannot be displayed.

**What it does:**

- Read loose Papyrus `.MIP` files using the integer header and per-level offsets in [`icr2tools/icr2_core/mip/mips.py`](https://github.com/skchow03/icr2tools/blob/main/icr2_core/mip/mips.py). Currently displays the **largest** mip level. Pixels are indexed 8-bit colors and use the currently selected PCX palette (`gamepal.pcx` by default).
- Apply UV values from each `POLY [T]` vertex. UVs are treated as **raw texel coordinates** (not normalized 0–1). The default is **clamp** outside the MIP; View → Repeat UVs changes that to wrapping. Mapping assumptions may differ from special Papyrus materials and should be compared in-game.
- Render concave/irregular and somewhat nonplanar polygons by triangulating their projected outlines. In perspective mode, interpolate UVs using reciprocal camera depth within triangles (perspective correction). The original ICR2 rasterizer's exact interpolation across nonplanar n-gons is **not established**, so this is a usable approximation, not byte/pixel-perfect emulation.
- Keep painter-order `LIST` rendering and the selected BSP/LOD visibility unchanged. Textured surfaces are composited in that order; no Z-buffer silently reorders them.
- Unlit preview is still the startup default. Enabling Lighting optionally applies the same simple directional shading to textured and solid-color polygons.
- **Automatic MIP lookup:** For binary `MATERIAL` flavor 4 records, the editor finds associated descendant `POLY [T]` polygons and resolves named texture resources from the 3DO resource table. Searches beside the opened 3DO and in `textures`/`mip` subfolders, or in File → **Choose MIP texture folder**. Loose `.MIP` files are required.
- **Manual assignment:** Sample `roadcar.3do` and `indycar.3do` have textured polygons but **no `MATERIAL` nodes**, so no texture filename is available in the 3DO itself. Select a textured polygon, then click **Assign polygon MIP** or **Assign group MIP** in the Polygons / BSP panel. The group option applies the MIP to all textured polygons with the same group number. File menu alternatives are also provided. Click **Clear** to remove the selected polygon/group override.
- Use **View → Textured polygons** (or the toolbar **Textures** checkbox) to switch textures on/off. Without an assigned/resolved MIP, polygons remain solid palette color. The polygon inspector displays the texture name, size, or why no MIP is found.

**Important scope:** Manual texture assignments affect the preview **only** and are not written to the model, persisted between application launches, or included in the 3DO binary. Existing UV edits still save in the original format. The editor does not modify MIP files and does not unpack carset/track `.DAT` archives; extract the needed MIPs first. `PMP` textures, palettes embedded inside DAT archives, filtering, alpha effects and the original Papyrus rasterizer's scanline details are not yet supported.

`fixtures/uv-checker-demo.mip` is an artificial 128×64 UV checker for experimenting with the mapping. It is **not a game texture**. The v0.8 screenshot shows this checker assigned to car texture group 16; actual livery textures must be supplied separately.

**Testing:** 45 automated tests passed under an X11 virtual desktop: 34 previous tests and 11 new MIP/texture tests covering MIP levels, invalid offsets, concave/nonplanar polygons, UV interpolation, perspective correction, manual group assignment, GUI toggle, and preservation of 3DO output. The desktop preview was also tested. These are tool-level tests, **not game-engine rendering tests**.

## NEW in v0.7 — Projection, LIST painter order, unlit default and game palette

**Projection toolbar and View menu:** select **Orthographic** (default) or
**Perspective (depth)**. The perspective camera uses a ~55° vertical field of
view, scales distant geometry smaller, and clips polygons at the camera's near
plane. The orbit camera and middle-drag panning work in both modes. Mouse-wheel
zoom changes the viewing scale in orthographic view and dollies the virtual
camera in perspective view. BSP-side evaluation uses the actual perspective
camera position; orthographic still uses a distant view representative. Both
views preserve raw model XYZ coordinates. **The SWITCH DISTANCE LOD input is
separate from camera movement** and does not automatically follow mouse zoom.

**LIST order:** `LIST` children are traversed in the order stored in the `.3do`
file (the author's expected back-to-front painter order), regardless of BSP
mode or projection. The v0.6 renderer incorrectly globally depth-sorted
polygons when BSP was switched off, overriding LIST order. This global sort
has been removed. With BSP enabled, the existing approximate BSP traversal
can reorder entire BSP branches, but each LIST's ordered children are drawn
in their original sequence. If authored LIST order is wrong, the editor
intentionally displays its overdraw rather than silently fixing it.

**Lighting:** View → **Lighting**, also on the main viewport toolbar, can be
turned on for directional shading. It is **OFF by default**: when off, polygon
fill RGB is the indexed palette color without brightness modification. The
on-screen vertex/selection/edge overlays retain diagnostic UI colors.

**Game palette:** the supplied `gamepal.pcx` is included directly in the ZIP
and automatically loaded on startup, extracting all 256 RGB entries from its
VGA palette trailer. This replaces approximate CAD colors as the default.
You may load another palette from File → Open 256-color PCX palette, restore
**Use bundled gamepal.pcx (default)**, or disable the palette to return to
synthetic CAD colors. The PCX provides the palette for both indexed polygon colors and the MIP textures. The PCX image artwork itself is not drawn.

**Testing:** Added automated checks of indexed palette values, unlit startup,
perspective depth scaling vs orthographic, unchanged underlying 3DO bytes,
LIST order through both the parser and the on-screen painter, and both
projection modes. In-game parity remains unverified.

## Previous v0.6 correction — FACE2 front/back visibility

The v0.5 preview incorrectly rendered **both descendants of every `FACE2` plane**, even though Papyrus `FACE2 (plane), front, back` chooses a different subtree depending on the camera side of the plane. This produced apparently double-sided polygons, including **POLY at body offset 5540** in `roadcar.3do`. The v0.7 preview selects the positive-side pointer at record offset `+24` or the negative-side pointer at `+28`, using **original or edited A/B/C/D coefficients** according to BSP preview mode. (This is view-side traversal and does not change the actual 3DO tree or polygon pointer order.)

**Verification on supplied `roadcar.3do`:** At SWITCH DISTANCE 0, 250,000, and 350,000, polygon 5540 is shown from test camera `(0, +300000, +50000)` and hidden from `(0, -300000, +50000)` in Original BSP mode. It remains displayed from both in **BSP Off** mode as intended. Also checked `indycar.3do`, `irl.3do`, and `panoz.3do`. Note that some polygons really are two-sided by virtue of belonging to different selected front/back branches; the editor uses the 3DO hierarchy to determine that rather than applying arbitrary polygon-winding culling.

In v0.5, a selected polygon retained a dashed yellow inspector outline even when it was *actually hidden*. v0.7 hides that ghost overlay by default. You can enable **Show ghost outline when BSP-hidden** in the Polygons / BSP tab (or the corresponding View menu item) if you want to locate an otherwise invisible surface for editing. Numbered vertices also follow this option. This change affects only the preview, not saved geometry or planes.

## Previously added in v0.5 — Backup overwrite, correct BSP preview refresh, reversed +Y view

1. **Existing `.3do.bak` files can now be replaced.** When you save over the currently opened source 3DO, the editor asks to overwrite that source and, if its `.3do.bak` already exists, asks separately whether to replace the backup (default **No**). Approving creates a new backup containing the file's **current on-disk bytes**, not an earlier in-memory snapshot. Declining the backup overwrite cancels saving and leaves both source and backup unchanged. A new 3DO is parsed and validated as a temporary file **before** either existing file is replaced; replacements use same-directory temporary files and atomic renames.
2. **BSP-only edits now update the `Rebuilt planes` preview.** v0.4 recomputed preview planes only when vertex XYZ had been edited, accidentally ignoring `Flip plane orientation`, `Auto calculate`, or `Use P1/P2/P3` if they were the only edits. This is fixed. The **Original 3DO planes** mode deliberately continues to show unmodified source equations for comparison.
3. **Preview paint order now honors the selected BSP tree traversal** for Original/Rebuilt BSP modes, instead of applying a final depth sort that masked changes to sorting-only BSP nodes. The **Off** mode still depth-sorts geometry. The traversal remains approximate, not a pixel-equivalent ICR2 renderer.
4. **Selected BSP direction indicator.** In the polygon inspector, the preview displays the selected FACE/BSP offset, the plane source (original/effective/edited), the virtual camera's front/back relationship, and a magenta **N+** normal arrow. The arrow is drawn at the polygon centroid for readability: it indicates normal *direction*, **not** the actual location of a plane that may not be coplanar with the polygon. End-on normals use a direction marker.
5. **+Y direction is reversed visually.** The viewport now shows positive Y pointing the opposite screen direction from v0.4, including its axis arrow and vertex dragging. **Raw 3DO XYZ values are not negated or modified.** Only the preview/camera basis has changed.

## Polygon editor — Polygon numbering and noncoplanar plane edits (v0.4 retained)

Choose the **Polygons / BSP** tab on the right, or press **P** while the 3D viewport has keyboard focus. Press **V** to return to Vertices.

1. **Select a polygon** by left-clicking its visible surface in the 3D preview or by selecting its row in the complete polygon list. The rows show body-relative `POLY` offset, polygon type, unique vertex count, and color. The **List only polygons in active LOD/BSP preview** checkbox offers a filtered list. If a selected polygon is hidden by LOD/BSP, no selection outline is drawn by default. You can enable a **dashed ghost outline** to locate/edit an otherwise invisible surface; this inspector overlay is **not** a claim the game would display it.
2. **Inspect vertices** in their binary-record order: each vertex's body offset, signed X/Y/Z and raw 16-bit unsigned U/V if textured. Double-click a listed vertex to open its original vertex-editing tab.
   - **New:** The selected polygon has numbered markers `#1`, `#2`, etc. directly over its vertices in the viewport, matching the **#** column of the ordered vertex list. Repeated refs are labelled `#1/#5`, for example. Turn these labels off with the checkbox in the polygon tab or **View → Number selected polygon vertices**. Only the selected polygon is numbered, avoiding clutter.
3. **Choose the target FACE/BSP plane** using the dropdown. There is *not* necessarily one plane per polygon. It shows ancestor planes in the binary tree, prioritizing unique local surface matches and marking coplanar or unrelated partition relationships. The source equation and the current would-be-saved equation appear below. No matching ancestor => the editor cannot invent a new FACE/BSP node.
4. **Auto calculate:** construct a new plane from the polygon's largest noncollinear triangle. Preserve the plane's existing facing direction and roughly preserve normal coefficient scale. Uses the chosen target plane record only. **Explicit automatic calculation is allowed for approximately planar/nonplanar polygons**; the inspector displays the maximum deviation of the other vertices.
5. **Use P1/P2/P3:** choose **three distinct, noncollinear vertices of this polygon** from ordered dropdowns. Their order sets the plane's normal by a cross product. **The remaining polygon vertices do NOT need to be coplanar**. The chosen plane is written even when a large n-gon is slightly warped. Collinear triplets, zero normals and unrepresentable integer coefficients remain invalid.
6. **Flip plane orientation:** negate all four plane coefficients **A, B, C and D**, reversing the normal and the relevant BSP half-space facing. This **does not reverse the POLY vertex-pointer winding order**, which is a different operation and is not yet available. Use the button again to restore orientation.
7. **Clear override:** return the chosen plane to the prior conservative auto-update behavior. All explicit plane actions support **Ctrl+Z / Ctrl+Y**, and explicit plane edits count as unsaved changes even if no XYZ coordinate changed.

A manual override updates the chosen plane record, not its pointers, descendant polygons, or BSP hierarchy. A **noncoplanar ancestor partition plane** can be overridden after a conspicuous warning, but the resulting rendering may be incorrect or crash the game. Do not apply a polygon's normal to an unrelated BSP partition casually.

The **BSP preview → Rebuilt planes** mode automatically activates after a plane edit so the changed plane can be inspected. The inspector reports the **maximum perpendicular distance** between the selected BSP plane and any polygon vertex, both in raw units and as a percentage of the polygon's bounding-box diagonal. This is **diagnostic, not a hard limit**. A saved file with an explicitly noncoplanar plane receives a warning in the rebuild report. The preview can still fall back if a selected triplet becomes collinear or the plane becomes unrepresentable, and saving is blocked until the invalid edit is fixed.

## Existing vertex and preview controls

- **Left click** a visible vertex dot to select it, or select by vertex's body-relative offset in the right-hand list. The same vertex may be shared by several polygons.
- **Left drag** a selected vertex to move it along the selected **X, Y, or Z** axis. The movement is snapped by **Nudge / drag step** (default 500 raw units).
- **X/Y/Z boxes → Apply coordinates** to enter precise signed 32-bit integer coordinates; or use **− Step / + Step**.
- For a vertex referenced by a **POLY [T]**, the **U/V boxes** display its original unsigned 16-bit texture coordinates (raw values). Edit U/V and choose **Apply texture UV** to save texture mapping changes independently from geometry. Untextured vertices show blank UV boxes. UV changes support undo/redo.
- **Right drag** to orbit; **middle drag** to pan; **mouse wheel** to zoom; **F / double click** to frame the whole model.
- **Ctrl+Z / Ctrl+Y** for undo / redo of XYZ, UV and explicit plane edits.
- **LOD: SWITCH DISTANCE** selects the branch appropriate for the **virtual distance** entered into the toolbar. The slider and numeric input use raw 3DO units. Choose **All branches** to show the combined LOD geometry (which can overlap in the preview). Zooming the orthographic camera does not alter the virtual distance.
- **BSP preview:** **Off** shows all polygons within the chosen LOD; **Original 3DO planes** uses the stored plane coefficients to perform half-space visibility testing; **Rebuilt planes** previews the coefficients that would be saved after editing, while retaining unmatched planes. The viewer hides back-facing `FACE` subtrees and the designated one-sided `BSPF` child; `FACE2` selects a distinct front-side or back-side subtree (a surface can still be intentionally visible from both sides if referenced on both). `BSPA`/`BSPN` are treated as draw-order nodes. `BSP2` uses a conservative approximate traversal.
- The preview displays the number of visible polygons, evaluated plane nodes and the active SWITCH branch pointer.
- **Bundled `gamepal.pcx` is used automatically by default.** File → Open 256-color PCX palette can select a different palette. You can also restore the bundled palette or remove it. MIP texture sampling is supported in v0.8 for loose `.mip` files. PMP rendering remains unsupported.
- **View → Plane rebuild report** (also F4) reports which plane associations can be rebuilt and any conflicts after editing.
- **Save edited copy…** writes a new `.3do` by default, validating it before replacing a target. When overwriting the source, it creates or (with permission) overwrites the `.3do.bak` backup using the original on-disk bytes.

### Important: geometry versus BSP partition planes

The original binary records hold plane equations `Ax + By + Cz + D = 0`:

- `A`, `B`, `C`: signed 32-bit integers at record-relative `+4,+8,+12`;
- `D`: signed 64-bit integer at `+16`;
- records: `FACE`, `FACE2`, `BSPF`, `BSPA`, `BSP2`, `BSPN`.

It is **unsafe to assume that every BSP plane corresponds to a visible polygon**. Some are spatial partitioning planes. For unmatched planes not explicitly overridden (same conservative rebuild algorithm retained from v0.2):

1. At load, candidate polygons are matched against each **original** plane equation, requiring all the polygon vertices to be within 0.5 raw units of that plane.
2. The matching polygon must be a descendant of the plane's node in the *original binary tree*. For a unique nearest local candidate, the editor can reconstruct `A,B,C,D` if its vertices change. For multiple closest candidates, it can do so only when all locally coincident polygons remain coplanar.
3. New normals have the same orientation sign and approximate coefficient magnitude as the original, and `D` is recalculated from a real vertex. Signed integer bounds are checked.
4. If a quad becomes nonplanar, or an association is missing/ambiguous, **the original plane is preserved and a warning appears**. The vertex modification can still be saved after the user accepts the warning.

The strict 1-unit coplanarity test above **only applies to implicit, safety-first rebuilding when moving vertices**. Deliberate **Auto calculate** / **Use P1/P2/P3** overrides no longer enforce this tolerance.

Therefore, **the plane reconstruction is intentionally partial**, not a proven full BSP rebuilder. Older modified car files can contain stale BSP plane equations that no longer match their polygons even before editing. No automatic fix is assumed for these.

### Current limitations

- Edits existing, referenced XYZ, UV values and selected existing FACE/BSP plane equations only. No creation/removal of vertices, polygons, nodes, texture images, or LOD levels. The actual ordered polygon-vertex pointer list cannot yet be reordered.
- 3D view is a **diagnostic CAD preview**, not the exact ICR2 rasterizer. The LOD branch calculation is based on `SWITCH DISTANCE` records; BSP culling approximates one-sided FACE/BSPF visibility from a virtual viewpoint and attempts draw ordering but does not reproduce every special-case of the game's renderer. With BSP preview on, the painter respects the parser's approximate BSP traversal order. In all modes, LIST children preserve their explicit back-to-front order; no global depth sort is used. No exact Papyrus framebuffer/emulation is claimed.
- The car 3DO examples expose **four stored threshold/pointer slots**, including a 0-distance fallback. Some community analysis describes three effective LODs rather than four; this prototype exposes and evaluates all non-null recorded branches. Verify stage boundaries in-game before assuming the final slot is always active.
- The viewer supports UV texture sampling from loose MIPs, but not PMP textures, animation, or exact game-engine rasterization. UV values are presented as **raw integers**, not normalized texture ratios.
- General external `DYNAMIC` models are not loaded into the preview. An individual-car `MATERIAL → RECOLOR` wrapper is now handled specially in v1.1 by opening its referenced base car model.
- Model coordinates are **raw 3DO integers** (not automatically converted to feet/meters).
- This version preserves all existing BSP/FACE hierarchy and will not repair an incorrectly ordered or fundamentally incompatible car model.
- The tool does not modify game executables, carset DAT archives, or the `indycar.3do`/`roadcar.3do` loading expectations.

**Always back up the original and test modified car files in the DOS, Windy or Rendition game version you target.** A file that structurally parses may still render incorrectly or crash in-game, particularly if geometry no longer agrees with old BSP partitioning.

## Format reference

Parsing based on the published reverse-engineered format in:

- [skchow03/3do23d](https://github.com/skchow03/3do23d), particularly `_3do_v3_icr2.py`, `flavors_icr2.py`, and `plane.py`.

In that format, the binary begins with five signed 32-bit header values (`body size`, `root offset`, `MIP count`, `PMP count`, `3DO dependency count`), then 8-byte resource names. Flavor offsets and vertex references are **body-relative**, where the body begins after the resource names. Polygon records store pointers to shared vertex records. This application does not repack the tree when saving.

## Source files

- `icr2_3do_cad.py` — Tkinter UI, orthographic/perspective previews, MIP assignments and edit controls.
- `car_appearance.py` — individual car MATERIAL→RECOLOR wrapper reader and referenced geometry lookup.
- `three_do.py` — bounded 3DO parser, MATERIAL-to-polygon mapping, plane matcher, patch writer.
- `texture_preview.py` — MIP level decoder and perspective-correct/orthographic triangulated indexed UV sampler.
- `test_v08_texture.py`, `test_v08_texture_gui.py` — MIP/raster/GUI regressions.
- `test_three_do.py` — core parser/rebuild regression tests.
- `test_preview_uv.py` — UV binary patch, SWITCH DISTANCE selection, and BSP preview tests.
- `test_polygon_plane.py` — explicit plane rebuild, source-normal reversal, ordered manual triplets, noncoplanar save/reload, safety validation.
- `test_poly_vertex_labels.py` — preview label ordering, duplicated vertex references, canvas label rendering.
- `test_v06_face2.py` — confirms offset 5540 front/back visibility on real car 3DOs, isolated FACE2 child traversal, and flipped-plane preview.
- `test_v05_regressions.py` — tests plane-only preview flips, manual plane preview, display-only Y reversal, repeated backup replacements, validation-before-overwrite.
- `smoke_v08.py` — desktop GUI texture smoke test with a generated demo checker (requires a display).
- `fixtures/` — copies of the six 3DO files supplied for testing; you can delete these after validating your installation.
- `ui_preview_v08.png` — screenshot of the v0.8 textured preview with artificial checker MIP.
- `ui_preview_v09.png` — screenshot using the supplied real `ind96.mip`.
- `ind96_texture_preview.png` — game-palette preview of decoded 128×165 MIP artwork.

To run the regression tests:

```bat
py -3 -m unittest discover -p "test*.py"
```

## Development status

v0.8 adds MIP texture previews using UV triangulation and preserves the v0.7 corrections to FACE2 child selection and hides BSP-hidden selection highlights by default. v0.5 added replaceable backups, a corrected Rebuilt BSP preview for standalone plane edits, approximate BSP tree drawing order, a selected-plane normal indicator, and flipped preview +Y. The v0.4 polygon picker, noncoplanar plane edits, vertex numbering, UV editing and undo/redo remain in place. **48 automated tests pass**; the desktop GUI and the overwrite-existing-backup flow were exercised against the supplied `roadcar.3do` fixture. **In-game rendering compatibility is not verified.** Test on your target ICR2/CART version.

## Visibility references and evidence

The model parser and coordinate fields follow the [3do23d source](https://github.com/skchow03/3do23d) (`_3do_v3_icr2.py`, `flavors_icr2.py`). The public [ICR2 3D file notes](https://www.icr2.net/tutorials/tools/3d_file_creation.pdf) describe `SWITCH DISTANCE` as selecting low/medium/high model branches, and ICR2 community reports distinguish one-sided `FACE`/`BSPF` geometry from `BSPA`/`BSPN` ordering. The simulator's exact `BSP2` semantics, projected-camera conventions, raster ordering, and some 0-threshold LOD details remain unverified; the preview is deliberately labeled accordingly.
