# Experimental GPU Viewer (read-only)

This is **a separate performance prototype**, not a replacement for the
Tkinter 3DO CAD editor. It reuses its production N3 compiler and 3DO Model
parser and displays local polygon geometry using PySide6 QOpenGLWidget +
PyOpenGL (OpenGL 3.3).

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
- **Render**: **Papyrus BSP painter** (default) walks original FACE/FACE2/
  BSPF/BSPA/BSP2/BSPN nodes from the actual camera position and paints
  selected polygon triangles in the model's back-to-front order, with GPU
  depth testing disabled. **BSP selection + GPU depth** uses the same selected
  triangles with depth testing. **All polygons + GPU depth** ignores BSP/LOD
  and is the legacy full-geometry diagnostic mode.
- **LOD distance (game units)**: chooses RES/SWITCH DISTANCE branches. Defaults
  to 0 (near); this is a **manual** model-unit value, not a simulation of
  ICR2's dynamically evaluated per-object LOD distances. Check **All LOD
  branches** to inspect every branch even though the game would not do so.
- **Open PCX palette…**: load a normal indexed 8-bit PCX with a 256-color
  VGA palette trailer (e.g. `sunny.pcx`). The bundled `gamepal.pcx` is used
  on startup; **Default palette** restores it. Palette changes recolor
  both plain polygons and MIPs instantly, without rebuilding geometry.
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
- **Polygon @**: type the polygon's **3DO body offset** in decimal or 0x
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

main.py uploads the XYZ/RGB vertex buffer **once when the file opens**.
The parsed Model tree remains in memory for read-only plane traversal.
Orbit/pan/zoom updates the view matrix **and**, in BSP modes, re-evaluates
the original BSP node side tests using the real camera location in unscaled
Papyrus coordinates. A single `uint32` **element/index buffer** is reordered
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

This **does not yet** include editing, picking, source tabs, PMP sprites
or externally referenced DYNAMIC model geometry. It displays local polygon
geometry with indexed palette colors and optional 8-bit MIP texture sampling.
Track-only LINE commands are **not rendered**, and exact Papyrus game
rasterization, frustum/near-plane clipping, mip-level switching, per-object
LOD evaluation, alpha/transparent texels, and display budgets have not been
reconstructed. BSP side tests and painter ordering reuse the editor's
existing reverse-engineered interpretation (not a verified reproduction
of the original game executable). Overlapping scenery can still look
different from ICR2, particularly with transparency or external objects.
Never infer that a BSP-selected polygon is completely visible on screen.

The read-only GPU path suppresses only *plane-anchor inference*, an editor
safety feature. It never modifies source coordinates, .3D comments or .3DO
binary output. Do not save game assets from this prototype.

A successful GUI smoke test verifies that an OpenGL 3.3 context can draw
a model. **No speedup is claimed until measured on RENO.**
If startup fails, check the GPU driver and that Qt has created a desktop
OpenGL context; software OpenGL can also be substantially slower.
