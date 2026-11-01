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
