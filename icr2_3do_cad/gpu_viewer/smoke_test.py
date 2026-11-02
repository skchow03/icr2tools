"""Offscreen/Xvfb smoke test of a *real* Qt/ModernGL GPU draw.

Run from repository root:
  xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 python \
      icr2_3do_cad/gpu_viewer/smoke_test.py icr2_3do_cad/fixtures/roadcar.3do

Requires the optional gpu_viewer/requirements.txt dependencies.
"""
import os
import shutil
import struct
import tempfile
import faulthandler
faulthandler.enable()
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from gpu_viewer.main import Window


def _make_smoke_child(path):
    """Tiny real binary external 3DO to exercise DYNAMIC GPU draws."""
    body = bytearray()
    refs = []
    for xyz in ((0,0,0), (20000,0,0), (0,20000,0)):
        refs.append(len(body))
        body.extend(struct.pack('<4i', 0, *xyz))
    poly = len(body)
    body.extend(struct.pack('<3i', -(1<<31)+1, 110, 2))
    for ref in refs:
        body.extend(struct.pack('<i', ref))
    root = len(body)
    body.extend(struct.pack('<3i', -(1<<31)+11, 1, poly))
    path.write_bytes(struct.pack('<5i', len(body), root, 0, 0, 0) + body)


def run(path):
    # The stock roadcar references wheels and helmet files not shipped with
    # fixtures. Supply synthetic children in a temporary folder to make the
    # graphics test exercise nested resolution and actual GPU index draws.
    scratch = tempfile.TemporaryDirectory()
    source = Path(path)
    dynamic_test = source.name.casefold() == 'roadcar.3do'
    if dynamic_test:
        local = Path(scratch.name) / source.name
        shutil.copyfile(source, local)
        for name in ('SFRONT.3DO', 'SREAR.3DO', 'HELMET.3DO'):
            _make_smoke_child(local.parent / name)
        path = local
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([sys.argv[0]])
    window = Window(path, benchmark=True)
    # roadcar has POLY [T] but no MATERIAL; exercise explicit MIP fallback.
    window.fallback_mip = ROOT / "fixtures" / "ind96.mip"
    # Ensure QOpenGLWidget is deleted while QApplication/GLX remain alive;
    # PySide6 6.12 can bus-error during interpreter-finalization otherwise.
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.resize(900, 680)
    window.show()
    started = perf_counter()
    result = {"ok": False, "error": "timed out"}
    def check():
        elapsed = perf_counter() - started
        view = window.viewer
        if (window._info and view._vao is not None and
                view._frame_count >= 8 and elapsed >= 1.25):
            image = view.grabFramebuffer()
            if image.isNull() or image.width() < 200 or image.height() < 200:
                result["error"] = "Empty OpenGL framebuffer"
            elif view._mesh.triangle_count < 1:
                result["error"] = "No local triangles drawn"
            elif view._index_count < 1 or not view._visible_set:
                result["error"] = "BSP painter did not upload visible polygon indices"
            elif (not view._atlas.polygon_rects or
                  view._atlas_texture is None or
                  view._palette_texture is None):
                result["error"] = "Indexed MIP atlas / palette was not uploaded"
            elif (dynamic_test and
                  (view._scene.loaded_instances != 5 or
                   view._mesh.polygon_count <= len(view._model.polygons) or
                   view._visibility_info.get("instances_visited", 0) != 6)):
                result["error"] = "DYNAMIC child geometry/BSP order missing in GPU draw"
            elif view.fps <= 0:
                result["error"] = "No measured Qt frame-swapped FPS"
            else:
                # Verify an actual rendered model, not merely a clear-color
                # framebuffer. Sample a coarse grid to avoid expensive reads.
                colors = set()
                for y in range(0, image.height(), max(1, image.height() // 32)):
                    for x in range(0, image.width(), max(1, image.width() // 32)):
                        colors.add(image.pixelColor(x, y).rgb())
                if len(colors) < 2:
                    result["error"] = "Frame contains only background; geometry invisible"
                    timer.stop()
                    window.close()
                    app.quit()
                    return
                screenshot = Path(os.environ.get(
                    "GPU_SMOKE_SCREENSHOT", "gpu_viewer_smoke.png"))
                image.save(str(screenshot))
                result["ok"] = True
                result["error"] = ""
                print(
                    f"GPU smoke passed: {view._mesh.polygon_count} polygons; "
                    f"{view._mesh.triangle_count} triangles; "
                    f"upload {view.upload_ms:.1f} ms; "
                    f"MIP faces {len(view._atlas.polygon_rects)}; "
                    f"external instances {view._scene.loaded_instances}; "
                    f"observed {view.fps:.1f} FPS; screenshot {screenshot}",
                    flush=True,
                )
            timer.stop()
            print("Closing Qt window",flush=True)
            window.close()
            print("Qt window closed",flush=True)
            app.quit()
        elif elapsed > 45:
            result["error"] = (
                f"timeout loading or drawing: {window.stats_label.text()} | "
                f"ctx={view._program is not None}, "
                f"buffer={view._vao is not None}, frames={view._frame_count}"
            )
            timer.stop()
            window.close()
            app.quit()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(100)
    print("Entering Qt event loop",flush=True)
    app.exec()
    print("Qt event loop exited",flush=True)
    scratch.cleanup()
    if not result["ok"]:
        raise SystemExit(result["error"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_test.py <model.3do>")
    run(sys.argv[1])
