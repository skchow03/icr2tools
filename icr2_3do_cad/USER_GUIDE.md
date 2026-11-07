# ICR2 3DO CAD — User Guide

The supported ICR2 3DO CAD editor uses PySide6 and OpenGL 3.3 to inspect and edit Papyrus .3D source and preview .3DO models. Changes are not written to game assets unless you explicitly export a new file.

## Windows setup

Install Python 3.10+ with a working NVIDIA/AMD/Intel OpenGL driver. From the
repository root:

~~~powershell
python -m pip install -r icr2_3do_cad/requirements.txt
python icr2_3do_cad/icr2_3do_cad.py "C:\path\to\RENO.3D" --benchmark --report cad_reno.json
~~~

Or from the icr2_3do_cad folder:

~~~powershell
python -m pip install -r requirements.txt
python icr2_3do_cad.py "C:\path\to\RENO.3D" --benchmark --report cad_reno.json
~~~

The optional --benchmark switch requests continuous redraws (~60 Hz)
and reports **actual presented frames per second** through Qt's
frameSwapped signal. VSync may cap this near the display's refresh rate.
The optional --report path writes aggregate timings on close, omitting
full paths, geometry coordinates and model source. Run once with RENO and
once with a building or fixtures/roadcar.3do.

## XYZ orientation and extended axis guides

By default, the viewport displays **X red**, **Y green** and **Z blue**
with two complementary tools:

1. The **bottom-left XYZ orientation gizmo** is fixed in the viewport,
   but rotates with the camera. It tells you which way positive XYZ points
   even if the object origin is off-screen. An axis pointing directly toward
   or away from the camera appears end-on as a dot instead of vanishing.
2. The **extended XYZ guides** show axis-aligned lines through your current
   **camera target**. Positive directions are brighter solid lines and
   negative directions fainter dashed lines. The guide positions follow
   the camera's view focus so you are not forced to find an object's actual
   world origin. These are *orientation guides*, not claims that the camera
   target equals raw Papyrus (0,0,0).

For exact positioning, open **View → Display Settings** and choose **Axis
guide anchor**: `View focus` (default), `Model bounding-box center`, or
`Raw Papyrus XYZ origin (0,0,0)`. The model center and raw origin may
be outside your current framing; the gizmo continues to indicate direction.

Use **View → Display Options → Extended XYZ axis guides** and **Corner XYZ
orientation gizmo** to show/hide each one; these switches are also available
in Display Settings. Visibility and anchoring preferences survive restarts.
Both are mouse-transparent Qt overlays and never appear in saved .3D/.3DO
geometry, selection or texture rendering; toggling them does not recompile
any model.

## Direct vertex moving in the viewport

1. Open a model and ensure **.3D Source** is ready and valid. Set the
   **Pick** selector above the viewport to **Vertices**.
2. Click the vertex to select it. Its N3 declaration is highlighted
   green, and its selected marker appears in the viewport.
3. Enable **Move vertex** beside the Pick selector (off by default).
   Three world-axis handles appear: **red X, green Y and blue Z**.
   Click the *shaft or arrowhead* of the desired axis and drag.
   The camera will not orbit during a handle drag.
4. The live marker and readout show the proposed **raw Papyrus XYZ**
   and dashed connected polygon edges while the original compiled mesh remains stable. **Release** the
   mouse to apply the new coordinate to the original N3 source and
   start an ordinary full-mesh rebuild. Only the selected axis changes.
   To cancel mid-drag, press **Esc**. Hold **Shift during a drag**
   to move 10× more slowly.
5. For coarse/fine integer steps, set **View → Display Settings →
   Vertex move snap step** to 1, 10, 100 or 1000 raw units.
   Use Source Undo/Ctrl+Z to undo a completed drag. Nothing is saved
   until Save .3D or Export Compiled 3DO is explicitly invoked.

The gizmo derives its directions from the **same projection and camera**
as the GPU, including perspective and orthographic views. An exactly
end-on axis has no meaningful screen drag direction and is not shown:
rotate the camera or use the other view. The arrows maintain a readable
screen size while zooming; dragging does not move the camera.

