"""Experimental GPU viewport for ICR2 track and car geometry.

Standalone read-only prototype: uses the production N3/3DO parser, but NOT
Tkinter's per-polygon renderer. Requires PySide6, moderngl and numpy.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from time import perf_counter
from collections import deque

import numpy as np

# Allow: python icr2_3do_cad/gpu_viewer/main.py RENO.3D
CAD_ROOT = Path(__file__).resolve().parents[1]
if str(CAD_ROOT) not in sys.path:
    sys.path.insert(0, str(CAD_ROOT))

try:
    import moderngl
    from PySide6.QtCore import Qt, QThread, Signal, QTimer
    from PySide6.QtGui import QSurfaceFormat, QShortcut, QKeySequence
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
        QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
    )
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except ImportError as exc:
    raise SystemExit(
        "GPU viewer dependencies are missing. Run:\n"
        "  python -m pip install -r icr2_3do_cad/gpu_viewer/requirements.txt\n"
        f"Original import error: {exc}"
    ) from exc

from gpu_viewer.mesh import MeshData, make_mesh, read_palette


VERTEX_SHADER = """
#version 330 core
in vec3 in_pos;
in vec3 in_color;
uniform mat4 u_mvp;
out vec3 v_color;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_color = in_color;
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec3 v_color;
out vec4 fragColor;
void main() {
    fragColor = vec4(v_color, 1.0);
}
"""


def _unit(vector):
    length = float(np.linalg.norm(vector))
    if length < 1e-10:
        raise ValueError("Camera axis is degenerate")
    return vector / length


def camera_view(azimuth, elevation, distance, target):
    """Row-major world-to-view matrix, using Z-up like the existing editor."""
    eye_direction = np.array((
        math.cos(elevation)*math.sin(azimuth),
        -math.cos(elevation)*math.cos(azimuth),
        math.sin(elevation),
    ), dtype=np.float64)
    forward = -_unit(eye_direction)
    right = np.cross(forward, np.array((0.0, 0.0, 1.0)))
    if np.linalg.norm(right) < 1e-8:
        right = np.array((1.0, 0.0, 0.0))
    right = _unit(right)
    up = _unit(np.cross(right, forward))
    eye = np.asarray(target, dtype=np.float64) + eye_direction * distance
    view = np.identity(4, dtype=np.float64)
    view[0, :3] = right
    view[1, :3] = up
    view[2, :3] = -forward
    view[0, 3] = -np.dot(right, eye)
    view[1, 3] = -np.dot(up, eye)
    view[2, 3] = np.dot(forward, eye)
    return view, right, up


def ortho_projection(half_height, aspect, near, far):
    half_width = max(half_height * aspect, 0.01)
    matrix = np.identity(4, dtype=np.float64)
    matrix[0, 0] = 1.0 / half_width
    matrix[1, 1] = 1.0 / half_height
    matrix[2, 2] = -2.0 / (far - near)
    matrix[2, 3] = -(far + near) / (far - near)
    return matrix


def perspective_projection(aspect, near, far):
    factor = 1.0 / math.tan(math.radians(60.0) / 2.0)
    matrix = np.zeros((4, 4), dtype=np.float64)
    matrix[0, 0] = factor / max(aspect, 0.01)
    matrix[1, 1] = factor
    matrix[2, 2] = -(far + near) / (far - near)
    matrix[2, 3] = -2.0 * far * near / (far - near)
    matrix[3, 2] = -1.0
    return matrix


class LoadWorker(QThread):
    ready = Signal(object, object)
    failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)

    def run(self):
        try:
            # Do not import Qt or create GL resources on this worker thread.
            from three_do import Model
            from n3_compile import compile_n3_text
            t0 = perf_counter()
            if self.path.suffix.lower() == ".3d":
                text = self.path.read_text(encoding="utf-8-sig")
                model, _ = compile_n3_text(
                    text, self.path, associate_planes=False)
            elif self.path.suffix.lower() == ".3do":
                model = Model(self.path, associate_planes=False)
            else:
                raise ValueError("Open a .3D or .3DO file")
            parse_ms = (perf_counter() - t0) * 1000
            palette = read_palette(CAD_ROOT / "gamepal.pcx")
            mesh = make_mesh(model, palette)
            stats = {
                "file": self.path.name,
                "parse_ms": parse_ms,
                "mesh_ms": mesh.build_ms,
                "model_polygons": len(model.polygons),
                "model_vertices": len(model.vertices),
                "model_planes": len(model.planes),
                "external_objects": len(model.dynamics),
                "mips": len(model.mip_names),
            }
            # Do not keep Model around. UI only needs the flattened buffer.
            self.ready.emit(mesh, stats)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class GLViewport(QOpenGLWidget):
    statsChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(600, 400)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(False)
        self._ctx = None
        self._resources_released = False
        self._shader = None
        self._vbo = None
        self._vao = None
        self._mesh = None
        self.upload_ms = None
        self.azimuth = math.radians(35)
        self.elevation = math.radians(28)
        self.target = np.zeros(3, dtype=np.float64)
        self.distance = 4.0
        self.half_height = 1.6
        self.perspective = False
        self._drag = None
        self._frametimes = deque(maxlen=240)
        self._frame_count = 0
        self.fps = 0.0
        self.frameSwapped.connect(self._on_frame_swapped)

    def initializeGL(self):
        try:
            self._ctx = moderngl.create_context(require=330)
            self._resources_released = False
            # Qt can destroy/re-create QOpenGLWidget contexts during native
            # teardown. Release our VAO/VBO/program while its context is alive.
            self.context().aboutToBeDestroyed.connect(self.shutdown_gl)
            self._shader = self._ctx.program(
                vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
            self._ctx.enable(moderngl.DEPTH_TEST)
            if self._mesh is not None:
                self._upload_mesh()
        except Exception as exc:
            self._ctx = None
            self.statsChanged.emit(f"OpenGL initialization failed: {exc}")
            raise

    def shutdown_gl(self):
        """Release only resources owned by ModernGL while Qt's GL context lives.

        QOpenGLWidget owns its framebuffer; release only our own shader and
        buffer objects. This may be called both from close and from Qt's
        aboutToBeDestroyed signal.
        """
        if self._ctx is None or self._resources_released:
            return
        self._resources_released = True
        self.makeCurrent()
        try:
            for name in ("_vao", "_vbo", "_shader"):
                resource = getattr(self, name, None)
                if resource is not None:
                    resource.release()
                    setattr(self, name, None)
            self._ctx.finish()
        finally:
            self.doneCurrent()

    def set_mesh(self, mesh: MeshData):
        self._mesh = mesh
        self._frametimes.clear()
        self._frame_count = 0
        self.frame_all()
        if self._ctx is not None:
            self.makeCurrent()
            try:
                self._upload_mesh()
            finally:
                self.doneCurrent()
        self.update()

    def _upload_mesh(self):
        if self._ctx is None or self._shader is None:
            return
        started = perf_counter()
        # Geometry is only re-uploaded when opening a new model, never
        # during orbit, pan, zoom, or continuous-FPS benchmarking.
        if self._vao is not None:
            self._vao.release()
            self._vao = None
        if self._vbo is not None:
            self._vbo.release()
            self._vbo = None
        if self._mesh is not None and self._mesh.vertices.size:
            self._vbo = self._ctx.buffer(
                np.ascontiguousarray(self._mesh.vertices, dtype=np.float32).tobytes())
            self._vao = self._ctx.vertex_array(
                self._shader, [(self._vbo, "3f 3f", "in_pos", "in_color")])
            # A one-time finish makes upload timing honest. Never use this
            # inside paintGL, where it would stall rendering each frame.
            self._ctx.finish()
        self.upload_ms = (perf_counter() - started) * 1000
        self.statsChanged.emit(f"GPU upload: {self.upload_ms:.1f} ms")

    def paintGL(self):
        if self._ctx is None:
            return
        # QOpenGLWidget has already made its Qt-owned FBO current.
        # Do NOT bind 0, call ctx.screen.use(), or wrap Qt's FBO in a
        # ModernGL Framebuffer: doing so can interfere with Qt teardown.
        w = max(1, int(self.width() * self.devicePixelRatioF()))
        h = max(1, int(self.height() * self.devicePixelRatioF()))
        self._ctx.viewport = (0, 0, w, h)
        self._ctx.enable(moderngl.DEPTH_TEST)
        self._ctx.disable(moderngl.CULL_FACE)
        self._ctx.clear(0.065, 0.09, 0.135, 1.0, depth=1.0)
        if self._vao is None:
            return
        aspect = w / h
        near = 0.001
        far = max(100.0, 40.0 * self.distance)
        view, _, _ = camera_view(self.azimuth, self.elevation,
                                 self.distance, self.target)
        if self.perspective:
            projection = perspective_projection(aspect, near, far)
        else:
            projection = ortho_projection(self.half_height, aspect, near, far)
        matrix = np.asarray(projection @ view, dtype=np.float32)
        # GLSL uses column-major matrices.
        self._shader["u_mvp"].write(matrix.T.tobytes())
        self._vao.render(mode=moderngl.TRIANGLES)

    def _on_frame_swapped(self):
        now = perf_counter()
        self._frame_count += 1
        self._frametimes.append(now)
        if len(self._frametimes) >= 2:
            duration = self._frametimes[-1] - self._frametimes[0]
            if duration > 0.25:
                self.fps = (len(self._frametimes) - 1) / duration

    def frame_all(self):
        self.target[:] = 0
        self.distance = 4.0
        self.half_height = 1.6
        self.update()

    def set_view(self, name):
        if name == "3D":
            self.azimuth, self.elevation = math.radians(35), math.radians(28)
        elif name == "Top":
            self.azimuth, self.elevation = 0.0, math.pi / 2
        elif name == "Front":
            self.azimuth, self.elevation = 0.0, 0.0
        elif name == "Side":
            self.azimuth, self.elevation = math.pi / 2, 0.0
        self.update()

    def wheelEvent(self, event):
        notches = event.angleDelta().y() / 120.0
        multiplier = math.exp(-notches * 0.15)
        self.half_height = min(1000.0, max(.0001, self.half_height * multiplier))
        self.distance = min(1000.0, max(.001, self.distance * multiplier))
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        self._drag = (event.position(), event.button())
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag = None
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        old, button = self._drag
        dx = event.position().x() - old.x()
        dy = event.position().y() - old.y()
        self._drag = (event.position(), button)
        if button == Qt.MouseButton.MiddleButton or (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            _, right, up = camera_view(self.azimuth, self.elevation,
                                       self.distance, self.target)
            world_per_pixel = (2 * self.half_height) / max(self.height(), 1)
            self.target += (-dx * right + dy * up) * world_per_pixel
        else:
            self.azimuth -= dx * .006
            self.elevation = max(-math.pi/2, min(math.pi/2,
                                                 self.elevation + dy*.006))
        self.update()
        event.accept()


class Window(QMainWindow):
    def __init__(self, path=None, *, benchmark=False, report_path=None):
        super().__init__()
        self.setWindowTitle("ICR2 GPU Viewer — prototype")
        self.resize(1280, 850)
        self.worker = None
        self._info = {}
        self.report_path = report_path
        self.viewer = GLViewport()
        self.load_label = QLabel("Open a .3D or .3DO model")
        self.load_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats_label = QLabel("No model loaded")
        root = QWidget()
        layout = QVBoxLayout(root)
        toolbar = QHBoxLayout()
        open_button = QPushButton("Open…")
        open_button.clicked.connect(self.open_dialog)
        toolbar.addWidget(open_button)
        frame_button = QPushButton("Frame All (F)")
        frame_button.clicked.connect(self.viewer.frame_all)
        toolbar.addWidget(frame_button)
        for name in ("3D", "Top", "Front", "Side"):
            button = QPushButton(name)
            button.clicked.connect(
                lambda checked=False, mode=name: self.viewer.set_view(mode))
            toolbar.addWidget(button)
        self.perspective_toggle = QCheckBox("Perspective")
        self.perspective_toggle.toggled.connect(self._set_perspective)
        toolbar.addWidget(self.perspective_toggle)
        self.benchmark_toggle = QCheckBox("Continuous 60 Hz benchmark")
        self.benchmark_toggle.setChecked(benchmark)
        toolbar.addWidget(self.benchmark_toggle)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        layout.addWidget(self.load_label)
        layout.addWidget(self.viewer, stretch=1)
        layout.addWidget(self.stats_label)
        self.setCentralWidget(root)
        QShortcut(QKeySequence("F"), self, activated=self.viewer.frame_all)
        self.viewer.statsChanged.connect(self.statusBar().showMessage)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._benchmark_tick)
        self.benchmark_toggle.toggled.connect(self._toggle_benchmark)
        if benchmark:
            self._timer.start()
        if path:
            # Opening after the window is visible avoids blocking Qt setup.
            QTimer.singleShot(0, lambda: self.load(path))

    def _set_perspective(self, checked):
        self.viewer.perspective = checked
        self.viewer.update()

    def _toggle_benchmark(self, checked):
        if checked:
            self.viewer._frametimes.clear()
            self._timer.start()
        else:
            self._timer.stop()

    def _benchmark_tick(self):
        self.viewer.update()
        if self._info:
            mesh = self.viewer._mesh
            upload = self.viewer.upload_ms
            self.stats_label.setText(
                f"Parse {self._info['parse_ms']:.0f} ms  |  "
                f"Mesh {self._info['mesh_ms']:.0f} ms  |  "
                f"Upload {upload:.1f} ms  |  "
                f"{mesh.polygon_count:,} polygons / {mesh.triangle_count:,} triangles  |  "
                f"FPS {self.viewer.fps:.1f} (continuous redraw)"
                if upload is not None else "Waiting for OpenGL upload…"
            )

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a Papyrus model", "",
            "Papyrus models (*.3d *.3D *.3do *.3DO);;All files (*)")
        if path:
            self.load(Path(path))

    def load(self, path):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Loading", "Finish the current load first.")
            return
        self.load_label.setText(f"Loading {Path(path).name}… (background worker)")
        self.stats_label.setText("Parsing model and building triangle buffer…")
        self.worker = LoadWorker(path)
        self.worker.ready.connect(self._loaded)
        self.worker.failed.connect(self._load_failed)
        self.worker.start()

    def _loaded(self, mesh, stats):
        self._info = stats
        self.viewer.set_mesh(mesh)
        self.load_label.setText(
            f"{stats['file']}  |  vertices {stats['model_vertices']:,}  |  "
            f"planes {stats['model_planes']:,}  |  "
            f"external placements {stats['external_objects']:,} (not drawn)")
        self.stats_label.setText(
            f"Parse {stats['parse_ms']:.0f} ms  |  "
            f"Mesh {stats['mesh_ms']:.0f} ms  |  "
            f"Upload {(self.viewer.upload_ms or 0):.1f} ms  |  "
            f"{mesh.polygon_count:,} polygons / {mesh.triangle_count:,} triangles  |  "
            f"skipped {mesh.skipped_polygons:,}  |  "
            f"fallback fans {mesh.fan_fallbacks:,}  |  "
            f"buffer {mesh.size_bytes / 1048576:.1f} MiB")
        self.statusBar().showMessage(
            "Left-drag orbit | Shift-left / middle-drag pan | Wheel zoom | F frame")

    def _load_failed(self, message):
        self.load_label.setText("Load failed; previous model preserved")
        self.stats_label.setText(message)
        QMessageBox.critical(self, "Cannot load Papyrus model", message)

    def closeEvent(self, event):
        self._timer.stop()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait()
        self.viewer.shutdown_gl()
        if self.report_path and self._info and self.viewer._mesh is not None:
            mesh = self.viewer._mesh
            payload = {
                "schema": 1,
                "renderer": "GPU prototype; Qt/OpenGL flat-colour depth test",
                "source_basename": self._info["file"],
                "parse_ms": round(self._info["parse_ms"], 3),
                "mesh_build_ms": round(mesh.build_ms, 3),
                "gpu_upload_ms": (round(self.viewer.upload_ms, 3)
                                  if self.viewer.upload_ms is not None else None),
                "presented_fps": round(self.viewer.fps, 3),
                "model_vertices": self._info["model_vertices"],
                "polygons_drawn": mesh.polygon_count,
                "triangles_drawn": mesh.triangle_count,
                "skipped_polygons": mesh.skipped_polygons,
                "fan_fallbacks": mesh.fan_fallbacks,
                "vertex_buffer_bytes": mesh.size_bytes,
            }
            try:
                target = Path(self.report_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload, indent=2) + "\n",
                                  encoding="utf-8")
                print(f"GPU benchmark report: {target}")
            except OSError as exc:
                print(f"Could not write GPU benchmark report: {exc}",file=sys.stderr)
        super().closeEvent(event)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="RENO.3D, a car .3DO, etc.")
    parser.add_argument("--benchmark", action="store_true",
                        help="Continuously redraw at 60 Hz and display FPS")
    parser.add_argument("--report", metavar="FILE",
                        help="Save load/upload/FPS measurements to JSON on close")
    args = parser.parse_args(argv)
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1])
    window = Window(args.path, benchmark=args.benchmark,
                    report_path=args.report)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
