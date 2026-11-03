# Experimental GPU Viewer with live N3 source editing

This remains a **separate performance prototype**, not a replacement for the
Tkinter 3DO CAD editor. It reuses the production N3 compiler, 3DO Model
parser, CPU source export and scene traversal, rendering geometry through
PySide6 QOpenGLWidget + PyOpenGL (OpenGL 3.3). Binary 3DO and texture
assets are read-only unless the user explicitly exports a *new* file.

## Windows setup

Install Python 3.10+ with a working NVIDIA/AMD/Intel OpenGL driver. From the
repository root:

~~~powershell
python -m pip install -r icr2_3do_cad/gpu_viewer/requirements.txt
python icr2_3do_cad/gpu_viewer/main.py "C:\path\to\RENO.3D" --benchmark --report gpu_reno.json
~~~

Or from the icr2_3do_cad folder:

~~~powershell
python -m pip install -r gpu_viewer/requirements.txt
python gpu_viewer/main.py "C:\path\to\RENO.3D" --benchmark --report gpu_reno.json
~~~

The optional --benchmark switch requests continuous redraws (~60 Hz)
and reports **actual presented frames per second** through Qt's
frameSwapped signal. VSync may cap this near the display's refresh rate.
The optional --report path writes aggregate timings on close, omitting
full paths, geometry coordinates and model source. Run once with RENO and
once with a building or fixtures/roadcar.3do.

## Car, Track, and Object workspaces

The viewer has a large GPU viewport and a **scrollable right-hand inspector**
with collapsible **Model**, **Display**, **Assets**, and **Advanced diagnostics**
sections. **Model** contains the Car / Track / Object workspace tabs.
Change workspaces at any time to show the tools appropriate to the current
asset; tab changes do not reload the model, reset the camera, compile source,
or discard unsaved edits.

- **Car** groups appearance-wrapper/carshape resolution, body or external
  material targets, livery MIP assignment, overrides, and RECOLOR status.
  The external 3DO folder also resolves wheel and helmet models.
- **Track** provides track-scene statistics (vertices, planes, external
  instances, RES switches and unresolved references), an external 3DO folder
  for trackside assets, and fallback texture controls.
- **Object** provides standalone object diagnostics (polygons, MIP names,
  DYNAMIC references), external 3DO resolution and fallback texture controls.

The top bar retains **Open**, **Save Source**, **Export 3DO**, **Frame All**,
camera views, and the **.3D Source** toggle. Display keeps projection,
textures and a single detail-level selector. Assets groups palette, MIP and
external-3DO resolution; Advanced diagnostics contains BSP rendering method,
fixed camera, polygon-offset lookup, benchmark and performance information.
The Source pane still opens beside the GPU viewport, with the same live
compilation, save, and export behavior. When Save Source or Export 3DO is
used before source has been prepared, the Source pane opens and generates it
first; repeat the requested action once preparation is complete.

The viewer suggests **Car** for recognized car geometry or individual-car
appearance wrappers, **Track** for clearly named track models (including
`track.3do` and `RENO.3D`), and leaves ambiguous filenames in the
currently selected workspace rather than guessing their semantics.
Select the correct mode manually for models whose names give no reliable hint.
The mode is a UI organization choice, not a conversion between file formats.

## Controls

- Left mouse drag: orbit
- Shift + left drag or middle drag: pan
- Mouse wheel: zoom
- 3D, Top, Front, Side buttons: standard orthographic views
- Perspective: toggle orthographic/perspective projection. Perspective BSP
  uses the real finite camera; orthographic BSP uses the *parallel viewing
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
  GPU mesh bounding box: projection accounts for the mesh center and scale.
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
- **.3D Source**: open the side-by-side N3 source tab. For a loaded .3D
  file it retains the original text and comments; for a binary .3do it
  generates editable N3 declarations using the same exporter as CPU CAD.
  Source generation is lazy and runs on a background thread. The GPU
  viewport stays visible and interactive beside the editor.
- **Live updates**: after 650 ms without typing, the existing N3 compiler
  runs on a worker and rebuilds geometry/atlases if the new source is valid.
  Only the latest text revision may replace the GPU model. Invalid source
  highlights its error line and retains the last valid scene and camera.
  **Apply now** compiles immediately. Colors, XYZ, UV, plane definitions,
  LIST/BSP, DYNAMIC and RES edits are subject to the same N3 compiler rules
  as the CPU editor.
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
  selected polygon triangles in the model's back-to-front order, with GPU
  depth testing disabled. **BSP selection + GPU depth** uses the same selected
  triangles with depth testing. **All polygons + GPU depth** ignores BSP/LOD
  and is the legacy full-geometry diagnostic mode.
- **Detail level / SWITCH DISTANCE / RES**: **Automatic** (default)
  computes the distance from the camera to each RES anchor in local model
  coordinates, including transformed DYNAMIC objects. Choose **Manual
  distance** to enter a threshold in original model units, or **Show all
  detail levels** to render alternate branches for diagnosis.
  Auto uses Euclidean distance as an approximation of the engine's actual
  switch logic, not a claim of exact in-game LOD thresholds.