A source vertex may use integer Papyrus values or scaled fractional
values; the move operation converts into the proper authored units
using ICR2_COORD_SCALE (or the compiler's inferred fractional scale).
This is checked against the currently compiled vertex before anything
changes. **U/V texture coordinates, labels, comments, material data and
all other vertices are preserved** unless the separate **Symmetrical
vertex editing** mode was enabled. Then the existing mirror-matching
and multiple-candidate confirmation run as part of the same undoable
edit. All polygons sharing a named vertex respond when the mesh is
recompiled.

The gizmo edits only **root-model named vertex declarations** with
valid compilation/source mappings. It does not edit anonymous inline
coordinates or external DYNAMIC children. It does not rebuild original
BSP plane coefficient data, and complex geometry can still need manual
FACE/BSP and winding checks. While dragging, the preview is a
screen-space point/axis overlay; the real triangles update only after
release and successful recompilation. Invalid or pending text disables
direct moving rather than allowing the editor to edit stale offsets.

## Symmetry editing and vertex highlighting

Selected vertex declarations in .3D Source now receive the same green
full-row highlight as a visible polygon. This works when picking a vertex
in the 3D viewport and when placing the source cursor on its declaration.
Vertices have no BSP polygon visibility status.

The **Symmetrical vertex editing** checkbox above the source is **off by
default on each new model**. Enable it only for geometry you expect to be
symmetrical, and select the correct mirror plane. X=constant mirrors across
YZ, Y=constant across XZ, and Z=constant across XY. The plane location
is in raw Papyrus coordinates and defaults to 0. The tolerance (also
raw coordinates) defaults to 0, requiring exact counterpart positions.

Edit a named vertex's XYZ triple normally. Before the editor compiles,
it finds the opposite vertex by reflecting its *previous successfully
validated XYZ*, not the already edited coordinates. With X=0,
changing left: [<100,20,30>]; to left: [<150,25,40>]; updates the
existing right: [<-100,20,30>]; to right: [<-150,25,40>].
With an offset mirror plane X=500, reflected X is 1000 - X.

**U/V texture coordinates and T fields never change.** The replacement
touches only the three XYZ number tokens, leaving other statements,
comments, materials, labels and references intact. Mirrored edits are
recorded in Automatic source changes and grouped with the source edit
for Undo.

When no match exists, the editor warns you; it also warns about a vertex
moved off its original symmetry plane. When several vertices occupy a
reflected position, you must choose which named source vertex to modify.
Canceling skips it. Editing both halves yourself prevents an automatic
overwrite. This mode never creates missing vertices or repairs unrelated
asymmetry. Structural edits and whole-model scaling bypass this helper.

## Calibrated tracing/reference images

Use a scanned plan, building elevation, blueprint or car side-profile
photo as a guide while editing the underlying model:

1. Open the geometry in **File → Open Model…**.
2. Choose **Assets → Load Tracing Reference Image…** and select a supported
   PNG, JPEG, BMP, WebP or TIFF. The image is previewed with the default
   Side (Y/Z) plane centered on the model; you can select Front (X/Z) or
   Top (X/Y) in the nonmodal calibration window.
3. Click **Align viewport to this plane (orthographic)** for a useful
   tracing view. The image is in *model space*, not fixed to screen pixels:
   it follows the orbit, pan and zoom camera.
4. Click **Pick A** and the first identifiable point in the image; then
   **Pick B** and the second. For a car, choose wheel centers; for a
   building, two points whose separation is known. Enter the corresponding
   length in **raw Papyrus model units**, not feet/meters unless you have
   independently converted them. This determines world units per pixel and
   rotates the image so A→B aligns to the horizontal axis of its selected
   plane. A coincides with the current **world U/V** anchor.
5. Fine-tune the **world U/V** anchor, **rotation**, **raw units/pixel**,
   **opacity** and **Show tracing image**. The **Reset scale and center to
   model** button restores an approximate fit based on mesh bounds.
   The reference can be kept while the dialog closes. **Assets → Adjust
   Tracing Reference…** reopens the controls.
6. Choose **Assets → Remove Tracing Reference** (or **Remove image** in
   the dialog) to discard it.

Side uses raw **Y right / Z up**, Front uses **X right / Z up**,
and Top uses **X right / Y up**, matching the editor's canonical
orthographic views. The reference is composited **behind** polygons
even in painter and wireframe modes, so it never steals clicks or
obscures a modeled face. The image is a *reference-only* GL pass and is
not added to the geometry, BSP, source, texture atlas or saved/exported
3DO. A reload or live source recompile preserves the overlay; opening
a different model clears it. The image file is read locally and is not
uploaded or modified. Large images are downsampled for GPU display;
marker coordinates remain relative to the original image size.
The active overlay is session-only, but you can save reusable profiles:

- **Save as…** in the calibration window, or **Assets → Save Tracing
  Reference Profile…**, names the active image and its plane, two
  calibration points, known distance, raw model-units-per-pixel, rotation,
  U/V placement, visibility and opacity. Saving an existing name asks before
  replacing it.
- Choose a name and **Restore** inside the dialog, or use **Assets →
  Restore Saved Tracing Profile…** after opening a different model. Profiles
  persist after quitting and reopening 3DO CAD. The default **Place relative
  to current model center** keeps the original raw-unit offset from the
  source mesh center while retaining the same physical scale and rotation.
  To place it at the saved *exact absolute coordinates*, choose **Keep exact
  saved model coordinates** in the dialog before restoring.
- **Delete** in the calibration window, or **Assets → Delete Saved
  Tracing Profile…**, removes that saved calibration entry. It does not
  remove the source photograph, the currently displayed image, or the
  model. Deleted profiles cannot be restored unless saved again.

The profile library is a human-readable JSON file in the user configuration
folder, `ICR2Tools/3DOCAD/tracing_profiles.json`, separate from game assets.
Profiles keep an **absolute filesystem path** to the original image rather
than copying image pixels. If an image is moved, removed or resized, the
app reports the problem and leaves the current reference untouched. Restore
the original image path/dimensions or recalibrate/save a new profile.
Profiles can be applied to any model in that installation; moving to a
different computer requires the image files to be available at the saved
paths. A saved profile is not baked into any compiled 3DO.
For tracing, use a true side elevation/orthographic photograph where
possible: perspective photos have foreshortening that a two-point
uniform calibration cannot remove.

## Car, Track, and Object workspaces

The main window is a **3D viewport and a side-by-side editable .3D source
pane**, without a permanent inspector, toolbar or source Help tab.
Use **Model → Workspace** to select Car, Track or Object, or open
**Model → Model Settings…** for the full workspace controls. These controls
reside in a separate, scrollable dialog, and changing workspace does not
reload the model, reset the camera, compile source, or discard unsaved edits.

- **Car** groups appearance-wrapper/carshape resolution, body or external
  material targets, livery MIP assignment, overrides, and RECOLOR status.
  The external 3DO folder also resolves wheel and helmet models.
- **Track** provides track-scene statistics (vertices, planes, external
  instances, RES switches and unresolved references), an external 3DO folder
  for trackside assets, fallback texture controls, and a **Track section detail**
  selector for indexed Papyrus track models. The selector defaults to **HI** and
  switches among **HI** (four section slots), **MED** (two), and **LO** (one)
  as global preview modes. With a matching same-folder TRK and section DLONG
  metadata, the default is **Camera window (HI / MED / LO)**: the section
  currently containing the camera's DLONG and the next **8 sections in each
  direction** are drawn at HI; the next **5 each way** at MED; then **3 each
  way** at LO. All farther sections are omitted. The three per-direction
  counts are independently adjustable in the Track tab, including zero;
  near/far windows wrap across DLONG zero for closed tracks. Overlap on
  short tracks prioritizes the nearer/highest detail. The camera window
  works with ordinary `.3D` source DATA (the eighth section LIST slot) and
  with original compiled `.3do`, where the compiler preserves the four
  DLONG values in otherwise unreferenced DATA immediately preceding each
  seven-pointer section LIST. Identical compiled LIST aliases share their
  metadata. Missing/ambiguous metadata disables adaptive mode, while global
  HI/MED/LO continues to work. The mode never modifies source or binaries,
  reuploads the full polygon VBO on movement, or affects car/object RES.
  Empty/NIL slots stay empty. The selector is disabled for models without
  a recognized track section table. **Recognized Track files default to
  BSP selection + OpenGL depth** (cars and standalone objects keep their
  painter-order default). The viewer identifies **TSD / DetailList** track
  surface markings from the alternating POLY + LINE/NIL record signature,
  including original compiled 3DOs without source names. Only visible TSD
  triangles are redrawn in one batched, depth-biased OpenGL overlay pass,
  preventing stripes and road-texture Z-fighting while preserving ordinary
  depth occlusion from closer scenery. No source vertex heights, MIP data or
  BSP/LOD selections are changed; global rendering modes remain selectable.
  The **Skybox (horiz.3do / horiz.3d)** checkbox is enabled and on
  by default if a valid `horiz.3do` is found beside an indexed track
  or in its `objects` / configured external objects folder. If no
  valid binary exists, the viewer compiles a valid `horiz.3d` instead.
  Case-insensitive discovery tries all binary candidates before any
  source candidate; an invalid/nonrenderable binary does not prevent
  trying source. The skybox
  is rendered in an independent background pass: its virtual eye stays at
  raw `(0,0,100)` by default, while camera yaw/pitch/tilt follows the viewer. The
  Track tab has editable HORIZ eye X/Y/Z fields (raw Papyrus units) and a reset
  button, allowing horizon alignment without changing the HORIZ file. Panning,
  zooming or moving a fixed camera does not translate the sky. The sky's
  named MIPs (`skyindex`, `page03b`, `page03` for the reference model)
  are resolved beside the selected HORIZ file, and missing textures are reported on the
  Track tab. The toggle never changes track geometry, source, BSP or LOD.
  **Reload MIPs (R)** reloads both track and sky atlases (rebuilding the
  scene while preserving the camera and current editable source).
  **TRK camera — follow racing direction** automatically searches the same
  folder for `<model-stem>.trk` (case-insensitive) whenever a recognized
  track `.3D` or `.3DO` opens. If found, it loads the physics course using
  the shared `icr2_core.trk` parser and enables a perspective camera at
  `DLONG=0, DLAT=0`, 10,000 raw Papyrus units (about 1.67 feet) above
  the TRK ground, oriented along the
  centerline's direction of travel. Click the 3D viewport to focus it, then
  **W / Up** = forward (increasing DLONG), **S / Down** = backward,
  **A / Left** = left (positive DLAT), and **D / Right** = right (negative
  DLAT). Hold Shift for 5x movement; configurable defaults are 10 feet
  longitudinal and 2 feet lateral per keypress. DLONG wraps around the lap;
  continuous bends change the heading automatically. The onboard camera
  also rolls with the TRK's local banking, sampled from ground elevations
  one foot to either side of the current DLAT. This follows banked turns,
  flatter straights and transitions without modifying the 3DO mesh, and
  rotates the HORIZ skybox together with the camera. Orbit and fixed
  camera modes remain level. The Track tab reports the current signed
  bank angle, section, DLONG/DLAT in raw units and feet, and camera XYZ;
  it has a
  reset-to-zero button. Uncheck TRK camera to restore the prior orbit view.
  Missing or malformed matching TRK files never stop geometry from opening.
  Recompiles preserve the TRK position and on/off state; loading another
  track starts at the new track's DLONG zero. Geometry, physics TRK, MIPs
  and source are all read-only in this mode.
  Original compiled track `.3do` files use seven-pointer section
  records and a special expanded root index (rather than the `.3D` source's
  eight-pointer lists and DATA hash). The viewer recognizes both formats,
  including compiled tracks whose expanded index contains extra sections
  absent from the repeated root hash (e.g. St. Petersburg 2024 and Washington
  D.C.). It keeps every distinct seven-slot LOD table, removes exact aliases,
  and replaces the root traversal in fixed HI/MED/LO views so the expanded
  prelude cannot draw all tiers unfiltered.
- **Object** provides standalone object diagnostics (polygons, MIP names,
  DYNAMIC references), external 3DO resolution and fallback texture controls.

**View → Customize Colors…** controls editor syntax/highlights and viewport accents.
**View → Display Settings…** provides projection, texture and RES distance
controls. **Assets → Asset Settings…** provides palette, MIP and external-3DO
configuration. **View → Advanced Diagnostics…** provides BSP rendering mode,
fixed-camera coordinates, polygon-offset lookup, benchmark and performance
information. These are nonmodal dialogs: change settings without shrinking
the viewport, and close the dialogs whenever they are no longer needed.
The source pane starts visible beside the 3D viewport, with the same live
compilation, save, and export behavior. If source preparation is still in
progress when Save Source or Export 3DO is requested, repeat the action once
the source pane reports that it is ready.

The viewer suggests **Car** for recognized car geometry or individual-car
appearance wrappers, **Track** for structurally recognized track section tables
(such as PUTNAM.3D) or clearly named track models (including
`track.3do` and `RENO.3D`), and leaves ambiguous filenames in the
currently selected workspace rather than guessing their semantics.
Select the correct mode manually for models whose names give no reliable hint.
The mode is a UI organization choice, not a conversion between file formats.
Skybox discovery is intentionally restricted to structurally recognized
indexed tracks, even if another model happens to be in the Track workspace.

## Desktop menus

The 3DO CAD editor uses a conventional **File / Edit / View / Model / Assets / Help**
menu bar. There is no permanent right sidebar.

- **File:** Open Model (**Ctrl+O**), Open Recent, Reload Model from Disk,
  **Save .3D Source** (**Ctrl+S**), **Save .3D Source As…**
  (**Ctrl+Shift+S**), Export Compiled 3DO (**Ctrl+E**), and Exit (**Ctrl+Q**).
- **Edit:** Undo/Redo, Cut/Copy/Paste, Select All, **Scale Model…** (uniform multiply/divide), Find in .3D Source
  (**Ctrl+F**) / Find Next (**F3**), Rename Selected Pointer, and
  Apply .3D Source Now. Standard text commands act on the focused editor
  (or the N3 source editor when no other editable text control has focus);
  Find searches full source text, including comments and filtered-out lines.
- **View:** Frame All, 3D/Top/Front/Side presets, Perspective, Fixed Camera,
  show/hide .3D Source, **Rendering Mode** (including Wireframe), common display
  toggles, Display Settings, Advanced Diagnostics and **Load Error Log…**.
  The Rendering Mode menu and Advanced Diagnostics combo stay synchronized.
- **Model:** Car/Track/Object workspace selection and the on-demand Model
  Settings dialog, with direct entries to each workspace's controls.
- **Assets:** Asset Settings dialog, palette selection/reset, MIP and
  external-3DO folders, fallback MIP selection/reset, and Reload MIPs.
- **Help:** keyboard/mouse controls and an About dialog.

The first **Save .3D Source** prompts for a .3D output path (by default an
`_edited.3d` name). Later Saves reuse that explicitly chosen path;
**Save .3D Source As…** always asks for another location. Saving source marks
the current text as saved, even if it cannot yet compile. Export Compiled
3DO continues to require validated source and protects the original
binary from replacement. Open, Reload Model, and Exit ask before
discarding unsaved source edits, with explicitly labeled **Discard changes**
and **Cancel** buttons. Saving over the original source uses **Overwrite
original** and **Cancel**. All destructive confirmations default to
**Cancel**: pressing Enter, Escape or closing the dialog never discards or
overwrites source without choosing the named action. Recent models are
kept in the user's Qt settings, and failed opens are not added to the list.

**Load Error Log:** On opening a .3D or .3DO, any recoverable loading
problems automatically open one scrollable, nonmodal report. It groups the
full list of unresolved DYNAMIC/EXTERN assets, missing or invalid MIPs,
PMP sprites, palette problems, skybox failures and skybox MIPs, and malformed
TRK navigation. There is no automatic popup if nothing went wrong, and
simply omitting an optional skybox/TRK is not an error. The report remains
available after closing it under **View → Load Error Log…**; the menu can
also show a clean-load report. **Copy Log** copies the full text for
troubleshooting. Opening a different model replaces the old report.
A fatal file-load error is also preserved in this report, even when the
previous preview remains visible. Live source recompilation and MIP
reloads refresh the report without repeatedly opening new windows.

The main window title displays the **last successfully opened .3D/.3DO
filename** and current workspace. An **asterisk (`*`)** after the filename means
the editable .3D Source has unsaved changes. Undoing back to the saved
contents or successfully saving .3D Source removes it. An unsuccessful
attempt to open a different file does not replace the displayed filename.

The **Projection** dropdown sits immediately above the viewport alongside
SWITCH DISTANCE. Every newly opened model defaults to **Perspective**,
even when the previous model used Orthographic. Same-model asset reloads
and live source recompiles retain the user's projection choice. The
dropdown stays synchronized with View → Perspective and the existing
Display Settings checkbox. While Fixed Camera or TRK driving is active,
Perspective is required and all three projection controls are disabled.

Single-letter **F** (Frame All) and **R** (Reload MIPs) remain scoped to
the viewport so those letters can be typed normally in the N3 editor.

## MIP texture and U,V reference window

Choose **Assets → Browse Model MIPs / U,V…** after opening a model.
This opens a **separate, non-modal window** that can stay visible next
to the 3D viewport and `.3D Source` editor while you work.

- The left list shows every **successfully resolved MIP used in the currently
  loaded geometry**, including referenced external objects, MATERIAL MIPs,
  and the active car-livery/fallback overrides. Multiple faces using the
  same file appear only once. Missing textures are listed in the summary,
  not misrepresented as loaded images. The full resolved path appears on hover.
- Select a MIP to display its highest-resolution, 8-bit indexed image
  recolored with the **same PCX palette currently in the 3DO CAD editor**.
  Use the **mouse wheel** or **+ / −** to zoom, **Fit** to see the entire
  texture, and **100%** for original texel size. Enlargements use nearest
  neighbor sampling; pixel-grid lines appear when sufficiently zoomed in.
- **Middle-drag** or **Shift+left-drag** to pan. **Left-click** a texel
  to highlight its 1×1 pixel area and show its integer **U,V**.
  **Copy U,V** places `u, v` on the clipboard for N3 editing. U increases
  rightward, V downward; `(0,0)` is the top-left pixel. These are **raw
  Papyrus texel coordinates, not normalized 0..1 UVs**.
- The open window follows successful model/source recompiles, palette
  changes, and MIP asset reloads. It retains the selected texture when
  possible. It never writes MIPs, source, or binary model files.

**Note:** Only textures that actually made it into the rendered model atlas
are listed. Unresolved, invalid, or atlas-capacity-excluded MIPs are
reported by the existing load diagnostics, not shown with fabricated pixels.

## Display vertex pointer names

Enable **Vertex labels** in the row immediately **above the 3D viewport**
(next to the Pick selector). The display-mode dropdown beside it provides
three choices:

- **All:** label every root-model vertex inside the camera frustum, including
  hidden/back-side vertices and vertices declared only for FACE/BSP planes.
  This is the original behavior.
- **Visible only:** label vertices on the **frontmost polygon surfaces**.
  A separate depth-only pass tests each projected vertex against the actual
  model geometry, so vertices hidden on the back of a car are excluded even
  when the viewport is in Papyrus drawing-order or wireframe mode. Vertex
  labels also respect the current polygon/RES selection. In wireframe mode,
  the depth test uses filled geometry as if surfaces were opaque; the visible
  wireframe itself remains see-through. Coincident/coplanar edges and
  subpixel silhouettes can still produce a few overlapping labels.
- **Selected poly:** show only vertices referenced by the polygon currently
  highlighted in **.3D Source** or clicked with **Pick → Polys**. No polygon
  selected means no blue dots or names. This mode is useful alongside the
  polygon-splitting controls, and does not need OpenGL depth readback.

The checkbox is **off by default**; the initial mode is **All** to preserve
existing behavior. All modes show small blue dots and pointer names, while
an individually selected vertex retains its larger yellow marker and name.
Models opened directly from binary `.3do` do not preserve authored pointer
names, so the generated N3 `_offset` names appear instead. The overlay
moves with orbit/pan/zoom, perspective/orthographic changes, and live N3
recompilation without changing the model or intercepting mouse clicks.
The dot/name colors are adjustable under **View → Customize Colors…**.
External DYNAMIC models have their own source files; only vertices belonging
to the root model are labeled.

## Split a polygon

Use **Split polygon…** above the 3D viewport (or **Edit → Split selected
Polygon…**). The tool switches picking to **Polys**. Click a visible polygon
in the *root model*; the contextual controls open **below the viewport**,
leaving the N3 editor visible alongside it.

- **Cut between edges:** pick two different numbered edges and a fractional
  position (0.5 = midpoint) on each. The cyan dashed overlay previews the
  cut. This adds two vertices, generates two polygons in a LIST, and repairs
  adjacent polygons that share the exact original edge pointers.
  Each edge is identified by its endpoint pointer names, for example
  `#1 front_left → front_right`, rather than an internal body offset.
- **Diagonal between existing vertices:** choose two nonadjacent numbered
  vertices; no vertices are added. The existing diagonal safety checks
  also reject cuts outside concave polygons.
  The vertex dropdowns show the existing `.3D` declaration names, for
  example `#1 front_left`. Raw offsets remain available as hover tooltips.
- **Split polygon** shows a confirmation with the vertex and neighbor counts
  and any seam warnings. **Close** hides the panel.

The operation edits the canonical **.3D Source** document as one undoable
change and recompiles the preview; it does not save anything automatically.
Use **Edit → Undo** or source-editor Ctrl+Z to undo; **Save .3D Source**
preserves the textual edit, and **Export compiled 3DO** writes a separate
validated binary. Existing unrelated declarations, pointer names and comments
are retained. For a split inside a MATERIAL wrapper, the wrapper continues
to surround the two new POLYs. A polygon must have its own named POLY
declaration or an individual MATERIAL wrapper; anonymous polygons embedded
in larger LIST/BSP expressions are rejected rather than rewritten blindly.
Duplicated coordinate edges that do not share original vertex pointers (for
example UV seams) are reported for manual inspection. BSP planes are not
rebuilt. Back up and validate any edited model in ICR2.

## Controls

- **Pick selector (above viewport):** **Vertices** is the default; choose
  **Polys** explicitly to click a face instead of a vertex. In Poly mode,
  clicking a visible root-model polygon highlights it and navigates to its
  original declaration in **.3D Source**. The source editor scrolls to the
  named declaration; if filtered statements are open, the matching POLY row
  is selected and scrolled into view (hidden POLY rows are revealed).
  Concave polygons are picked using their existing rendered triangles; the
  nearest intersected eligible face wins. No source or model data changes.
- **Left-click near a vertex (Vertices mode):** select the nearest visible root-model
  vertex (within 24 logical screen pixels) and jump to its declaration in
  **.3D Source**. The declaration label is selected, and the existing yellow
  viewport marker identifies the vertex. If source is hidden, it opens;
  if generated source for a binary .3do is still being prepared, the jump
  completes when source is ready. Custom authored labels and generated
  `_offset` labels work in both full and filtered-source modes. Clicks in
  empty space do nothing. Referenced DYNAMIC/EXTERN child vertices are
  excluded because the Source pane edits the root model only.
- Left mouse drag: orbit (a drag does not trigger picking in either mode)
- Shift + left drag or middle drag: pan
- Mouse wheel: zoom
- 3D, Top, Front, Side buttons: standard orthographic views
- **Projection dropdown (above viewport):** choose Perspective or
  Orthographic. Newly loaded models always use Perspective.
  Perspective BSP uses the real finite camera; orthographic BSP uses the *parallel viewing
  direction*, so zooming does not spuriously flip front/back visibility.
  For near-edge-on planes the finite-eye sign is used as an approximation.
- **Fixed Camera**: toggles a stationary **perspective** camera at
  editable *raw Papyrus* XYZ coordinates, defaulting to **(0,0,5000)**.
  The X, Y and Z numeric controls appear in **Advanced diagnostics**
  below Fixed Camera while this mode is enabled. Enter positive or negative model coordinates
  (up to ±2 billion raw units); changing any coordinate updates the camera
  position and BSP/automatic RES selection immediately without retessellating
  geometry or reloading textures. All entered XYZ values persist when the
  mode is toggled off and back on during the current session.
  The coordinates refer to the original .3D/.3DO model, **not** the normalized
  OpenGL mesh bounding box: projection accounts for the mesh center and scale.
  The initial direction looks horizontally along +Y; drag to look around,
  or use 3D/Top/Front/Side to change direction without moving the eye.
  Mouse wheel changes perspective FOV (20–110 degrees) instead of dollying;
  shift/middle panning is disabled. Perspective is locked while active.
  Toggle Fixed Camera again to restore the prior external view, or use
  Frame All to exit and refit. No geometry, text, or textures are changed.
  This is a user-selected diagnostic view, not a verified game-wide cockpit
  viewpoint.
- Frame All (F): recenter and fit the model; exits Fixed Camera
- Open: load a different .3D or .3do without restarting. If source edits
  are unsaved, the viewer requests confirmation before discarding them.
- **.3D Source**: the editor is shown beside the 3D viewport by default,
  without a separate Help tab. Choose **View → Show .3D Source** to hide or
  restore it. For a loaded .3D file it retains the original text and comments.
  Opening a binary .3do generates standalone, compilable N3 source with a
  named `root` declaration and no internal `ICR2_OFFSET` or `ICR2_ROOT`
  comments. This source can be edited and exported as a new .3DO without the
  original binary. The editor recompiles source when exporting a new binary; original binary record offsets may change. Source generation runs
  on a background thread; the 3D viewport stays interactive beside the editor.
- **Live updates**: after 650 ms without typing, the existing N3 compiler
  runs on a worker and rebuilds geometry/atlases if the new source is valid.
  Only the latest text revision may replace the rendered model. Invalid source
  highlights its error line and retains the last valid scene and camera.
  **Apply now** compiles immediately. Colors, XYZ, UV, plane definitions,
  LIST/BSP, DYNAMIC and RES edits are subject to the same N3 compiler rules
  as the 3DO parser/compiler.
- **Save .3D as…** saves the editable text to a chosen .3D path. It also
  permits explicitly saving unfinished/invalid source for later editing.
  It never silently overwrites the original file. **Export compiled .3DO…**
  writes the most recently validated compiled model to a *different*
  binary path; invalid or still-pending edits cannot be exported. Camera
  movement, source typing and live preview do not write any file.
- **Individual-car source**: with a driver wrapper like his21.3do open,
  the Source tab edits and recompiles the underlying indycar.3do base
  geometry, *not* the MATERIAL/RECOLOR appearance wrapper itself. RECOLOR
  and its selected body MIP remain applied to the live preview, along
  with independently referenced DYNAMIC wheel/helmet geometry.
- **Render**: **Papyrus BSP painter** (default) walks original FACE/FACE2/
  BSPF/BSPA/BSP2/BSPN nodes from the actual camera position and paints
  selected polygon triangles in the model's back-to-front order, with OpenGL
  depth testing disabled. **BSP selection + OpenGL depth** uses the same selected
  triangles with depth testing. **All polygons + OpenGL depth** ignores BSP/RES
  and is the legacy full-geometry diagnostic mode for non-track models. For
  recognized indexed tracks it still honors the selected HI/MED/LO section tier,
  so the three alternative surfaces are not overlaid. **Wireframe (polygon
  outlines only)** draws original polygon boundary edges as pale lines against
  the dark viewport, with no filled triangles, triangulation diagonals,
  textures, PMP sprites, or skybox. Its see-through view ignores BSP
  face culling but **honors the same SWITCH DISTANCE / RES selection** as
  the filled modes. Automatic chooses by camera-to-anchor distance; Manual
  uses the slider value; All levels shows all RES branches. Selected HI/MED/LO
  track section detail still applies to avoid stacking track surface variants.
  Selected source polygons receive an amber outline and vertex inspection
  markers still work.
  The edge buffer is built only on first use and reused when orbiting;
  loading or recompiling new geometry invalidates it.
- **Track section detail** is independent of **SWITCH DISTANCE / RES**. It
  selects one tier from the track's trailing `secN_lN: LIST` pointer tables;
  the viewer does not combine all seven slots as if they were scene geometry.
  Switching is immediate (OpenGL indices only), without recompiling or changing
  the source/binary file. Cars and ordinary standalone objects retain their
  existing RES behavior.
- **SWITCH DISTANCE / RES** is now in a compact strip **immediately
  above the 3D viewport**, rather than hidden in Display Settings. It
  provides **Auto / Manual / All levels**, a horizontal slider from **0 to
  the highest RES threshold**, and an exact raw-unit spin box. Dragging
  the slider or changing the number automatically selects **Manual**;
  **Auto** uses the camera-to-anchor distance; **All levels** shows every
  RES branch. The range is recalculated and clamped on model reload or
  valid source recompilation; controls are disabled when no positive
  RES threshold exists. The same setting controls filled and wireframe
  modes, including resolved external 3DO instances.
  Automatic computes each RES distance in local model coordinates, including
  transformed DYNAMIC objects, using Euclidean distance as an approximation
  rather than verified game-exact behavior.
- **Automatic model-local SUNNY.PCX**: whenever you open a new
  `.3D` or `.3DO`, the 3DO CAD editor first searches **that file's own folder**
  for `SUNNY.PCX` (case-insensitively). If present and valid, it becomes
  the active 256-color palette automatically, including for referenced
  sprites and MIP textures in the scene. The Assets panel shows
  **model folder** beside the palette name. If the file has no
  `SUNNY.PCX`, the previously selected palette remains in effect
  (the bundled `gamepal.pcx` is the initial default). If the local
  `SUNNY.PCX` is malformed, a status warning is shown and the previous
  palette is used so the model can still open. Only the **opened model's
  immediate folder** is searched; referenced 3DOs cannot replace its
  palette. Source recompilation and reloading the current model keep
  your currently selected palette.
- **Open PCX palette…**: manually choose any indexed 8-bit PCX with a
  256-color VGA palette trailer, overriding the automatically selected
  palette for the current model. **Default palette** restores bundled
  `gamepal.pcx`. Palette changes recolor both plain polygons, MIPs and
  PMP sprites instantly, without rebuilding geometry or decoding sprites.
- **Individual car 3DO**: open a per-driver `.3do` directly, such as
  `cit74.3do`. As in the original asset decoder, the root MATERIAL references a
  **RECOLOR record at body offset zero**, not a renderable child. The OpenGL
  loader reads it using the existing `car_appearance` decoder and opens
  the referenced base geometry (e.g. `indycar.3do`) separately. It maps
  only *base car* polygon color indices, preserving independent wheel and
  helmet colors and textures. The livery's indexed MIP pixels are unchanged.
- **Apply Individual-Car RECOLOR / MIP…**: after opening a geometry model
  (for example `roadcar.3do` or `indycar.3do`), choose this command in
  **Assets** or **Model → Car Settings…**. Select an individual-driver wrapper,
  such as `cit74.3do`. Its RECOLOR mapping applies only to the loaded root
  geometry; its MIP name is looked up beside `cit74.3do` and assigned only to
  the root textured body polygons. This intentionally ignores the wrapper's
  own EXTERN geometry reference, so CIT74 (which references INDYCAR) can be
  previewed over ROADCAR without swapping meshes. The model currently in the
  .3D Source pane remains editable; live recompilation, camera position and
  the source document are preserved. The window title and Car settings
  identify the active wrapper. **Clear Car Appearance Overlay** restores
  the prior model appearance; reopening another model clears the manual
  overlay. A wrapper that is not a valid individual-car RECOLOR/MATERIAL
  file is rejected. Missing named MIPs appear in the load diagnostics.
  A manually assigned body MIP remains a higher-priority explicit override
  until that manual override is cleared.
  **This is a preview overlay, not a source edit**: Save .3D and Export
  Compiled 3DO write edited root geometry only; they do not bake RECOLOR,
  include the wrapper's livery MIP, or modify the wrapper or its textures.
- **Car geometry / Assign carshape 3DO…**: on an individual-car wrapper,
  this lists the actual named base shape, not the wheel/helmet DYNAMIC
  references. Use it to locate the base `.3do` manually if necessary.
  Missing base geometry is reported in the status bar rather than silently
  showing a blank car. Clear shape override restores automatic lookup.
- **Texture target / Assign livery MIP…**: **Car body** is first and
  selected by default when root POLY[T] faces exist. It assigns a MIP
  *only to the base car's textured polygons*, never wheel1, wheel2 or
  helmet. Other materials are listed explicitly as **External/material**
  for advanced texture overrides. The wrapper's MATERIAL MIP is automatically
  applied to the body, with lookup relative to the wrapper directory.
  Clear livery override restores automatic lookup. Opening another model
  clears model-specific texture/geometry overrides so prior cars do not
  carry over unexpected wheel assignments.
- **Reload MIPs (R)**: rereads the changed MIP from disk on a background
  worker, without reopening the carshape or resetting the view. For an
  unchanged atlas layout, only the OpenGL's integer texture is reuploaded:
  geometry, BSP indices and camera are retained. If a MIP's dimensions/layout
  change, the worker rebuilds the UV attributes before replacing the VBO.
  Saving edits to the MIP in your image/conversion tool then pressing R
  previews a revised livery. No file writing or automatic file watcher.
- **3DO objects folder…**: optionally choose a folder containing the model's
  DYNAMIC/external references. For each child, the viewer first searches
  for a **valid .3do** (case-insensitive, across all standard directories);
  if no valid binary exists it compiles a **.3d N3 source** in memory.
  This also works for nested DYNAMIC references and negative EXTERN pointers,
  regardless of whether the parent was opened from .3D or .3DO. Models beside
  the parent and common adjacent object directories are searched automatically.
  Explicit per-object overrides still take precedence. Nested children retain
  their BSP, camera-local coordinates and RES anchors, and repeated placements
  share a parsed model but have independent transforms. Invalid files,
  missing models and cycles are reported without preventing the parent from
  loading. No referenced files are modified.
- **MIP folder…**: choose a folder containing the model's named `.mip`
  files. The loader also searches the model's directory and its `textures`,
  `mip` and `mips` subfolders, without case-sensitive filename assumptions.
  `MATERIAL` associations in the 3DO/N3 choose the texture for POLY [T]
  faces. **Fallback MIP…** maps otherwise-unassigned textured polygons to
  an explicitly chosen file; **Clear fallback** reverses this override.
  Changing MIPs rebuilds the read-only mesh/atlas, not the source file.
- **Textures**: toggle sampled MIP colors and PMP sprites versus flat
  polygon palette colors. **Repeat UV (tile MIPs)** is enabled by default for
  both editable `.3D` and compiled `.3DO` files. If UVs extend beyond the
  dimensions of their assigned MIP, the shader wraps them independently by
  that MIP's actual width and height, without sampling neighboring images in
  the shared atlas. Uncheck it only to compare the former clamp-to-edge
  behavior. The status line reports loaded/missing MIPs, mapped faces and
  atlas size.
- **PMP sprites (PMP/PMP2)** (Display, enabled by default): render
  viewpoint-selected transparent sprites both in the opened 3DO and in
  DYNAMIC/external referenced 3DOs. Uses the same validated PMP decoder as
  the existing palette decoder: indexed colors and missing-span transparency, with the
  current PCX palette sampled directly on the OpenGL. PMP files do **not**
  have a single fixed signature: their first four bytes encode each image's
  width, height, and X/Y origin offsets. The decoder now validates these
  against the color-span records, accepts the optional helmet-style 0xAF
  footer, and supports terminator-free scenery sprites such as tree1.pmp,
  tree2.pmp, tree3.pmp and tree4.pmp. The matching 3DO references can be
  displayed with a user-selected SUNNY.PCX palette. The sprite files are
  resolved case-insensitively beside the referenced 3DO, in the selected
  external-objects folder, or in the selected texture folder; missing/invalid
  sprites are reported in Assets without blocking polygon rendering.
  Camera-facing quads use the source vertex as the original **256x256 PMP
  canvas's row 127** (horizontal center x=128). The cropped visible bitmap
  retains original pixel coordinates, so a tree with painted rows 7..127
  stands above its 3DO Z vertex instead of being centered around that vertex.
  This applies to PMP and PMP2, including referenced and DYNAMIC sprites.
  Image-crop-based scaling remains unchanged. Billboard draw order remains
  the original BSP/RES/LIST sequence between polygon spans. **Textures** must also
  be checked. Both checkboxes may be switched without reloading the model.
  Opening a new model decodes all sprite view variants on a worker; orbiting
  or changing SWITCH DISTANCE changes which sprites are selected, without
  re-decoding PMP bitmaps or rebuilding the polygon VBO.
  This follows the historical sizing approximation, not a verified
  bit-exact game sprite projection or depth convention. In the diagnostic
  **All polygons** mode, all sprite variants are drawn, just as all polygon
  alternatives are drawn.
- **Polygon body offset** (Advanced diagnostics): type the polygon's **3DO body offset** in decimal or 0x
  hexadecimal (as displayed by the CAD structure inspector) to see whether
  it is selected by BSP and the chosen LOD. Selected does not necessarily
  mean pixel-visible: other drawn polygons can still cover it.

Loading and mesh creation run on a worker thread; the OpenGL context and
buffer upload stay on Qt's GUI thread. A **stage progress bar** appears above
the viewport while opening or rebuilding a model, even if Model Settings are
closed. It reports model/reference parsing, palette, HORIZ skybox, TRK
navigation, PMP sprites, MIP atlas, triangulation, and final OpenGL upload.
Percentages are coarse completed-stage markers, **not** estimated time
remaining: they may stay at a stage while a particularly large stock track is
being processed. The bar briefly shows 100% on success, disappears after
completion, and hides on failure while the existing error log remains
available. Preparing editable N3 source has its own separate worker/status.

**View → Live Load Activity** opens a nonmodal, timestamped trace panel that
also opens automatically when a file starts loading. It reports the exact
referenced 3DO, HORIZ, PMP and MIP currently being read, progress through
instance flattening and polygon triangulation, and BEGIN/DONE markers for
each OpenGL geometry/texture/skybox/sprite upload. The most recent 4,000
lines remain visible in the panel, with **Copy full log** and **Save as…**
buttons for the complete on-disk trace. The log also follows automatic
**editable N3 source generation** after model loading, including record
conversion progress and insertion of the resulting text into the editor.
An unrelated **Load Error Log** still lists finished-load warnings
and failures.

The trace is appended **synchronously to disk before each expensive
operation**, so its last BEGIN line remains inspectable even if the Qt GUI
stops repainting. The default path on Windows is
`%USERPROFILE%\\ICR2Tools\\cad_last_load.log` (the panel shows the
actual path and uses a temporary-folder fallback if needed). It records
local file paths and full exception tracebacks, so review it before sharing.
The last log remains available after a crash/restart until a new model load
begins; it is not sent anywhere. If the load reports nothing for **12 seconds**,
a watchdog writes an **INACTIVITY SNAPSHOT** with the last attempted operation
and current Python stack traces to the same file; it repeats at most every
20 seconds (20 snapshots maximum), even when the Qt GUI cannot repaint.
A stage entry or silence is diagnostic rather than proof of a deadlock.
A blocking native driver call can also prevent Python's watchdog thread
from running if it holds the Python interpreter lock.

## N3 context-sensitive syntax help

While editing **.3D Source**, a compact **N3 help** line below the text box
follows the command at the cursor: its purpose and a signature showing the
correct syntax. Hover over a statement for a longer explanation, or press
**Ctrl+Shift+Space** (or click the **?** button) to request the full help
without inserting or modifying any text. The expanded tooltip has a narrow,
wrapped width and is anchored **beneath the source line** near the left
edge of the Source editor rather than over the 3D model. Qt can move it above
the line when there is insufficient space below near the screen boundary.
The same placement is used for filtered statements and inline editing.

Help also appears when hovering over a **filtered statement row**. While
editing a filtered statement directly (double-click), the live help follows
the in-place editor's cursor and unfinished syntax; **Esc** still cancels and
**Ctrl+Enter** still commits that one statement.

The reference covers the **N3 constructs supported by the current compiler**:
vertices (including texture UV and color), POLY / POLY [T], LINE, LIST,
NIL, FACE / FACE2, BSPF / BSPA / BSP2 / BSPN, MATERIAL, SWITCH DISTANCE,
DYNAMIC, EXTERN, SUPEROBJ, SRB / PMP2, RECOLOR, DYNO, DATA, and the 3D VERSION
header and ICR2 metadata comments. FACE/FACE2 tips explain one-sided vs
front/back surfaces; BSPF/BSPA/BSP2/BSPN tips explain the viewer's
front/back child selection, drawing order and which branches are skipped.
The source tuple's winding (v1 → v2 → v3) determines its positive/front
side. These are **CAD viewer BSP traversal rules**, not claims that every
visited polygon must be pixel-visible or a bit-exact reconstruction of
the original game. Undocumented payload meanings such as DYNO are not guessed.

POLY and POLY [T] tips also describe how to switch **solid ↔ textured**:
add/remove [T] directly after POLY. Texturing additionally needs T=<U,V>
at every referenced vertex and an applicable MATERIAL MIP texture; switching
to solid lets the POLY palette index determine its color. Existing vertex UVs
may remain when converting back to solid, and shared MATERIAL wrappers
should not be removed without checking their other child geometry.

Help works during partial and multiline typing and when source has not yet
recompiled. It does **not** alter source, perform completion, change any
model vertex, trigger recompilation, or interfere with F2 pointer renaming.
For large generated .3D sources, the active-context lookup visits at most
48 nearby text blocks rather than scanning the entire source on cursor moves.

## Filtering and navigating .3D Source

The **Filter statements** dropdown in .3D Source contains checkboxes for
**Comments (%)**, **POLY**, **Vertices**, **LIST**, **BSP**, **FACE**,
**SWITCH**, **MATERIAL**, **DYNAMIC**, **LINE**, **RECOLOR**, **Sprites**
(SRB/PMP2), and **Other** (NIL, DATA, SUPEROBJ, the version header, etc.).
Every category is checked by default, so the normal editable source is shown.

- Uncheck any categories to **exclude** those statements from the
  navigation results, or click **Only** beside a category to isolate it.
  **Show all** restores the full editable source; **Hide all** gives an
  empty starting point for choosing a few categories.
- The **Active SWITCH DISTANCE branches only** checkbox in the same
  dropdown adds a second, independent filter. It follows the compiled
  model's selected RES branches at the current Display-panel manual distance,
  or per-anchor camera distance in **Automatic** mode. The list updates when
  the slider, mode, or camera moves. **Show all detail levels** includes all
  RES branches. Active branch wrappers (SWITCH, LIST, FACE/BSP, MATERIAL,
  DYNAMIC), their POLYs, the vertices referenced by those polygons and
  RES anchors, and named FACE/BSP plane vertices are kept together. Branches
  not selected at the current distance and unrelated declarations are hidden.
  Combine this option with any statement-type checkboxes or Find text.
- **Active** here means reachable through the current **distance/LOD**
  selection, **not necessarily visible on screen**: BSP camera-side culling,
  occlusion, and clipping are intentionally separate. Green/salmon POLY
  inspection still reports BSP/LOD drawing selection. Standalone comment
  lines and unused declarations are excluded in active-only mode.
  If the editor has unvalidated source edits, the list uses the last valid
  compiled model and labels its status accordingly; newly renamed statements
  stay in the filtered list until recompilation. If no compiled model is
  available, the filter temporarily shows category matches rather than
  incorrectly hiding everything.
- The **Find** field further filters results by label or displayed statement
  text. Results display **original file line numbers** in source order.
  Multiline declarations are grouped as a single result, so they are never
  cut into dangling continuation lines. Standalone `%` comment lines are
  listed under Comments, while inline comments stay with their statements.
- The filtered results are **editable in place**, not a separate read-only
  navigation mode. Select a statement to inspect its polygon or vertex in the
  3D viewport. **Double-click** a result (or start typing on a selected row)
  to edit that statement inside the filtered list. **Ctrl+Enter** commits the
  edit, **Esc** cancels, and moving focus away also commits. Multiline
  statements open with their complete text.
- After each edit the **same checkbox selection and Find query remain active**,
  so you can immediately edit the next matching statement. If your edit
  changes a statement's category or removes its search match, that row
  naturally drops out of the filtered results.
- **Show full source at selected line** remains available when you want
  unrestricted editing across statement boundaries. The inline editor
  deliberately restricts each edit to one complete statement, so a large
  paste or selection cannot delete filtered-out statements between rows.
- Filtering itself **never deletes or modifies hidden lines**. Inline edits
  update the **one canonical N3 source document**, preserving undo/redo,
  revision tracking, live compilation, validation, Save Source and 3DO export.
  The existing optional auto-rename feature still updates references across
  the document when an edited declaration label is renamed. **Find error**
  restores the complete editor before navigating to the failing line.

## Customizing source and viewport colors

Choose **View → Customize Colors…** to open the scrollable color editor.
Colors apply immediately to the open viewer and persist across launches in
your operating system's `ICR2Tools/OpenGLViewer` Qt settings. Each swatch opens
the native color picker. **Restore Dark Defaults** and **Use Light Preset**
provide coordinated, high-contrast syntax/selection palettes, including
the text color over selected POLY and compiler-error lines.

The source editor exposes separate colors for its background and plain text,
comments, quoted filenames, N3 keywords, pointer labels, selection background
and foreground, visible/not-drawn POLY highlights, error-line background,
and highlighted-line text. The same POLY colors apply in the filtered
statement list, so switching between full and filtered source does not
change readability. The source editor no longer inherits an arbitrary
light/dark operating-system background while keeping fixed pale syntax.

The 3D viewport provides separate controls for the clear/background color,
normal wireframe lines, the selected-POLY wire outline, **two selected-face
tints** (one for dark polygon/texture pixels, another for bright or white
pixels), vertex marker fill, and vertex marker border. Instead of simply
brightening the selected face to white, the shader automatically blends
between warm and contrasting blue tints according to underlying brightness.
The colors are editable and saved with the other appearance preferences.
Three additional settings control BSP plane vertex-marker fill, winding-arrow
color and marker outline separately from the editable vertex dot. Changes
do not recompile N3 or re-upload the mesh. A loaded track skybox can
cover the viewport's clear color.

## Inspecting N3 geometry with the source cursor

Open **.3D Source** beside the OpenGL preview. Place the text cursor anywhere
within a named `POLY` or `POLY [T]` declaration to tint that face.
This also applies to **inline POLYs nested directly in MATERIAL** declarations,
for example `rs1: MATERIAL MIP="usag", GROUP=3, POLY [T] <208> {a,b,c,d};`.
Selecting the MATERIAL row highlights its compiled POLY child rather than the
non-renderable MATERIAL wrapper. The same row is navigable under both
**MATERIAL** and **POLY-only** filters (its displayed category remains MATERIAL);
the green/salmon source highlight and the viewport POLY tint follow the actual
child's active BSP/LOD visibility. Picking that polygon in the viewport returns
to the authored MATERIAL row. A MATERIAL holding a LIST or a separately named
POLY reference remains a normal MATERIAL row, not an implicitly selected POLY.

Place it within a named vertex declaration (`name: [<X,Y,Z>];`) to show
a bright dot at that vertex in the 3D viewport. Selecting a named **BSPF,
BSPA, BSP2 or BSPN** declaration additionally highlights the three vertices
in its plane operand, with distinct **cyan plane markers** and directed
**1 → 2 → 3 → 1** arrowheads indicating the source's exact winding order.
This works from full source or from the filtered **BSP** statement list.
The familiar single-vertex editing dot remains yellow, so plane inspection
cannot be confused with selecting an editable vertex. All overlays follow
orbit, zoom and fixed-camera views; they do not move geometry or edit N3.

Plane points can be named vertex declarations (including plane-only vertices
that are not otherwise rendered) or inline `[<X,Y,Z>]` coordinates. The
binary BSP plane normal alone does not retain the original tuple winding:
the source is the authority. Source-only overlays disappear while text is
pending validation, after compilation errors or when .3D Source is hidden.
Clipped/offscreen points and arrows are omitted rather than drawn at
misleading coordinates. Five-coefficient legacy plane tuples do not provide
three point operands and have no winding overlay.

- Cursor inspection works with named standalone .3D declarations as well as
  generated `_offset` declarations when a binary .3do is opened.
- Multiline polygon declarations are supported. Empty lines, comments and
  unrelated commands clear the overlay.
- While source text is unvalidated or contains a compilation error, overlays
  disappear rather than pointing to the *last valid* model incorrectly.
  They return after a successful live compile. Closing Source hides them.
- A selected polygon is contrast-tinted **only when its POLY is selected by
  the current BSP and SWITCH DISTANCE/LOD traversal**. If the active distance
  excludes its LOD branch, a high-contrast **Qt text banner** appears over
  the viewport; it is rendered independently of the OpenGL pipeline to avoid
  corrupted/distorted glyphs. BSP camera-side exclusions get a distinct
  explanation. The currently selected POLY declaration is also shaded
  **green** when included in the active BSP/LOD traversal, or **salmon** when
  excluded. Multiline declarations are shaded in full. These colors clear
  while the source edit is pending validation or when selecting a non-POLY.
  In **All polygons + OpenGL depth** mode, every renderable polygon qualifies
  because that mode bypasses BSP/LOD.
- Being included in BSP/LOD selection is **not proof of pixel visibility**:
  other geometry can still cover a selected polygon. The diagnostic highlight
  continues to draw atop those surfaces for inspection.
- Inline anonymous vertices within commands are not independent named
  vertex declarations. A marker also disappears if its 3D position is
  outside the camera frustum. Viewport clicking is available separately
  through the **Pick** selector.

### Scale all model vertices

Select **Edit → Scale Model…** when a valid editable .3D source is loaded.
Choose **Multiply coordinates by** or **Divide coordinates by**, enter a
positive number (for example, multiply by 2 for double size or divide by
4 for one-quarter size), then click **Scale model**. **Cancel** leaves the
source untouched. The scale pivot is the model origin **(0,0,0)**, with one
uniform factor applied to X, Y and Z (not separate axis stretch).

This transforms all N3 vertex XYZ coordinates, including named vertices and
inline `[<X,Y,Z>]` points in FACE/BSP planes. To keep the complete scene
consistent, it also scales DYNAMIC placement XYZ, SRB/PMP2 sprite sizes,
SWITCH DISTANCE thresholds and the signed 64-bit offsets of raw
five-coefficient FACE/BSP planes. **UV texture coordinates, palette colors,
MATERIAL assignments, rotation angles, object labels, comments and
referenced external 3DO geometry remain unchanged**. External objects are
*repositioned*, not resized; scale their source assets separately if needed.

Arithmetic uses decimal factors (so **Divide by 6000** is not approximated
through a float input). In integer-unit N3 files, final coordinates round
to the nearest integer Papyrus unit; source with fractional units retains
its original coordinate-scale interpretation even if the scaled numbers
become integers. Out-of-range coordinates, plane offsets and unsafe zero
LOD/sprite sizes are rejected **before the editor changes**.

The entire transform is **one Ctrl+Z Undo step** and is logged in the
Automatic source changes panel. It triggers the usual asynchronous
validation/OpenGL preview but does **not** save either the .3D or .3DO file.
Finish pending source edits or fix compilation errors before scaling. The
original source remains available through Undo until subsequent editing
or loading clears the editor history.

### F2: rename just a pointer name

Press **F2** with the caret anywhere in a named N3 declaration, including a
multiline continuation, or with a statement selected in the filtered results.
Enter the replacement name in the dialog. The editor changes **only the
declaration label**, leaving its command, vertex coordinates, color values,
texture assignments, spacing and comments untouched. In the filtered list
you stay on the same filter and can continue working.

With **Auto-rename references** checked (the default), F2 also updates exact
references to that pointer elsewhere in the full source, even when those rows
are hidden by filters. Disabling that checkbox makes F2 change **only the
label**. The rename rejects invalid N3 identifiers, reserved keywords and
duplicate declaration names before editing, and makes the entire operation
**one undoable change**. Press **Cancel** to leave everything unchanged.
F2 does nothing on comments, the version header or blank lines. Source still
requires an explicit save or compiled export to write files.

**Auto-rename references** is enabled by default in the .3D Source toolbar.
When you edit a declaration's pointer name (for example `old_panel:` to
`new_panel:`), the editor automatically rewrites matching references in
other statements after a short typing pause. The operation is token-aware:
comments, quoted MIP/EXTERN filenames, longer identifiers containing the
name, N3 keywords and other declarations are not modified. Name collisions
are not propagated; compilation reports the invalid declaration normally.
Uncheck **Auto-rename references** to edit declaration labels without
touching their references. Nothing is written to disk until an explicit save
or export. Automatic changes participate in the editor's undo history.

