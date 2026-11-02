# Experimental GPU Viewer (read-only)

This is **a separate performance prototype**, not a replacement for the
Tkinter 3DO CAD editor. It reuses its production N3 compiler and 3DO Model
parser and displays local polygon geometry using PySide6 QOpenGLWidget +
ModernGL (OpenGL 3.3).

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

## Controls

- Left mouse drag: orbit
- Shift + left drag or middle drag: pan
- Mouse wheel: zoom
- 3D, Top, Front, Side buttons: standard orthographic views
- Perspective: toggle orthographic/perspective projection
- Frame All (F): recenter and fit the model
- Open: load a different .3D or .3do without restarting

Loading and mesh creation run on a worker thread; the OpenGL context and
buffer upload stay on Qt's GUI thread.

## Architecture and what is measured

mesh.py builds **one packed, interleaved float32 XYZ/RGB buffer**
from original Papyrus polygons and the gamepal.pcx palette. It handles
triangles, convex quads, and concave polygons through ear clipping;
degenerate faces are skipped and fallback fans are explicitly counted.
Large track coordinates are recentered/scaled for GPU float precision.

main.py uploads that buffer **once when the file opens**. Orbital camera
movement only changes a 4x4 matrix; it never reparses N3, rebuilds BSP,
or transfers polygon geometry to the GPU.

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

This **does not yet** include editing, picking, source tabs, MIP texture
sampling, PMP sprites or externally referenced DYNAMIC model geometry.
It displays **local polygon geometry in flat indexed colors**, with ordinary
GPU depth testing. Papyrus BSP/painter order, LOD switching and track-only
LINE commands are **not faithfully reproduced**. Overlapping scenery may
therefore look different from the game or Tk preview.

The read-only GPU path suppresses only *plane-anchor inference*, an editor
safety feature. It never modifies source coordinates, .3D comments or .3DO
binary output. Do not save game assets from this prototype.

A successful GUI smoke test verifies that an OpenGL 3.3 context can draw
a model. **No speedup is claimed until measured on RENO.**
If startup fails, check the GPU driver and that Qt has created a desktop
OpenGL context; software OpenGL can also be substantially slower.