- **Open PCX palette…**: load a normal indexed 8-bit PCX with a 256-color
  VGA palette trailer (e.g. `sunny.pcx`). The bundled `gamepal.pcx` is used
  on startup; **Default palette** restores it. Palette changes recolor
  both plain polygons and MIPs instantly, without rebuilding geometry.
- **Individual car 3DO**: open a per-driver `.3do` directly, such as
  `cit74.3do`. As in the CPU editor, the root MATERIAL references a
  **RECOLOR record at body offset zero**, not a renderable child. The GPU
  loader reads it using the existing `car_appearance` decoder and opens
  the referenced base geometry (e.g. `indycar.3do`) separately. It maps
  only *base car* polygon color indices, preserving independent wheel and
  helmet colors and textures. The livery's indexed MIP pixels are unchanged.
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
  unchanged atlas layout, only the GPU's integer texture is reuploaded:
  geometry, BSP indices and camera are retained. If a MIP's dimensions/layout
  change, the worker rebuilds the UV attributes before replacing the VBO.
  Saving edits to the MIP in your image/conversion tool then pressing R
  previews a revised livery. No file writing or automatic file watcher.
- **3DO objects folder…**: optionally choose a folder containing the model's
  DYNAMIC/external `.3do` references. Models beside the parent and common
  adjacent object directories are also searched automatically. Nested child
  models use their own BSP planes, camera-local coordinates and RES anchors.
  Reused objects receive separate translated/rotated instances. Missing
  models and cyclic references are reported without preventing the parent
  from loading. No source objects are written.
- **MIP folder…**: choose a folder containing the model's named `.mip`
  files. The loader also searches the model's directory and its `textures`,
  `mip` and `mips` subfolders, without case-sensitive filename assumptions.
  `MATERIAL` associations in the 3DO/N3 choose the texture for POLY [T]
  faces. **Fallback MIP…** maps otherwise-unassigned textured polygons to
  an explicitly chosen file; **Clear fallback** reverses this override.
  Changing MIPs rebuilds the read-only mesh/atlas, not the source file.
- **Textures**: toggle sampled MIP colors versus flat polygon palette colors.
  **Repeat UV** optionally wraps raw texel UVs, which clamp by default.
  The status line reports loaded/missing MIPs, mapped faces and atlas size.
- **Polygon body offset** (Advanced diagnostics): type the polygon's **3DO body offset** in decimal or 0x
  hexadecimal (as displayed by the CAD structure inspector) to see whether
  it is selected by BSP and the chosen LOD. Selected does not necessarily
  mean pixel-visible: other drawn polygons can still cover it.

Loading and mesh creation run on a worker thread; the OpenGL context and
buffer upload stay on Qt's GUI thread.

## Architecture and what is measured

mesh.py builds **one packed, interleaved float32 XYZ/RGB/index/UV/atlas-rect
buffer** from original Papyrus polygons and the selected PCX palette. It handles
triangles, convex quads, and concave polygons through ear clipping;
degenerate faces are skipped and fallback fans are explicitly counted.
Large track coordinates are recentered/scaled for GPU float precision.

main.py uploads the XYZ/RGB/UV vertex buffer **once when the file opens**.
The worker discovers nested DYNAMIC and negative external references and
flattens their transformed instances into the same GPU buffer, preserving
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
single GPU `GL_R8UI` atlas. The fragment shader selects nearest texels
using original raw UV coordinates, then looks up their colors in a separate
256x1 PCX palette texture. No per-polygon draw calls or color conversion
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
overlays. In GPU-depth modes the depth buffer is used as a diagnostic
comparison. Vertex winding is not used for automatic GL backface culling:
FACE/BSP plane rules control branch eligibility.

It reports:
- N3/3DO parse milliseconds: includes binary parsing but excludes
  editor-only BSP plane/polygon anchor inference
- Triangle-mesh construction milliseconds: CPU-side work
- GPU upload milliseconds: one-time blocking upload and synchronization
- Displayed FPS: Qt frame-swapped events during continuous repaint
- Polygon/triangle counts, skipped/fallback faces, and VBO memory

Numbers are *not* directly comparable to Tk's profiler unless the same model,
resolution, visibility and benchmark procedure are used on the same machine.

## Intentional limitations

The GPU viewer has editable N3 source and explicit .3D/.3DO export,
but does **not yet** provide mouse polygon picking or PMP sprites.
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

The GPU preview path suppresses only *plane-anchor inference*, an editor
safety feature. Previewing and switching workspaces never writes original
source files or .3DO assets. The explicit .3D save and compiled .3DO export
commands are the only model-writing operations; validate generated binaries
in the game before use.

A successful GUI smoke test verifies that an OpenGL 3.3 context can draw
a model. **No speedup is claimed until measured on RENO.**
If startup fails, check the GPU driver and that Qt has created a desktop
OpenGL context; software OpenGL can also be substantially slower.