### Automatic source change log

A small, **four-line-high scrollable "Automatic source changes"** box sits
immediately below the full/filtered .3D editing area. It records automated
reference rewrites triggered by editing a pointer label and F2 pointer renames.
Each event includes the time, old and new names, original declaration line,
number of references updated and source line numbers for up to 30 rewritten
references (with a remainder count for larger edits).

The log is **read-only** and independent of the .3D document; reading,
selecting, copying, or clearing it does not affect file contents, the dirty
flag, live recompilation or undo. Ordinary typing does not produce entries.
The latest 2,000 log lines are retained for the open model and the list
clears when a different source file is loaded or the editor is reset.
**Clear log** clears only the history display, not edits. An Undo operation
reverses source changes but does not erase its historical log entry.

The selection uses original model coordinates and compiled N3 record offsets;
it does not recompile the model or re-upload the mesh on each cursor move.

## Architecture and what is measured

mesh.py builds **one packed, interleaved float32 XYZ/RGB/index/UV/atlas-rect
buffer** from original Papyrus polygons and the selected PCX palette. It handles
triangles, convex quads, and concave polygons through ear clipping;
degenerate faces are skipped and fallback fans are explicitly counted.
Large track coordinates are recentered/scaled for OpenGL float precision.

main.py uploads the XYZ/RGB/UV vertex buffer **once when the file opens**.
The worker discovers nested DYNAMIC and negative external references and
flattens their transformed instances into the same OpenGL buffer, preserving
their own polygon identifiers and material filenames. The parsed model trees
remain in memory for read-only plane traversal.
Orbit/pan/zoom updates the view matrix **and**, in BSP modes, re-evaluates
the original BSP node side tests using perspective's real camera location
or orthographic's parallel camera direction in unscaled Papyrus coordinates.
The parent's LIST/BSP event stream inserts child models at their original
DYNAMIC sites; their local-space transformations are inverted for BSP tests.
Each RES/SWITCH DISTANCE tests its own anchor in automatic mode. A single `uint32` **element/index buffer** is reordered
and uploaded only when view or LOD changes; it never retransfers polygon
XYZ/RGB/UV, reparses N3 or retessellates geometry. The continuous-redraw
benchmark reuses the cached index buffer while the camera is stationary.

