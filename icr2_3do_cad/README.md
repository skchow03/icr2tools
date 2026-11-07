# ICR2 3DO CAD

The ICR2 3DO CAD editor is the supported application for inspecting and editing Papyrus *IndyCar Racing II* and *CART Racing* `.3D` source and `.3DO` models. It uses a PySide6 desktop interface and an OpenGL 3.3 renderer for large car, object and track models. The former Tkinter front end has been retired.

## Run

Install **Python 3.10+**, an OpenGL 3.3-capable driver and the dependencies:

```sh
python -m pip install -r icr2_3do_cad/requirements.txt
python icr2_3do_cad/icr2_3do_cad.py
python icr2_3do_cad/icr2_3do_cad.py path/to/model.3d
```

Alternatively, from inside `icr2_3do_cad/`, run `python icr2_3do_cad.py`. On Windows, `RUN_ME_WINDOWS.bat` launches this same application. No separate renderer or subfolder entry point is required.

To measure viewport performance, use `--benchmark` and optionally `--report cad_profile.json`. The normal editor does not continuously redraw when idle.

## Features

- Open compiled `.3do` files or standalone Papyrus/N3 `.3D` source; the editable source panel recompiles and updates the viewport after validation.
- Car, Track and Object workspaces; camera orbit, pan, zoom, orthographic and fixed-camera views, track-guided navigation, indexed HI/MED/LO section windows and optional skybox.
- CAD-style always-visible XYZ orientation triad (bottom-left) and extended, labeled red/green/blue XYZ guides; independent visibility and anchor controls.
- Inspect vertex and polygon source declarations, BSP/draw-order decisions, external DYNAMIC models, MIP materials, PMP sprites and visibility.
- Import a photo, blueprint or car profile as a calibrated model-space tracing image behind the geometry (Front/Side/Top planes, opacity and alignment controls).
- Preview a separate driver `.3do` RECOLOR and body MIP on the currently editable car or car-part geometry without opening the driver's referenced carshape.
- Edit N3 source with live diagnostics, reference navigation, polygon splitting, vertex inspection, pointer renaming and scaling.
- Save source or export a newly compiled `.3do` explicitly; failed compilation does not overwrite game assets.

## Built-in Help

Choose **Help → Help Topics…** or press **F1** to open a fast, native, nonmodal **Qt Help window inside ICR2 3DO CAD**. It provides real desktop buttons for Back, Forward, Home, Search, Print and Close, plus Contents, an A–Z Index, and live full-text Search. Topic links, history, and printing stay inside the application: no web browser or WebEngine process is launched. Closing and reopening Help reuses the same window.

Help reads the self-contained [HTML user manual](USER_MANUAL.html) locally as documentation, not as a webpage. Keep `USER_MANUAL.html` beside `icr2_3do_cad.py` when distributing source; frozen/PyInstaller builds must bundle the file in their data directory or beside the executable. The HTML can also be read on its own if necessary, but F1 opens the native Qt window.

## World-axis guides and orientation gizmo

The viewport now shows two independent CAD-style orientation aids by default:

- **Corner XYZ gizmo**: a mouse-transparent red X, green Y and blue Z
  direction triad in the bottom-left, rotating with the camera in
  3D, Front, Side, Top and TRK/fixed-camera views. It stays visible
  regardless of model position or zoom.
- **Extended XYZ guides**: colored positive-axis lines, faint dashed
  negative-axis lines and labels that extend across the visible viewport.
  By default, guides pass through the **camera's view focus**, not necessarily
  raw world XYZ (0,0,0), to remain useful while panning and zooming.
  Choose **Model bounding-box center** or **Raw Papyrus XYZ origin**
  under View → Display Settings if you need those exact anchor locations.

Toggle either overlay independently under **View → Display Options** or
**View → Display Settings**. The controls persist after restarting CAD.
These are transparent, nonselectable UI guides only; they do not alter
the model, tracing-image calibration, BSP, rendered geometry or exports.

## Move vertices directly in the 3D viewport

Choose **Pick → Vertices**, select a root-model vertex, then enable
**Move vertex** beside the Pick selector. Red X, green Y and blue Z arrows
appear at the selected vertex. Drag one visible arrow to move the point
**along that axis only**, in either perspective or orthographic view.
Shift while dragging makes movement ten times finer; press **Esc** to
cancel without modifying anything. An axis pointing directly at the
camera cannot be manipulated in that view: orbit or choose another
orthographic view.

The translucent Qt gizmo shows the proposed raw Papyrus XYZ and a dashed preview of incident polygon edges immediately.
The geometry itself remains unchanged while dragging, to avoid repeated
expensive N3 compilation. **Release** the mouse to modify the selected
vertex's XYZ fields in the canonical .3D Source, apply the existing
optional symmetry rules (including ambiguity prompts), and recompile the
full mesh. View → Display Settings has a **Vertex move snap step** choice
(1, 10, 100, 1000 raw units; default 1). Changes are undoable with
Ctrl+Z. Save/Export is explicit; a drag never overwrites an original file.

