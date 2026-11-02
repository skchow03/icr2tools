"""Offscreen/Xvfb smoke test of a *real* Qt/ModernGL GPU draw.

Run from repository root:
  xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 python \
      icr2_3do_cad/gpu_viewer/smoke_test.py icr2_3do_cad/fixtures/roadcar.3do

Requires the optional gpu_viewer/requirements.txt dependencies.
"""
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from gpu_viewer.main import Window


def run(path):
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([sys.argv[0]])
    window = Window(path, benchmark=True)
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
                    f"observed {view.fps:.1f} FPS; screenshot {screenshot}",
                    flush=True,
                )
            timer.stop()
            window.close()
            app.quit()
        elif elapsed > 45:
            result["error"] = (
                f"timeout loading or drawing: {window.stats_label.text()} | "
                f"ctx={view._ctx is not None}, "
                f"buffer={view._vao is not None}, frames={view._frame_count}"
            )
            timer.stop()
            window.close()
            app.quit()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(100)
    app.exec()
    if not result["ok"]:
        raise SystemExit(result["error"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_test.py <model.3do>")
    run(sys.argv[1])