Texture assets are decoded once using the existing validated `texture_preview.load_mip`
reader; their full-resolution **8-bit palette indices** are packed into a
single OpenGL `GL_R8UI` atlas. The fragment shader selects nearest texels
using original raw UV coordinates with per-MIP modulo tiling (default on),
then looks up their colors in a separate 256x1 PCX palette texture. No per-polygon draw calls or color conversion
during camera motion. The palette can be updated independently. Missing
or malformed MIPs leave the associated polygons in their flat palette color,
with the missing files counted in the UI. The atlas is capped at 4096x4096;
assets that exceed available capacity fall back to flat color.

The single expanded VBO includes the geometry of inactive LOD branches and
resolved external models. For individual-car RECOLOR wrappers, the
`car_appearance` decoder loads the shared base model separately; remappings
affect that model's polygons only, not the external DYNAMIC wheels/helmet.
The wrapper's MATERIAL filename is resolved relative to the original
wrapper directory, even if the shared shape lives elsewhere. The camera-dependent index list includes only
selected branches and emits child polygons at their parent's insertion site.
Repeated model files are parsed once and instantiated independently. An
optional external 3DO search folder can be selected in the UI.

The BSP painter path deliberately disables the normal OpenGL depth test:
depth testing can reverse LIST sibling paint order and coincident face
overlays. In OpenGL-depth modes the depth buffer is used as a diagnostic
comparison. Vertex winding is not used for automatic GL backface culling:
FACE/BSP plane rules control branch eligibility.