The editor respects implicit or explicit ICR2_COORD_SCALE, source
comments, declaration names and T/U/V fields. Moving a vertex affects
all polygons that reference its pointer. No arbitrary anonymous inline
polygon vertex or referenced external DYNAMIC child may be dragged.
Move mode starts OFF when opening a new model, and normal viewport
selection/orbit/pan continue to work when not dragging a handle.

## Symmetrical vertex editing (optional)

Clicking a vertex in the viewport navigates to its .3D Source declaration,
highlighting the **whole row green**, as with a visible POLY.

The new **Symmetrical vertex editing** checkbox above the source is
**OFF by default every time a model opens**. Set a mirror plane:
X=constant (YZ), Y=constant (XZ) or Z=constant (XY). The raw model
plane coordinate defaults to 0; tolerance defaults to 0 (exact matches).

At Apply or the normal source debounce, the editor pairs each modified
named vertex using its *last validated* XYZ coordinates, then updates
the opposite vertex to the mirrored new XYZ. **Only XYZ numbers change;
texture U/V, labels, comments and polygon statements are preserved.**
Automatic edits are grouped for Undo and logged. Missing counterparts and
centerline points moved off-plane trigger warnings; multiple matching
vertices present a choice of labeled source rows, which can be canceled.
If both halves were edited manually, neither is silently overwritten.

This is for matched existing N3 vertices, not an operation that creates
new geometry. Structural edits and whole-model scaling are independent
of per-vertex mirroring.

## Trace geometry over a calibrated reference image

Open a car, part, building or trackside object. Choose **Assets → Load
Tracing Reference Image…**, then choose a PNG/JPEG/other supported image.
An independent tracing plane is added behind the editable geometry. The
nonmodal calibration window stays open alongside the source editor.

Choose **Side (Y/Z)**, **Front (X/Z)** or **Top (X/Y)** and click
**Align viewport to this plane (orthographic)**. Use **Pick A** and
**Pick B** to select two points on the photograph (for example the two
wheel centers), then enter their actual distance in **raw model units**.
The image scales and rotates so A→B aligns horizontally with the entered
distance. Move the reference using its U/V origin, or manually adjust the
scale, rotation, opacity and visibility. The initial image is fitted
approximately to the model's bounding box before calibration.

To reopen the controls use **Assets → Adjust Tracing Reference…**;
**Remove Tracing Reference** discards the image. The image is purely a
preview, not a material, model polygon, source edit or exported asset.
It stays aligned while orbiting/zooming or editing source. Opening an
unrelated model clears the active overlay, but **saved reference profiles**
can restore the full calibration on any model, including after restarting CAD.

Use **Save as…** in the calibration window (or **Assets → Save Tracing
Reference Profile…**) to name a reusable profile. Select a saved name in
the dialog and click **Restore**, or use **Assets → Restore Saved Tracing
Profile…**. The default places the same calibrated image and model-unit
offset relative to the **new model's center**; choose **Keep exact saved
model coordinates** if you need the original absolute U/V instead. Delete
profiles from the dialog or Assets menu without deleting the actual image.

Profiles are saved in the user's application configuration directory
(`ICR2Tools/3DOCAD/tracing_profiles.json`), **not** in a game model or
track folder. They reference image files by absolute path; moving an
image breaks that profile until the image is restored to its saved path.
Images are not embedded, copied, or uploaded.

## Preview a driver appearance on an editable car model

Open `roadcar.3do`, `indycar.3do`, a wheel, or another car-part geometry file.
Choose **Assets → Apply Individual-Car RECOLOR / MIP…**, then choose an
individual-car file such as `cit74.3do`. The **Car Settings** dialog offers the
same command, plus **Clear appearance overlay**.

The viewport applies the driver file's RECOLOR mapping and resolves its named
body MIP relative to the driver file, while you continue editing the original
geometry and .3D Source. A wrapper's own geometry reference is intentionally
ignored for this explicit overlay: `cit74.3do` can be previewed on
`roadcar.3do` despite referencing `indycar.3do`. External wheel/helmet
materials remain independent. The overlay is **preview-only**: exporting
compiled geometry does not embed the wrapper's RECOLOR/MIP or rewrite it.
If a body MIP is missing, the MIP diagnostics identify it. A separate manual
body-MIP override takes precedence until cleared.

**Important:** Exporting edited source recompiles a model; binary record offsets may change. Back up originals, validate new assets, and test compiled models in-game. The renderer is a diagnostic approximation, not a game-exact rasterizer.

See the [full user guide](USER_GUIDE.md), [N3 interchange notes](N3_INTERCHANGE.md), [development and binary-safety notes](DEVELOPMENT.md) and [performance guide](PERFORMANCE.md).

## Tests

From `icr2_3do_cad/`:

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

GUI/OpenGL tests require a display and their dependencies. On headless Linux, use `xvfb-run` with Mesa software rendering. GitHub Actions exercises both the general regression suite and an OpenGL framebuffer smoke test.

The bundled `fixtures/` and `gamepal.pcx` are required by the editor and tests.
