# Profiling the 3DO CAD editor

Profiling is **off by default**. Enable it for a representative session, preferably
with the large RENO.3D track model and a smaller building for comparison.

Windows PowerShell, from the `icr2_3do_cad` directory:

```powershell
$env:ICR2_CAD_PROFILE="1"
$env:ICR2_CAD_PROFILE_OUTPUT="cad_performance.json"
python icr2_3do_cad.py "C:\path\to\RENO.3D"
```

Windows CMD:

```bat
set ICR2_CAD_PROFILE=1
set ICR2_CAD_PROFILE_OUTPUT=cad_performance.json
python icr2_3do_cad.py C:\path\to\RENO.3D
```

Perform the same steps for each model: load; orbit continuously for 10 seconds;
zoom; toggle texture visibility; select a polygon; edit a vertex; make a valid
change in the live source tab; wait for compilation; then close the editor.
A JSON report is written on successful file load and again on close.

## Large-track optimization pass

This optimization pass targets the specific costs discovered while reviewing
the original RENO.3D track (about 4,365 polygon commands and 1,083
FACE/BSP commands). The old plane-association stage repeated expensive
non-collinear polygon triplet searches for every BSP plane. The optimized
stage prepares each polygon's original geometry once, reuses it for all
planes, and computes each plane's normal length once. The conservative
original 0.5-unit coplanarity criterion, candidate ordering, and binary
records remain unchanged.

For track-sized vertex clouds (1,200 or more **active** vertices), the
renderer now builds the pale-blue/orange vertex dots in a single RGBA
`PhotoImage` overlay rather than creating thousands of Tk ovals. The
selected vertex remains a separate highlighted marker. Pixel-based picking
still tests **every active vertex**, including overlapping and non-rendered
vertices. Smaller models and installations without Pillow retain their
original canvas markers.

GUI loading inserts the vertex list into Tk in 512-item batches, reducing
Python-to-Tcl calls without changing offsets, names, or row ordering.
Camera basis vectors are cached by azimuth/elevation, eliminating repeated
trigonometric calculations for vertices in the same camera pose.

New profiling stages:
- `model.parse_records`: reading the binary hierarchy, polygons and vertices
- `model.associate_planes`: safe BSP-to-polygon association
- `ui.vertex_list`: filling vertex inspector rows
- `viewport.vertex_points`: rendering individual dots or the RGBA overlay

### Verification

Regression tests compare every stored plane candidate, anchor, distance and
confidence to the old uncached algorithm for real fixture models and verify
byte-identical no-op saves. GUI tests verify marker overlay activation, full
vertex picking, and unmodified listbox row ordering.

**These tests prove semantic equivalence, not a specific speedup.** RENO
itself is not committed to GitHub tests. To measure the actual improvement
on your machine, run the same benchmark procedure before and after this PR,
using separate JSON outputs. The remaining polygon/texture rendering uses
Tk's CPU canvas; GPU rendering and more extensive scene culling would still
require a larger architectural change.

## Measurements

- `load.read_n3`, `load.compile_n3`, `load.parse_3do`: file input and compilation
- `load.populate_ui`, `load.source_tab`: list/inspector/source initialization
- `viewport.redraw`: full CPU/Tk draw time, including textures and labels
- `viewport.redraw_requests`: coalesced redraw request count, **not** FPS
- `viewport.vertex_labels`, `viewport.pmp_sprite`: detailed draw contributors
- `ui.polygon_list`, `ui.geometry_targets`, `ui.raw_inspector`, `ui.dynamic_list`: inspector costs
- `source.background_compile`, `source.apply_compiled`, `source.sync_model`: live source pipeline

Each stage has count, total, mean, median, p95, and maximum milliseconds.
Some stages are nested and **must not be summed**. Viewport redraw durations
measure the Tk CPU-side drawing operation, not GPU scanout or true FPS.
Compilation is timed in its background worker, not the UI thread.

Reports contain aggregate timings and stage names only, not model paths,
vertex coordinates, source code, or texture data. The output file is
overwritten on the next report; use distinct names for each benchmark.
Performance depends on model complexity, display resolution, texture settings,
hardware, and operating system. No performance claims should be made without
comparing actual reports.

Use results to decide whether to optimize compilation, UI list population,
texture rasterization, or replace the renderer. The instrumentation does not
change geometry, BSP traversal, binary exports, or save behavior.