It reports:
- N3/3DO parse milliseconds: includes binary parsing but excludes
  editor-only BSP plane/polygon anchor inference
- Triangle-mesh construction milliseconds: CPU-side work
- OpenGL upload milliseconds: one-time blocking upload and synchronization
- Displayed FPS: Qt frame-swapped events during continuous repaint
- Polygon/triangle counts, skipped/fallback faces, and VBO memory

Numbers are *not* directly comparable to Tk's profiler unless the same model,
resolution, visibility and benchmark procedure are used on the same machine.

## Intentional limitations

The 3DO CAD editor has editable N3 source, .3D/.3DO export, and click
picking for root-model polygons and vertices. Referenced child models and
PMP/PMP2 sprites cannot be selected in the root source pane. PMP/PMP2 sprites
use a separate OpenGL 3.3 billboard shader with palette-index/alpha textures;
their dimensions and screen-facing behavior are approximate like the Papyrus sprite approximation.
Per-driver RECOLOR tables and livery MIP overrides remain read-only overlays;
the viewer does not save them back into carset archives.
It displays local and referenced DYNAMIC/child 3DO polygon geometry with
indexed palette colors and optional 8-bit MIP texture sampling.
Track-only LINE commands are **not rendered**, and exact Papyrus game
rasterization, frustum/near-plane clipping, mip-level switching, game-exact
per-object LOD distance, alpha/transparent texels, and display budgets have
not been reconstructed. A nearly edge-on orthographic BSP plane that spans
the viewport cannot be represented perfectly by one global front/back
decision; it falls back to the finite camera side for stability. BSP side tests and painter ordering reuse the editor's
existing reverse-engineered interpretation (not a verified reproduction
of the original game executable). Overlapping scenery can still look
different from ICR2, particularly with transparency or external objects.
Never infer that a BSP-selected polygon is completely visible on screen.

The OpenGL preview path suppresses only *plane-anchor inference*, an editor
safety feature. Previewing and switching workspaces never writes original
source files or .3DO assets. The explicit .3D save and compiled .3DO export
commands are the only model-writing operations; validate generated binaries
in the game before use.

A successful GUI smoke test verifies that an OpenGL 3.3 context can draw
a model. **No speedup is claimed until measured on RENO.**
If startup fails, check the OpenGL driver and that Qt has created a desktop
OpenGL context; software OpenGL can also be substantially slower.
