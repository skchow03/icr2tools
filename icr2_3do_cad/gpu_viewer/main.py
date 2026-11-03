"""Experimental GPU viewport for ICR2 track and car geometry.

Standalone read-only prototype: uses the production N3/3DO parser, but NOT
Tkinter's per-polygon renderer. Requires PySide6, PyOpenGL and numpy.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import tempfile
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
    from OpenGL.GL import (
        GL_ARRAY_BUFFER, GL_COLOR_BUFFER_BIT, GL_COMPILE_STATUS, GL_DEPTH_BUFFER_BIT,
        GL_DEPTH_TEST, GL_DYNAMIC_DRAW, GL_ELEMENT_ARRAY_BUFFER, GL_FALSE, GL_FLOAT, GL_FRAGMENT_SHADER, GL_LINK_STATUS,
        GL_STATIC_DRAW, GL_TRIANGLES, GL_UNSIGNED_INT, GL_UNSIGNED_BYTE,
        GL_VERTEX_SHADER, GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE_2D,
        GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_WRAP_S,
        GL_TEXTURE_WRAP_T, GL_NEAREST, GL_CLAMP_TO_EDGE, GL_R8UI,
        GL_RGB8, GL_RED_INTEGER, GL_RGB, GL_UNPACK_ALIGNMENT,
        glAttachShader, glBindBuffer, glBindVertexArray, glBufferData,
        glClear, glClearColor, glCompileShader, glCreateProgram, glCreateShader,
        glDeleteBuffers, glDeleteProgram, glDeleteShader, glDeleteVertexArrays,
        glDisable, glDrawArrays, glDrawElements, glEnable, glEnableVertexAttribArray, glFinish, glGenBuffers,
        glGenVertexArrays, glGetProgramInfoLog, glGetProgramiv,
        glGetShaderInfoLog, glGetShaderiv, glGetUniformLocation, glLinkProgram,
        glShaderSource, glUniformMatrix4fv, glUseProgram, glVertexAttribPointer,
        glViewport, glGenTextures, glDeleteTextures, glBindTexture,
        glActiveTexture, glTexImage2D, glTexParameteri, glPixelStorei,
        glUniform1i,
    )
    from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPointF, QRectF
    from PySide6.QtGui import (
        QColor, QPainter, QPen, QBrush, QSurfaceFormat, QShortcut, QKeySequence,
    )
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
        QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox,
        QScrollArea, QSlider, QSplitter, QTabWidget, QToolButton, QVBoxLayout, QWidget,
    )
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except ImportError as exc:
    raise SystemExit(
        "GPU viewer dependencies are missing. Run:\n"
        "  python -m pip install -r icr2_3do_cad/gpu_viewer/requirements.txt\n"
        f"Original import error: {exc}"
    ) from exc

from gpu_viewer.mesh import MeshData, make_mesh, read_palette
from gpu_viewer.visibility import (
    FIXED_CAMERA_DEFAULT_EYE, camera_in_model_units, fixed_eye_view_target,
)
from gpu_viewer.scene import build_scene, ordered_scene_indices, load_car_or_model
from gpu_viewer.textures import build_atlas, load_palette
from gpu_viewer.source_tab import SourcePane
from gpu_viewer.source_inspection import (
    target_offset, polygon_mesh_range, polygon_inspection_notice,
    vertex_screen_position,
)
from gpu_viewer.workspaces import (
    WORKSPACE_MODES, suggest_workspace, workspace_scene_summary,
    resolve_lod_distance, max_switch_distance,
)


VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 in_pos;
layout(location = 1) in vec3 in_color;
layout(location = 2) in float in_index;
layout(location = 3) in vec2 in_uv;
layout(location = 4) in vec4 in_rect;
uniform mat4 u_mvp;
out vec3 v_color;
flat out int v_index;
out vec2 v_uv;
flat out vec4 v_rect;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_color = in_color;
    v_index = int(in_index + 0.5);
    v_uv = in_uv;
    v_rect = in_rect;
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec3 v_color;
flat in int v_index;
in vec2 v_uv;
flat in vec4 v_rect;
uniform usampler2D u_mips;
uniform sampler2D u_palette;
uniform int u_textures;
uniform int u_repeat;
uniform int u_inspect_poly;
out vec4 fragColor;
void main() {
    int index = clamp(v_index, 0, 255);
    if (u_textures != 0 && v_rect.z >= 1.0 && v_rect.w >= 1.0) {
        ivec2 size_px = ivec2(v_rect.zw);
        ivec2 texel = ivec2(floor(v_uv + vec2(0.5)));
        if (u_repeat != 0) {
            texel = ivec2((texel.x % size_px.x + size_px.x) % size_px.x,
                          (texel.y % size_px.y + size_px.y) % size_px.y);
        } else {
            texel = clamp(texel, ivec2(0), size_px - ivec2(1));
        }
        index = int(texelFetch(u_mips, ivec2(v_rect.xy) + texel, 0).r);
    }
    vec3 color = texelFetch(u_palette, ivec2(index, 0), 0).rgb;
    if (u_inspect_poly != 0) {
        // Highlight the requested face even when BSP/LOD excludes it.
        color = min(vec3(1.0), color * 1.5 + vec3(0.45, 0.33, 0.12));
    }
    fragColor = vec4(color, 1.0);
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


def perspective_projection(aspect, near, far, fov_degrees=60.0):
    factor = 1.0 / math.tan(math.radians(fov_degrees) / 2.0)
    matrix = np.zeros((4, 4), dtype=np.float64)
    matrix[0, 0] = factor / max(aspect, 0.01)
    matrix[1, 1] = factor
    matrix[2, 2] = -(far + near) / (far - near)
    matrix[2, 3] = -2.0 * far * near / (far - near)
    matrix[3, 2] = -1.0
    return matrix


class LoadWorker(QThread):
    ready = Signal(object, object, object, object, object, object)
    failed = Signal(str)

    def __init__(self, path, palette_path, texture_folder=None,
                 fallback_mip=None, *, objects_folder=None,
                 mip_overrides=None, object_overrides=None, body_mip=None,
                 existing_model=None, source_text=None, source_path=None,
                 appearance_override=None):
        super().__init__()
        self.path = Path(path)
        self.palette_path = Path(palette_path)
        self.texture_folder = texture_folder
        self.fallback_mip = fallback_mip
        self.objects_folder = objects_folder
        self.mip_overrides = dict(mip_overrides or {})
        self.object_overrides = dict(object_overrides or {})
        self.body_mip = body_mip
        self.existing_model = existing_model
        self.source_text = source_text
        self.source_path = Path(source_path) if source_path is not None else None
        self.appearance_override = appearance_override

    def run(self):
        try:
            # Do not import Qt or create GL resources on this worker thread.
            from three_do import Model
            from n3_compile import compile_n3_text
            t0 = perf_counter()
            if self.source_text is not None:
                # Compile candidate text off the UI thread. Do not overwrite
                # the last valid model until this AND the mesh/atlas succeed.
                model, _ = compile_n3_text(
                    self.source_text, self.source_path, associate_planes=False)
                appearance = self.appearance_override
                scene = build_scene(model, objects_folder=self.objects_folder,
                                    object_overrides=self.object_overrides,
                                    appearance=appearance)
            elif self.path.suffix.lower() == ".3do":
                model, scene, appearance = load_car_or_model(
                    self.path, existing_model=self.existing_model,
                    objects_folder=self.objects_folder,
                    object_overrides=self.object_overrides,
                    fixtures_folder=CAD_ROOT / 'fixtures')
            elif self.path.suffix.lower() == ".3d":
                if self.existing_model is not None:
                    model = self.existing_model
                else:
                    text = self.path.read_text(encoding="utf-8-sig")
                    model, _ = compile_n3_text(
                        text, self.path, associate_planes=False)
                scene = build_scene(model, objects_folder=self.objects_folder,
                                    object_overrides=self.object_overrides)
                appearance = None
            else:
                raise ValueError("Open a .3D or .3DO file")
            parse_ms = (perf_counter() - t0) * 1000
            palette = load_palette(self.palette_path)
            atlas = build_atlas(scene.geometry, self.path,
                                texture_folder=self.texture_folder,
                                fallback_mip=self.fallback_mip,
                                mip_overrides=self.mip_overrides,
                                body_mip=self.body_mip)
            mesh = make_mesh(scene.geometry,
                             palette.astype(np.float32) / 255.0, atlas)
            stats = {
                "file": self.path.name,
                "parse_ms": parse_ms,
                "mesh_ms": mesh.build_ms,
                "model_polygons": len(model.polygons),
                "model_vertices": len(model.vertices),
                "model_planes": len(model.planes),
                "external_objects": len(model.dynamics),
                "mips": len(model.mip_names),
                "texture_count": len(atlas.loaded_names),
                "missing_textures": atlas.missing_names,
                "texture_errors": atlas.errors,
                "textured_faces": len(atlas.polygon_rects),
                "textured_candidates": atlas.textured_polygons,
                "atlas_shape": atlas.pixels.shape,
                "dynamic_instances": scene.loaded_instances,
                "external_warnings": scene.warnings,
                "switches": sum(len(inst.model.switches)
                                for inst in scene.instances),
                "recolor_pairs": scene.recolor_pairs,
                "appearance_geometry": (appearance.geometry_name if appearance else ""),
                "appearance_mip": (appearance.texture_name if appearance else ""),
                "geometry_file": model.path.name,
                "body_textured_faces": len(scene.geometry.body_polygons),
                "material_names": tuple(sorted(set(
                    scene.geometry.polygon_materials.values()),
                    key=str.casefold)),
            }
            # The parsed, read-only hierarchy is needed to evaluate BSP
            # planes, but polygon geometry is never rebuilt during orbit.
            self.ready.emit(mesh, stats, model, atlas, palette, scene)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class SourceExportWorker(QThread):
    """Generate editable source without blocking Qt/OpenGL for large models."""
    ready = Signal(str, object)
    failed = Signal(str)

    def __init__(self, model, opened_path):
        super().__init__()
        self.model = model
        self.opened_path = Path(opened_path)

    def run(self):
        try:
            from text_3d import export_text
            if self.opened_path.suffix.lower() == '.3d':
                source = self.opened_path.read_text(encoding='utf-8-sig')
                target = self.opened_path
            else:
                # For individual-car wrappers, export BASE geometry, not the
                # zero-polygon MATERIAL->RECOLOR wrapper.
                source = export_text(self.model)
                target = self.model.path.with_suffix('.3d')
            self.ready.emit(source, target)
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class TextureReloadWorker(QThread):
    """Read changed MIP bytes on a worker, without reloading car/3DO models."""
    ready = Signal(object, object, object)
    failed = Signal(str)

    def __init__(self, scene, mesh, palette, model_path, texture_folder,
                 fallback_mip, mip_overrides, body_mip, previous_atlas):
        super().__init__()
        self.scene = scene
        self.mesh = mesh
        self.palette = np.ascontiguousarray(palette, dtype=np.uint8)
        self.model_path = model_path
        self.texture_folder = texture_folder
        self.fallback_mip = fallback_mip
        self.mip_overrides = dict(mip_overrides)
        self.body_mip = body_mip
        self.previous_atlas = previous_atlas

    def run(self):
        try:
            atlas = build_atlas(
                self.scene.geometry, self.model_path,
                texture_folder=self.texture_folder,
                fallback_mip=self.fallback_mip,
                mip_overrides=self.mip_overrides,
                body_mip=self.body_mip)
            # Texture edits normally change only indexed pixels. VBO and BSP
            # index ordering remain completely untouched in the fast path.
            mesh = None
            if atlas.polygon_rects != self.previous_atlas.polygon_rects:
                mesh = make_mesh(
                    self.scene.geometry,
                    self.palette.astype(np.float32) / 255.0, atlas)
            stats = {
                "texture_count": len(atlas.loaded_names),
                "missing_textures": atlas.missing_names,
                "texture_errors": atlas.errors,
                "textured_faces": len(atlas.polygon_rects),
                "textured_candidates": atlas.textured_polygons,
                "atlas_shape": atlas.pixels.shape,
            }
            self.ready.emit(atlas, mesh, stats)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class GLViewport(QOpenGLWidget):
    statsChanged = Signal(str)
    visibilityChanged = Signal(str)
    fixedCameraModeChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(600, 400)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(False)
        self._program = None
        self._uniform = None
        self._texture_uniform = None
        self._repeat_uniform = None
        self._inspection_uniform = None
        self._atlas_texture = None
        self._palette_texture = None
        self._atlas = None
        self._palette = None
        self.textures_enabled = True
        self.texture_repeat = False
        self.texture_upload_ms = None
        self._resources_released = False
        self._vbo = None
        self._ebo = None
        self._vao = None
        self._mesh = None
        self._model = None
        self._scene = None
        self.inspection_kind = None
        self.inspection_offset = None
        self.render_mode = 'painter'  # painter | depth | all
        self.lod_distance = 'auto'  # auto=per-RES anchor, None=all, number=manual
        self._visibility_dirty = True
        self._index_count = 0
        self._visible_set = frozenset()
        self._visibility_info = {}
        self.upload_ms = None
        self.azimuth = math.radians(35)
        self.elevation = math.radians(28)
        self.target = np.zeros(3, dtype=np.float64)
        self.distance = 4.0
        self.half_height = 1.6
        self.perspective = False
        self.fixed_camera_mode = False
        self.fixed_camera_eye = tuple(FIXED_CAMERA_DEFAULT_EYE)
        self.fixed_camera_fov = 60.0
        self._saved_external_view = None
        self._drag = None
        self._frametimes = deque(maxlen=240)
        self._frame_count = 0
        self.fps = 0.0
        self.frameSwapped.connect(self._on_frame_swapped)
        # IMPORTANT: text drawn via QPainter inside paintGL was corrupted on
        # some drivers (glyphs become speckled/striped after raw GL calls).
        # A child QLabel paints through Qt's widget compositor independently
        # of the OpenGL shader / buffer state.
        self.visibility_banner = QLabel(self)
        self.visibility_banner.setObjectName("sourceVisibilityBanner")
        self.visibility_banner.setTextFormat(Qt.TextFormat.PlainText)
        self.visibility_banner.setWordWrap(True)
        self.visibility_banner.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.visibility_banner.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.visibility_banner.setStyleSheet(
            "QLabel#sourceVisibilityBanner {"
            " background: #171e2b; color: #ffffff;"
            " border: 2px solid #dca04b; border-radius: 6px;"
            " padding: 10px 14px;"
            " font-size: 13px; font-weight: bold; }")
        self.visibility_banner.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._size_visibility_banner()

    def _size_visibility_banner(self):
        width = max(120, min(660, self.width() - 24))
        self.visibility_banner.setGeometry(12, 12, width, 76)

    def _set_visibility_warning(self, notice):
        if not notice:
            if self.visibility_banner.isVisible():
                self.visibility_banner.hide()
            return
        # Two deliberate lines: Qt owns font rendering and wraps the detail
        # at the *logical* widget width, independent of device pixel ratio.
        reason = notice.partition(": ")[2] if ": " in notice else notice
        text = "POLY NOT VISIBLE\n" + reason[0].upper() + reason[1:]
        if self.visibility_banner.text() != text:
            self.visibility_banner.setText(text)
        self._size_visibility_banner()
        if not self.visibility_banner.isVisible():
            self.visibility_banner.show()
        self.visibility_banner.raise_()

    def initializeGL(self):
        """Qt owns the active FBO. PyOpenGL operates on it without wrapping."""
        self._resources_released = False
        self.context().aboutToBeDestroyed.connect(self.shutdown_gl)
        vertex_shader = glCreateShader(GL_VERTEX_SHADER)
        fragment_shader = glCreateShader(GL_FRAGMENT_SHADER)
        try:
            for shader, source in ((vertex_shader, VERTEX_SHADER),
                                   (fragment_shader, FRAGMENT_SHADER)):
                glShaderSource(shader, source)
                glCompileShader(shader)
                if not glGetShaderiv(shader, GL_COMPILE_STATUS):
                    raise RuntimeError(glGetShaderInfoLog(shader))
            program = glCreateProgram()
            glAttachShader(program, vertex_shader)
            glAttachShader(program, fragment_shader)
            glLinkProgram(program)
            if not glGetProgramiv(program, GL_LINK_STATUS):
                raise RuntimeError(glGetProgramInfoLog(program))
            self._program = program
            self._uniform = glGetUniformLocation(program, "u_mvp")
            self._texture_uniform = glGetUniformLocation(program, "u_textures")
            self._repeat_uniform = glGetUniformLocation(program, "u_repeat")
            self._inspection_uniform = glGetUniformLocation(program, "u_inspect_poly")
            glUseProgram(program)
            glUniform1i(glGetUniformLocation(program, "u_mips"), 0)
            glUniform1i(glGetUniformLocation(program, "u_palette"), 1)
            glUseProgram(0)
        finally:
            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)
        glEnable(GL_DEPTH_TEST)
        self._visibility_dirty = True
        if self._mesh is not None:
            self._upload_mesh()
            self._upload_texture_assets()

    def shutdown_gl(self):
        """Delete our VBO/VAO/shader before Qt destroys its GL context."""
        if self._resources_released:
            return
        self._resources_released = True
        if self._program is None:
            return
        self.makeCurrent()
        try:
            if self._vao is not None:
                glDeleteVertexArrays(1, [self._vao])
                self._vao = None
            if self._vbo is not None:
                glDeleteBuffers(1, [self._vbo])
                self._vbo = None
            if self._ebo is not None:
                glDeleteBuffers(1, [self._ebo])
                self._ebo = None
            textures = [tex for tex in (self._atlas_texture, self._palette_texture)
                        if tex is not None]
            if textures:
                glDeleteTextures(len(textures), textures)
            self._atlas_texture = self._palette_texture = None
            glDeleteProgram(self._program)
            self._program = None
        finally:
            self.doneCurrent()

    def set_mesh(self, mesh: MeshData, model, atlas, palette, scene,
                 *, preserve_view=False):
        self._mesh = mesh
        self._model = model
        self._scene = scene
        self.inspection_kind = None
        self.inspection_offset = None
        self._atlas = atlas
        self._palette = np.ascontiguousarray(palette, dtype=np.uint8)
        self._visibility_dirty = True
        self._visible_set = frozenset()
        self._visibility_info = {}
        self._frametimes.clear()
        self._frame_count = 0
        if not preserve_view and not self.fixed_camera_mode:
            self.frame_all()
        # If origin view is enabled while opening another model, keep the
        # eye pinned to that model's (0,0,0), not its bounding-box center.
        if self._program is not None:
            self.makeCurrent()
            try:
                self._upload_mesh()
                self._upload_texture_assets()
            finally:
                self.doneCurrent()
        self.update()

    def set_source_inspection(self, kind=None, offset=None):
        """Set a source-only overlay. Existing VBO/EBO and scene stay unchanged."""
        if kind not in ("polygon", "vertex") or offset is None:
            kind, offset = None, None
        if (self.inspection_kind, self.inspection_offset) != (kind, offset):
            self.inspection_kind = kind
            self.inspection_offset = offset
            self.update()

    def _upload_mesh(self):
        if self._program is None:
            return
        started = perf_counter()
        # Rebuild only on open. Camera movement never uploads geometry.
        if self._vao is not None:
            glDeleteVertexArrays(1, [self._vao])
            self._vao = None
        if self._vbo is not None:
            glDeleteBuffers(1, [self._vbo])
            self._vbo = None
        if self._ebo is not None:
            glDeleteBuffers(1, [self._ebo])
            self._ebo = None
        self._visibility_dirty = True
        if self._mesh is not None and self._mesh.vertices.size:
            payload = np.ascontiguousarray(
                self._mesh.vertices, dtype=np.float32).tobytes()
            self._vao = int(glGenVertexArrays(1))
            self._vbo = int(glGenBuffers(1))
            self._ebo = int(glGenBuffers(1))
            glBindVertexArray(self._vao)
            glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
            glBufferData(GL_ARRAY_BUFFER, len(payload), payload, GL_STATIC_DRAW)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(
                0, 3, GL_FLOAT, GL_FALSE, 52, ctypes.c_void_p(0))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(
                1, 3, GL_FLOAT, GL_FALSE, 52, ctypes.c_void_p(12))
            for location, length, offset in ((2, 1, 24), (3, 2, 28),
                                             (4, 4, 36)):
                glEnableVertexAttribArray(location)
                glVertexAttribPointer(
                    location, length, GL_FLOAT, GL_FALSE, 52,
                    ctypes.c_void_p(offset))
            # Element buffer stays attached to the VAO. Upload only integer
            # indices when BSP visibility changes, never the XYZ/RGB VBO.
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, 0, None, GL_DYNAMIC_DRAW)
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            # One synchronization at load time; never in the render loop.
            glFinish()
        self.upload_ms = (perf_counter()-started)*1000
        self.statsChanged.emit(f"GPU upload: {self.upload_ms:.1f} ms")

    def _upload_texture_assets(self):
        """OpenGL texture setup is GUI-thread-only; never called on orbit."""
        if self._program is None or self._atlas is None or self._palette is None:
            return
        started = perf_counter()
        if self._atlas_texture is None:
            self._atlas_texture = int(glGenTextures(1))
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._atlas_texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        pixels = np.ascontiguousarray(self._atlas.pixels, dtype=np.uint8)
        h, w = pixels.shape
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, w, h, 0,
                     GL_RED_INTEGER, GL_UNSIGNED_BYTE, pixels)
        self._upload_palette()
        self.texture_upload_ms = (perf_counter() - started) * 1000

    def _upload_palette(self):
        if self._program is None or self._palette is None:
            return
        if self._palette_texture is None:
            self._palette_texture = int(glGenTextures(1))
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self._palette_texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, 256, 1, 0, GL_RGB,
                     GL_UNSIGNED_BYTE, self._palette)

    def set_atlas(self, atlas):
        """Replace MIP pixel texture only: preserve VAO/VBO and BSP EBO."""
        self._atlas = atlas
        if self._program is not None:
            self.makeCurrent()
            try:
                self._upload_texture_assets()
            finally:
                self.doneCurrent()
        self.update()

    def set_palette(self, palette):
        """Swap the 256-color lookup without retessellating/reuploading XYZ."""
        self._palette = np.ascontiguousarray(palette, dtype=np.uint8)
        if self._program is not None:
            self.makeCurrent()
            try:
                self._upload_palette()
            finally:
                self.doneCurrent()
        self.update()

    def invalidate_visibility(self):
        """Reevaluate only the BSP indices at the next draw, not the mesh."""
        self._visibility_dirty = True
        self.update()

    def set_render_mode(self, mode):
        if mode not in ('painter', 'depth', 'all'):
            raise ValueError(f"Unknown render mode: {mode}")
        self.render_mode = mode
        if mode == 'all':
            self.visibilityChanged.emit(
                f"All polygons: {self._mesh.polygon_count:,} geometry faces "
                "(BSP and LOD ignored; GPU depth test)"
                if self._mesh is not None else "All polygons"
            )
            self.update()
        else:
            self.invalidate_visibility()

    def _camera_eye_model(self):
        """Unscaled Papyrus eye used for BSP and automatic RES switches."""
        if self.fixed_camera_mode:
            return self.fixed_camera_eye
        return camera_in_model_units(
            self._mesh.center, self._mesh.scale, self.target,
            self.azimuth, self.elevation, self.distance)

    def _camera_view_matrix(self):
        """Fixed Camera changes look direction without moving its eye."""
        target = self.target
        if self.fixed_camera_mode and self._mesh is not None:
            target = fixed_eye_view_target(
                self._mesh.center, self._mesh.scale, self.fixed_camera_eye,
                self.azimuth, self.elevation, self.distance)
        return camera_view(
            self.azimuth, self.elevation, self.distance, target)

    def _refresh_visibility(self):
        """Active GL context required. Never reparses or retessellates."""
        if self._model is None or self._mesh is None or self._vao is None:
            return
        eye = self._camera_eye_model()
        direction = None
        if not self.perspective:
            direction = (
                math.cos(self.elevation) * math.sin(self.azimuth),
                -math.cos(self.elevation) * math.cos(self.azimuth),
                math.sin(self.elevation),
            )
        indices, visible, info = ordered_scene_indices(
            self._scene, self._mesh, eye, self.lod_distance,
            view_direction=direction)
        glBindVertexArray(self._vao)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes,
                     indices if indices.size else None, GL_DYNAMIC_DRAW)
        glBindVertexArray(0)
        self._index_count = len(indices)
        self._visible_set = visible
        self._visibility_info = info
        self._visibility_dirty = False
        self.visibilityChanged.emit(
            f"BSP visible {info['mesh_polygons']:,}/{self._mesh.polygon_count:,} "
            f"renderable polygons | {info['triangles']:,} triangles | "
            f"{info['tested_planes']:,} plane tests | "
            f"{info['culled_nodes']:,} pruned nodes | "
            f"{info['lod_selections']:,} LOD selections | "
            f"{info['instances_visited']:,} instances"
        )

    def paintGL(self):
        if self._program is None:
            return
        # QOpenGLWidget makes its Qt-owned framebuffer current before
        # paintGL. Raw GL operates on it without taking ownership of it.
        w=max(1,int(self.width()*self.devicePixelRatioF()))
        h=max(1,int(self.height()*self.devicePixelRatioF()))
        glViewport(0,0,w,h)
        if self.render_mode == 'painter':
            # Preserve Papyrus traversal / LIST painter order. Depth testing
            # would defeat authored overlaps and coincident BSP2 front/back.
            glDisable(GL_DEPTH_TEST)
        else:
            glEnable(GL_DEPTH_TEST)
        glClearColor(0.065,0.09,0.135,1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self._vao is None:
            return
        aspect=w/h
        near=0.001
        far=max(100.0,40.0*self.distance)
        view,_,_=self._camera_view_matrix()
        if self.perspective:
            projection=perspective_projection(
                aspect, near, far,
                self.fixed_camera_fov if self.fixed_camera_mode else 60.0)
        else:
            projection=ortho_projection(self.half_height,aspect,near,far)
        matrix=np.ascontiguousarray((projection@view).T,dtype=np.float32)
        glUseProgram(self._program)
        glUniformMatrix4fv(self._uniform,1,GL_FALSE,matrix)
        glUniform1i(self._texture_uniform, int(self.textures_enabled))
        glUniform1i(self._repeat_uniform, int(self.texture_repeat))
        glUniform1i(self._inspection_uniform, 0)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._atlas_texture or 0)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self._palette_texture or 0)
        if self.render_mode != 'all' and self._visibility_dirty:
            self._refresh_visibility()
        glBindVertexArray(self._vao)
        if self.render_mode == 'all':
            glDrawArrays(GL_TRIANGLES,0,self._mesh.vertices.shape[0])
        elif self._index_count:
            glDrawElements(GL_TRIANGLES, self._index_count, GL_UNSIGNED_INT, None)

        # Source highlighting must never force a BSP/LOD-excluded polygon
        # into the scene. Only brighten polygons selected for this view.
        notice = None
        if self.inspection_kind == "polygon":
            span = polygon_mesh_range(
                self._scene, self._mesh, self.inspection_offset)
            if span is None or not span[1]:
                notice = "POLY has no renderable triangles in this scene"
            elif (self.render_mode != "all" and
                  self.inspection_offset not in self._visible_set):
                notice = polygon_inspection_notice(
                    self._model, self.inspection_offset, self._visible_set,
                    self.lod_distance, self._camera_eye_model(),
                    self.render_mode)
            else:
                # The selected face is part of the active traversal; retain
                # its bright overlay for easy identification.
                glDisable(GL_DEPTH_TEST)
                glUniform1i(self._inspection_uniform, 1)
                glDrawArrays(GL_TRIANGLES, *span)
                glUniform1i(self._inspection_uniform, 0)

        glBindVertexArray(0)
        glUseProgram(0)
        self._set_visibility_warning(notice)
        if self.inspection_kind == "vertex":
            position = vertex_screen_position(
                self._model, self._mesh, self.inspection_offset,
                projection @ view, self.width(), self.height())
            if position is not None:
                # The existing screen-space dot retains its own QPainter path.
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor(12, 20, 32), 2))
                painter.setBrush(QBrush(QColor(255, 237, 65)))
                painter.drawEllipse(QPointF(*position), 6.0, 6.0)
                painter.end()

    def _on_frame_swapped(self):
        now = perf_counter()
        self._frame_count += 1
        self._frametimes.append(now)
        if len(self._frametimes) >= 2:
            duration = self._frametimes[-1] - self._frametimes[0]
            if duration > 0.25:
                self.fps = (len(self._frametimes) - 1) / duration

    def set_fixed_camera_eye(self, x, y, z):
        """Update the raw Papyrus XYZ eye without changing orbit, mesh or FOV."""
        eye = tuple(float(v) for v in (x, y, z))
        if not all(math.isfinite(v) for v in eye):
            raise ValueError("Fixed Camera XYZ must be finite")
        if eye == self.fixed_camera_eye:
            return
        self.fixed_camera_eye = eye
        if self.fixed_camera_mode:
            self.invalidate_visibility()

    def set_fixed_camera_mode(self, enabled):
        """Toggle a stationary perspective eye at user-specified raw XYZ."""
        enabled = bool(enabled)
        if self.fixed_camera_mode == enabled:
            return
        if enabled:
            self._saved_external_view = (
                self.target.copy(), self.distance, self.half_height,
                self.perspective, self.azimuth, self.elevation)
            self.fixed_camera_mode = True
            self.perspective = True
            self.azimuth = 0.0       # Looking toward +Y from the fixed eye
            self.elevation = 0.0     # Level view for interior inspection
            self.fixed_camera_fov = 60.0
        else:
            self.fixed_camera_mode = False
            if self._saved_external_view is not None:
                (target, self.distance, self.half_height, self.perspective,
                 self.azimuth, self.elevation) = self._saved_external_view
                self.target = target.copy()
            self._saved_external_view = None
        self.fixedCameraModeChanged.emit(self.fixed_camera_mode)
        self.invalidate_visibility()

    def frame_all(self):
        if self.fixed_camera_mode:
            self.set_fixed_camera_mode(False)
        self.target[:] = 0
        self.distance = 4.0
        self.half_height = 1.6
        self.invalidate_visibility()

    def set_view(self, name):
        if name == "3D":
            self.azimuth, self.elevation = math.radians(35), math.radians(28)
        elif name == "Top":
            self.azimuth, self.elevation = 0.0, math.pi / 2
        elif name == "Front":
            self.azimuth, self.elevation = 0.0, 0.0
        elif name == "Side":
            self.azimuth, self.elevation = math.pi / 2, 0.0
        self.invalidate_visibility()

    def wheelEvent(self, event):
        notches = event.angleDelta().y() / 120.0
        multiplier = math.exp(-notches * 0.15)
        if self.fixed_camera_mode:
            # Do not dolly away from (0,0,0). Wheel adjusts field of view,
            # letting skybox authors examine details while stationary.
            self.fixed_camera_fov = min(110.0, max(20.0, self.fixed_camera_fov * multiplier))
            self.update()
        else:
            self.half_height = min(1000.0, max(.0001, self.half_height * multiplier))
            self.distance = min(1000.0, max(.001, self.distance * multiplier))
            self.invalidate_visibility()
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
            if not self.fixed_camera_mode:
                _, right, up = self._camera_view_matrix()
                world_per_pixel = (2 * self.half_height) / max(self.height(), 1)
                self.target += (-dx * right + dy * up) * world_per_pixel
            # Fixed Camera disables pan: eye stays at selected raw XYZ.
        else:
            self.azimuth -= dx * .006
            self.elevation = max(-math.pi/2, min(math.pi/2,
                                                 self.elevation + dy*.006))
        self.invalidate_visibility()
        event.accept()


BODY_MATERIAL = "__car_body__"  # internal target, never an asset filename


class Window(QMainWindow):
    def __init__(self, path=None, *, benchmark=False, report_path=None):
        super().__init__()
        self.setWindowTitle("ICR2 GPU Viewer — Object workspace")
        self.resize(1280, 850)
        self.worker = None
        self._info = {}
        self.report_path = report_path
        self.palette_path = CAD_ROOT / "gamepal.pcx"
        self.texture_folder = None
        self.objects_folder = None
        self.mip_overrides = {}
        self.object_overrides = {}
        self.body_mip = None
        self.fallback_mip = None
        self.model_path = None
        self._preserve_view = False
        self._source_invalid = False
        self._source_busy_revision = None
        self._source_queued = None
        self._source_export_worker = None
        self._source_export_model = None
        self._source_applied = False
        self._last_valid_source_text = None
        self.viewer = GLViewport()
        self.load_label = QLabel("Open a .3D or .3DO model")
        self.load_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats_label = QLabel("No model loaded")
        self.visibility_label = QLabel("BSP status will appear here")
        self.polygon_status = QLabel("Enter a polygon body offset to inspect")
        self.palette_status = QLabel("Palette: bundled gamepal.pcx")
        self.texture_status = QLabel("MIPs: no model loaded")
        self.car_status = QLabel("Individual-car RECOLOR: not loaded")
        root = QWidget()
        layout = QVBoxLayout(root)
        # Collapsible, scrollable settings leave the majority of the window to the model.
        self.sidebar_content = QWidget()
        side_layout = QVBoxLayout(self.sidebar_content)
        side_layout.setContentsMargins(8, 8, 8, 8)
        side_layout.setSpacing(6)
        self.section_buttons = {}

        def section(title, expanded):
            header = QToolButton()
            header.setText(title)
            header.setCheckable(True)
            header.setChecked(expanded)
            header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            side_layout.addWidget(header)
            self.section_buttons[title] = header
            panel = QWidget()
            content = QVBoxLayout(panel)
            content.setContentsMargins(4, 2, 4, 8)
            content.setSpacing(6)
            panel.setVisible(expanded)
            side_layout.addWidget(panel)

            def toggle(checked, target=panel, button=header):
                target.setVisible(checked)
                button.setArrowType(
                    Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
            header.toggled.connect(toggle)
            return content

        model_layout = section("Model", True)
        display_layout = section("Display", True)
        assets_layout = section("Assets", False)
        advanced_layout = section("Advanced diagnostics", False)
        side_layout.addStretch()

        toolbar = QHBoxLayout()
        open_button = QPushButton("Open…")
        open_button.clicked.connect(self.open_dialog)
        toolbar.addWidget(open_button)
        save_source = QPushButton("Save Source")
        save_source.clicked.connect(
            lambda: self._source_toolbar_action(self._save_source))
        toolbar.addWidget(save_source)
        export_3do = QPushButton("Export 3DO")
        export_3do.clicked.connect(
            lambda: self._source_toolbar_action(self._export_compiled_source))
        toolbar.addWidget(export_3do)
        frame_button = QPushButton("Frame All (F)")
        frame_button.clicked.connect(self.viewer.frame_all)
        toolbar.addWidget(frame_button)
        for name in ("3D", "Top", "Front", "Side"):
            button = QPushButton(name)
            button.clicked.connect(
                lambda checked=False, mode=name: self.viewer.set_view(mode))
            toolbar.addWidget(button)
        self.fixed_camera_button = QPushButton("Fixed Camera")
        self.fixed_camera_button.setCheckable(True)
        self.fixed_camera_button.setToolTip(
            "Lock the camera at user-selected raw Papyrus XYZ. "
            "Default: (0, 0, 5000). Drag to look around; the wheel changes "
            "FOV without moving the camera. Frame All or untoggle "
            "to return to the exterior orbit.")
        self.fixed_camera_button.toggled.connect(self.viewer.set_fixed_camera_mode)
        advanced_layout.addWidget(self.fixed_camera_button)
        self.perspective_toggle = QCheckBox("Perspective")
        self.perspective_toggle.toggled.connect(self._set_perspective)
        display_layout.addWidget(self.perspective_toggle)
        self.source_toggle = QPushButton('.3D Source')
        self.source_toggle.setCheckable(True)
        self.source_toggle.toggled.connect(self._toggle_source)
        toolbar.addWidget(self.source_toggle)
        self.benchmark_toggle = QCheckBox("Continuous 60 Hz benchmark")
        self.benchmark_toggle.setChecked(benchmark)
        advanced_layout.addWidget(self.benchmark_toggle)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        # Expose raw Papyrus coordinates while Fixed Camera is active.
        # Keep these controls outside the already-crowded view toolbar.
        self.fixed_camera_controls = QWidget(root)
        fixedbar = QVBoxLayout(self.fixed_camera_controls)
        fixedbar.setContentsMargins(0, 0, 0, 0)
        fixedbar.addWidget(QLabel("Fixed Camera eye (raw XYZ):"))
        self.fixed_camera_coords = []
        for axis, raw in zip("XYZ", FIXED_CAMERA_DEFAULT_EYE):
            fixedbar.addWidget(QLabel(axis + ":"))
            spin = QSpinBox()
            spin.setRange(-2_000_000_000, 2_000_000_000)
            spin.setSingleStep(1000)
            spin.setValue(int(raw))
            spin.setMinimumWidth(112)
            spin.setToolTip(
                f"Raw Papyrus {axis} camera coordinate, in model units. "
                "Enter a value to move the fixed camera.")
            spin.valueChanged.connect(self._fixed_camera_coords_changed)
            self.fixed_camera_coords.append(spin)
            fixedbar.addWidget(spin)
        fixedbar.addStretch()
        self.fixed_camera_controls.hide()
        advanced_layout.addWidget(self.fixed_camera_controls)
        advanced_layout.addWidget(QLabel("Rendering method"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Papyrus drawing order (default)", "painter")
        self.mode_combo.addItem("BSP selection + GPU depth", "depth")
        self.mode_combo.addItem("All polygons + GPU depth", "all")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        advanced_layout.addWidget(self.mode_combo)

        display_layout.addWidget(QLabel("SWITCH DISTANCE / RES"))
        self.lod_mode_combo = QComboBox()
        self.lod_mode_combo.addItem("Automatic (per RES anchor)", "auto")
        self.lod_mode_combo.addItem("Manual (slider)", "manual")
        self.lod_mode_combo.addItem("Show all detail levels", "all")
        self.lod_mode_combo.setToolTip(
            "Drag the distance slider to select manual distance. "
            "Automatic measures from the camera to each RES anchor.")
        self.lod_mode_combo.currentIndexChanged.connect(self._lod_changed)
        display_layout.addWidget(self.lod_mode_combo)
        slider_row = QHBoxLayout()
        self.lod_slider = QSlider(Qt.Orientation.Horizontal)
        self.lod_slider.setRange(0, 0)
        self.lod_slider.setEnabled(False)
        self.lod_slider.setToolTip(
            "Manual SWITCH DISTANCE in raw Papyrus model units; "
            "dragging switches from Automatic to Manual.")
        self.lod_slider.sliderPressed.connect(self._activate_manual_distance)
        self.lod_slider.valueChanged.connect(self._slider_distance_changed)
        slider_row.addWidget(self.lod_slider, 1)
        self.lod_spin = QSpinBox()
        self.lod_spin.setRange(0, 0)
        self.lod_spin.setKeyboardTracking(False)
        self.lod_spin.setToolTip(
            "Exact SWITCH DISTANCE. Editing this value selects Manual mode.")
        self.lod_spin.valueChanged.connect(self._spin_distance_changed)
        self.lod_spin.setEnabled(False)
        slider_row.addWidget(self.lod_spin)
        display_layout.addLayout(slider_row)
        self.lod_max_label = QLabel("No SWITCH DISTANCE thresholds found")
        self.lod_max_label.setWordWrap(True)
        display_layout.addWidget(self.lod_max_label)

        advanced_layout.addWidget(QLabel("Polygon body offset"))
        self.polygon_edit = QLineEdit()
        self.polygon_edit.setPlaceholderText("decimal or 0x...")
        self.polygon_edit.textChanged.connect(self._update_polygon_status)
        advanced_layout.addWidget(self.polygon_edit)

        assetsbar = QVBoxLayout()
        palette_button = QPushButton("Open PCX palette…")
        palette_button.clicked.connect(self.open_palette_dialog)
        assetsbar.addWidget(palette_button)
        default_button = QPushButton("Default palette")
        default_button.clicked.connect(self.restore_palette)
        assetsbar.addWidget(default_button)
        folder_button = QPushButton("MIP folder…")
        folder_button.clicked.connect(self.choose_mip_folder)
        assetsbar.addWidget(folder_button)
        reload_button = QPushButton("Reload MIPs (R)")
        reload_button.clicked.connect(self.reload_mips)
        assetsbar.addWidget(reload_button)
        self.show_textures = QCheckBox("Textures")
        self.show_textures.setChecked(True)
        self.show_textures.toggled.connect(self._textures_toggled)
        display_layout.addWidget(self.show_textures)
        self.repeat_uv = QCheckBox("Repeat UV")
        self.repeat_uv.toggled.connect(self._repeat_toggled)
        display_layout.addWidget(self.repeat_uv)
        assets_layout.addLayout(assetsbar)
        objects_button = QPushButton("External 3DO folder…")
        objects_button.clicked.connect(self.choose_objects_folder)
        assets_layout.addWidget(objects_button)
        self.fallback_controls = QWidget()
        fallback_layout = QVBoxLayout(self.fallback_controls)
        fallback_layout.setContentsMargins(0, 0, 0, 0)
        fallback_button = QPushButton("Fallback MIP…")
        fallback_button.clicked.connect(self.choose_fallback_mip)
        fallback_layout.addWidget(fallback_button)
        clear_fallback = QPushButton("Clear fallback MIP")
        clear_fallback.clicked.connect(self.clear_fallback_mip)
        fallback_layout.addWidget(clear_fallback)
        assets_layout.addWidget(self.fallback_controls)

        # Mode tabs configure the current scene; the GPU viewport and N3
        # editor below remain a single shared document across all three.
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setDocumentMode(True)
        car_page = QWidget()
        car_layout = QVBoxLayout(car_page)
        car_layout.setContentsMargins(6, 4, 6, 4)
        carbar = QVBoxLayout()
        carbar.addWidget(QLabel("Car geometry:"))
        self.car_ref_combo = QComboBox()
        self.car_ref_combo.setMinimumWidth(90)
        carbar.addWidget(self.car_ref_combo)
        shape_button = QPushButton("Assign carshape 3DO…")
        shape_button.clicked.connect(self.choose_car_shape)
        carbar.addWidget(shape_button)
        clear_shape = QPushButton("Clear shape override")
        clear_shape.clicked.connect(self.clear_car_shape)
        carbar.addWidget(clear_shape)
        carbar.addWidget(QLabel("Texture target:"))
        self.material_combo = QComboBox()
        self.material_combo.setMinimumWidth(100)
        carbar.addWidget(self.material_combo)
        livery_button = QPushButton("Assign livery MIP…")
        livery_button.clicked.connect(self.choose_livery_mip)
        carbar.addWidget(livery_button)
        clear_livery = QPushButton("Clear livery override")
        clear_livery.clicked.connect(self.clear_livery_mip)
        carbar.addWidget(clear_livery)
        car_layout.addLayout(carbar)
        car_layout.addWidget(self.car_status)
        self.workspace_tabs.addTab(car_page, "Car")

        track_page = QWidget()
        track_layout = QVBoxLayout(track_page)
        track_layout.setContentsMargins(6, 4, 6, 4)
        self.track_status = QLabel("Track scene: open a track .3D or .3DO")
        track_layout.addWidget(self.track_status)
        self.workspace_tabs.addTab(track_page, "Track")

        object_page = QWidget()
        object_layout = QVBoxLayout(object_page)
        object_layout.setContentsMargins(6, 4, 6, 4)
        self.object_status = QLabel("Object scene: open a standalone .3D or .3DO")
        object_layout.addWidget(self.object_status)
        self.workspace_tabs.addTab(object_page, "Object")

        # Ambiguous filenames should not be guessed to be cars or tracks.
        # A strongly identified file selects a tab after its first load.
        self.workspace_tabs.setCurrentIndex(WORKSPACE_MODES.index("object"))
        self.workspace_tabs.currentChanged.connect(self._workspace_changed)
        model_layout.addWidget(self.workspace_tabs)
        self.load_label.setWordWrap(True)
        model_layout.addWidget(self.load_label)
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.addWidget(self.viewer)
        self.source_tabs = QTabWidget()
        self.source_pane = SourcePane()
        self.source_tabs.addTab(self.source_pane, '.3D Source')
        source_help = QLabel(
            'Edit Papyrus N3 text; after a 650 ms pause, valid source '
            'recompiles off the GUI thread and updates the GPU viewport.\\n\\n'
            'An invalid edit retains the last valid model. '
            'Use Apply now to compile immediately, and Save .3D as… '
            'to save the source text. Export compiled .3DO… writes a '
            'separate binary only after successful compilation.\\n\\n'
            'When a car appearance wrapper is open, the source is for '
            'its shared base geometry; the livery and RECOLOR remain '
            'read-only overlays. The original source files are never '
            'overwritten without explicit confirmation.')
        source_help.setWordWrap(True)
        source_help.setAlignment(Qt.AlignmentFlag.AlignTop)
        source_help.setMargin(16)
        self.source_tabs.addTab(source_help, 'Help')
        self.editor_splitter.addWidget(self.source_tabs)
        self.editor_splitter.setStretchFactor(0, 2)
        self.editor_splitter.setStretchFactor(1, 1)
        self.source_tabs.hide()
        sidebar = QScrollArea()
        sidebar.setWidgetResizable(True)
        sidebar.setWidget(self.sidebar_content)
        sidebar.setMinimumWidth(265)
        sidebar.setMaximumWidth(410)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.editor_splitter)
        self.main_splitter.addWidget(sidebar)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        self.main_splitter.setSizes([970, 300])
        layout.addWidget(self.main_splitter, stretch=1)
        for label in (self.stats_label, self.visibility_label,
                      self.polygon_status, self.palette_status,
                      self.texture_status, self.car_status,
                      self.track_status, self.object_status):
            label.setWordWrap(True)
        advanced_layout.addWidget(self.stats_label)
        advanced_layout.addWidget(self.visibility_label)
        advanced_layout.addWidget(self.polygon_status)
        assets_layout.addWidget(self.palette_status)
        assets_layout.addWidget(self.texture_status)
        self.setCentralWidget(root)
        self._workspace_changed(self.workspace_tabs.currentIndex())
        # Single-letter viewport shortcuts must NOT intercept N3 typing in
        # QPlainTextEdit (e.g. FACE, MATERIAL, RECOLOR).
        frame_shortcut = QShortcut(QKeySequence("F"), self.viewer,
                                  activated=self.viewer.frame_all)
        frame_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        reload_shortcut = QShortcut(QKeySequence("R"), self.viewer,
                                   activated=self.reload_mips)
        reload_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.viewer.statsChanged.connect(self.statusBar().showMessage)
        self.viewer.visibilityChanged.connect(self._visibility_updated)
        self.viewer.fixedCameraModeChanged.connect(self._fixed_camera_mode_changed)
        self.source_pane.compileRequested.connect(self._source_requested)
        self.source_pane.saveRequested.connect(self._save_source)
        self.source_pane.exportRequested.connect(self._export_compiled_source)
        self.source_pane.cursorTargetChanged.connect(self._source_target_changed)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._benchmark_tick)
        self.benchmark_toggle.toggled.connect(self._toggle_benchmark)
        if benchmark:
            self._timer.start()
        if path:
            # Opening after the window is visible avoids blocking Qt setup.
            QTimer.singleShot(0, lambda: self.load(path))

    def _workspace_changed(self, index):
        if 0 <= index < self.workspace_tabs.count():
            label = self.workspace_tabs.tabText(index)
            self.setWindowTitle(f"ICR2 GPU Viewer — {label} workspace")
            self.fallback_controls.setVisible(label != "Car")

    def _source_toolbar_action(self, callback):
        """Expose Save/Export without bypassing lazy source preparation."""
        if not self.source_pane.ready:
            if self.viewer._model is None:
                QMessageBox.information(self, "No model", "Open a model first.")
                return
            self.source_toggle.setChecked(True)
            self._ensure_source_loaded()
            self.statusBar().showMessage(
                "Preparing editable source; use Save Source or Export 3DO when ready.")
            return
        callback()

    def _textures_toggled(self, checked):
        self.viewer.textures_enabled = checked
        self.viewer.update()

    def _repeat_toggled(self, checked):
        self.viewer.texture_repeat = checked
        self.viewer.update()

    def _toggle_source(self, checked):
        self.source_tabs.setVisible(checked)
        if checked:
            self.editor_splitter.setSizes([780, 480])
            self.source_tabs.setCurrentIndex(0)
            self._ensure_source_loaded()
            self._source_target_changed(self.source_pane.current_target())
        else:
            self.viewer.set_source_inspection()
            self.source_pane.set_polygon_visibility(None)

    def _source_target_changed(self, target):
        if (not self.source_toggle.isChecked() or
                self.source_pane.pending or self._source_invalid or
                target is None):
            self.viewer.set_source_inspection()
            self.source_pane.set_polygon_visibility(None)
            return
        kind, label = target
        offset = target_offset(self.viewer._model, kind, label)
        self.viewer.set_source_inspection(kind, offset)
        self._refresh_source_polygon_visibility()

    def _refresh_source_polygon_visibility(self):
        target = self.source_pane.current_target()
        if (not self.source_toggle.isChecked() or
                self._source_invalid or target is None or
                target[0] != "polygon" or
                self.viewer._model is None or
                (self.viewer._visibility_dirty and
                 self.viewer.render_mode != "all")):
            self.source_pane.set_polygon_visibility(None)
            return
        offset = target_offset(self.viewer._model, "polygon", target[1])
        span = polygon_mesh_range(self.viewer._scene,
                                  self.viewer._mesh, offset)
        if span is None or not span[1]:
            self.source_pane.set_polygon_visibility(False)
        else:
            self.source_pane.set_polygon_visibility(
                self.viewer.render_mode == "all" or
                offset in self.viewer._visible_set)

    def _ensure_source_loaded(self):
        if self.source_pane.ready or self.viewer._model is None:
            return
        if self._source_export_worker and self._source_export_worker.isRunning():
            return
        model = self.viewer._model
        self._source_export_model = model
        self.source_pane.status.setText('Preparing editable .3D source on worker…')
        worker = SourceExportWorker(model, self.model_path)
        self._source_export_worker = worker
        worker.ready.connect(
            lambda text, path, candidate=model:
                self._source_exported(candidate, text, path))
        worker.failed.connect(
            lambda err, candidate=model: self._source_export_failed(candidate, err))
        worker.start()

    def _source_exported(self, candidate, text, path):
        if candidate is not self.viewer._model:
            if self.source_toggle.isChecked():
                QTimer.singleShot(80, self._ensure_source_loaded)
            return
        if self.source_pane.ready:
            return
        self.source_pane.set_source(
            text, path,
            status=(f'Editable source for {candidate.path.name}. '
                    'Valid changes update the GPU preview without saving.'))
        self._source_invalid = False

    def _source_export_failed(self, candidate, error):
        if candidate is self.viewer._model:
            self.source_pane.status.setText(
                f'Cannot generate editable source: {error}')
            self._source_invalid = True

    def _source_requested(self, revision, source):
        # Keep only the latest revision while the previous worker runs.
        self._source_queued = (revision, source)
        self._pump_source()

    def _pump_source(self):
        if self._source_queued is None:
            return
        if self.worker is not None and self.worker.isRunning():
            QTimer.singleShot(80, self._pump_source)
            return
        if not self.source_pane.ready or self.viewer._model is None:
            return
        revision, source = self._source_queued
        if revision != self.source_pane.revision:
            self._source_queued = None
            return
        self._source_queued = None
        self._source_busy_revision = revision
        self.worker = LoadWorker(
            self.model_path, self.palette_path, self.texture_folder,
            self.fallback_mip, objects_folder=self.objects_folder,
            mip_overrides=self.mip_overrides, object_overrides=self.object_overrides,
            body_mip=self.body_mip, source_text=source,
            source_path=self.source_pane.source_path,
            appearance_override=self.viewer._scene.appearance)
        self.worker.ready.connect(
            lambda mesh, stats, model, atlas, palette, scene, rev=revision:
                self._source_compiled(rev, source, mesh, stats, model, atlas, palette, scene))
        self.worker.failed.connect(
            lambda error, rev=revision: self._source_compile_failed(rev, error))
        self.worker.start()

    def _source_compiled(self, rev, source, mesh, stats, model, atlas, palette, scene):
        self._source_busy_revision = None
        if rev == self.source_pane.revision:
            # Commit one complete candidate, never a partially parsed tree.
            self._preserve_view = True
            self._loaded(mesh, stats, model, atlas, palette, scene,
                         from_source=True)
            self._source_applied = True
            self._last_valid_source_text = source
            self._source_invalid = False
            self.source_pane.mark_valid(rev, model)
        if self._source_queued is not None:
            QTimer.singleShot(40, self._pump_source)

    def _source_compile_failed(self, rev, error):
        self._source_busy_revision = None
        if rev == self.source_pane.revision:
            self._source_invalid = True
            self.source_pane.mark_error(rev, error)
        if self._source_queued is not None:
            QTimer.singleShot(40, self._pump_source)

    def _save_source(self):
        if not self.source_pane.ready:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save editable N3 source',
            str(self.source_pane.source_path.with_name(
                self.source_pane.source_path.stem + '_edited.3d')),
            'Papyrus N3 (*.3d);;All files (*)')
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != '.3d':
            QMessageBox.warning(self, 'Invalid source extension',
                                'Save N3 source with a .3D extension.')
            return
        if target.resolve() == self.source_pane.source_path.resolve():
            reply = QMessageBox.question(
                self, 'Overwrite original N3 source?',
                'This will overwrite the original editable .3D file. Continue?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix='.' + target.name + '.', suffix='.tmp', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(self.source_pane.get_source().encode('utf-8'))
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self, 'Save failed', str(error))
            return
        self.source_pane.status.setText(
            f'Saved {target.name}.' +
            (' Source is not currently valid; GPU preview still shows last valid model.'
             if self._source_invalid or self.source_pane.pending else ''))

    def _export_compiled_source(self):
        if not self.source_pane.ready or self.viewer._model is None:
            return
        if self.source_pane.pending or self._source_invalid or self._source_queued is not None:
            QMessageBox.warning(
                self, 'Cannot export an unvalidated model',
                'Resolve the N3 source error or Apply now successfully before '
                'exporting a compiled binary. Save .3D as… can retain unfinished text.')
            return
        target, _ = QFileDialog.getSaveFileName(
            self, 'Export compiled 3DO',
            str(self.source_pane.source_path.with_name(
                self.source_pane.source_path.stem + '_edited.3do')),
            'Papyrus 3DO (*.3do);;All files (*)')
        if not target:
            return
        dest = Path(target)
        if dest.suffix.lower() != '.3do':
            QMessageBox.warning(self, 'Invalid binary extension', 'Choose a .3DO file.')
            return
        if dest.resolve() == self.viewer._model.path.resolve() or (
                self.model_path is not None and
                dest.resolve() == self.model_path.resolve()):
            QMessageBox.warning(
                self, 'Original binary protected',
                'Choose another filename. Original geometry and appearance '
                '3DOs must remain untouched.')
            return
        try:
            fd, temporary = tempfile.mkstemp(
                prefix='.' + dest.name + '.', suffix='.tmp', dir=dest.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(self.viewer._model.raw)
                os.replace(temporary, dest)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError as error:
            QMessageBox.warning(self, 'Export failed', str(error))
            return
        self.source_pane.status.setText(f'Exported last valid model as {dest.name}.')

    def _busy(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Loading", "Finish the current load first.")
            return True
        return False

    def _apply_palette(self, path):
        if self._busy():
            return
        try:
            palette = load_palette(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid PCX palette", str(exc))
            return
        self.palette_path = Path(path)
        self.palette_status.setText(f"Palette: {self.palette_path.name} (256 colors)")
        self.viewer.set_palette(palette)

    def open_palette_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open 256-color PCX palette",
            str(self.palette_path.parent),
            "PCX palette (*.pcx *.PCX);;All files (*)")
        if path:
            self._apply_palette(path)

    def restore_palette(self):
        self._apply_palette(CAD_ROOT / "gamepal.pcx")

    def choose_mip_folder(self):
        if self._busy():
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Choose folder with .MIP textures",
            str(self.texture_folder or
                (self.model_path.parent if self.model_path else CAD_ROOT)))
        if directory:
            self.texture_folder = Path(directory)
            self._reload_texture_assets()

    def choose_objects_folder(self):
        if self._busy():
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Choose folder with external .3DO objects",
            str(self.objects_folder or
                (self.model_path.parent if self.model_path else CAD_ROOT)))
        if directory:
            self.objects_folder = Path(directory)
            self._reload_texture_assets()

    def choose_fallback_mip(self):
        if self._busy():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose MIP for unassigned POLY [T] faces",
            str(self.texture_folder or
                (self.model_path.parent if self.model_path else CAD_ROOT)),
            "Papyrus MIP (*.mip *.MIP);;All files (*)")
        if path:
            self.fallback_mip = Path(path)
            self._reload_texture_assets()

    def clear_fallback_mip(self):
        if self._busy():
            return
        self.fallback_mip = None
        self._reload_texture_assets()

    def _reload_texture_assets(self):
        if self.model_path is not None and self.viewer._model is not None:
            self.load(self.model_path, reuse_model=True)

    def choose_car_shape(self):
        if self._busy():
            return
        name = self.car_ref_combo.currentData()
        if not name:
            QMessageBox.information(
                self, "No referenced carshape",
                "Open an individual-car appearance wrapper to assign its shared carshape.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"Use a 3DO for {name}",
            str(self.objects_folder or
                (self.model_path.parent if self.model_path else CAD_ROOT)),
            "Papyrus 3DO (*.3do *.3DO);;All files (*)")
        if path:
            self.object_overrides[name.casefold()] = Path(path)
            self._reload_texture_assets()

    def clear_car_shape(self):
        if self._busy():
            return
        name = self.car_ref_combo.currentData()
        if name and name.casefold() in self.object_overrides:
            self.object_overrides.pop(name.casefold())
            self._reload_texture_assets()

    def choose_livery_mip(self):
        if self._busy():
            return
        name = self.material_combo.currentData()
        if not name:
            QMessageBox.information(
                self, "No texture target",
                "Load a model containing POLY [T] faces first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose MIP for material {name}",
            str(self.texture_folder or
                (self.model_path.parent if self.model_path else CAD_ROOT)),
            "Papyrus livery MIP (*.mip *.MIP);;All files (*)")
        if path:
            if name == BODY_MATERIAL:
                self.body_mip = Path(path)
            else:
                self.mip_overrides[name.casefold()] = Path(path)
            self.reload_mips()

    def clear_livery_mip(self):
        if self._busy():
            return
        name = self.material_combo.currentData()
        if name == BODY_MATERIAL:
            if self.body_mip is not None:
                self.body_mip = None
                self.reload_mips()
        elif name and name.casefold() in self.mip_overrides:
            self.mip_overrides.pop(name.casefold())
            self.reload_mips()

    def reload_mips(self):
        """Re-read car livery MIPs, keeping the model and camera in memory."""
        if self._busy() or self.model_path is None:
            return
        scene = self.viewer._scene
        if scene is None or self.viewer._mesh is None:
            return
        self.statusBar().showMessage("Reloading indexed MIP pixels…")
        self.worker = TextureReloadWorker(
            scene, self.viewer._mesh, self.viewer._palette,
            self.model_path, self.texture_folder, self.fallback_mip,
            self.mip_overrides, self.body_mip, self.viewer._atlas)
        self.worker.ready.connect(self._mips_reloaded)
        self.worker.failed.connect(self._mip_reload_failed)
        self.worker.start()

    def _show_mip_stats(self, stats):
        self.texture_status.setText(
            f"MIPs: {stats['texture_count']} loaded | "
            f"{stats['textured_faces']}/{stats['textured_candidates']} "
            f"POLY [T] faces mapped | atlas "
            f"{stats['atlas_shape'][1]}x{stats['atlas_shape'][0]} | "
            f"{len(stats['missing_textures'])} missing | "
            f"{len(stats['texture_errors'])} errors")

    def _mips_reloaded(self, atlas, mesh, stats):
        self._info.update(stats)
        if mesh is None:
            self.viewer.set_atlas(atlas)
            self.statusBar().showMessage(
                "Livery MIPs reloaded; original VBO, BSP and camera preserved")
        else:
            self.viewer.set_mesh(
                mesh, self.viewer._model, atlas,
                self.viewer._palette, self.viewer._scene, preserve_view=True)
            self._source_target_changed(self.source_pane.current_target())
            self.statusBar().showMessage(
                "Livery MIPs reloaded; UV atlas layout changed, rebuilt VBO")
        self._show_mip_stats(stats)
        self.car_status.setText(
            f"Individual-car RECOLOR: {self._info.get('recolor_pairs',0)} mappings"
            f" | base: {self._info.get('geometry_file','')}"
            f" | active texture overrides: {len(self.mip_overrides) + int(self.body_mip is not None)}")
        if stats['missing_textures'] or stats['texture_errors']:
            self.statusBar().showMessage(
                "MIP issues: " + "; ".join(
                    list(stats['missing_textures'][:5]) +
                    list(stats['texture_errors'][:3])))

    def _mip_reload_failed(self, message):
        self.statusBar().showMessage("MIP reload failed; previous livery retained")
        QMessageBox.warning(self, "MIP reload failed", message)

    def _mode_changed(self, index):
        self.viewer.set_render_mode(self.mode_combo.currentData())
        self._refresh_source_polygon_visibility()
        self._update_polygon_status()

    def _activate_manual_distance(self):
        if self.lod_mode_combo.currentData() != "manual":
            self.lod_mode_combo.setCurrentIndex(
                self.lod_mode_combo.findData("manual"))
        else:
            self._lod_changed()

    def _slider_distance_changed(self, value):
        self.lod_spin.blockSignals(True)
        self.lod_spin.setValue(value)
        self.lod_spin.blockSignals(False)
        self._activate_manual_distance()

    def _spin_distance_changed(self, value):
        self.lod_slider.blockSignals(True)
        self.lod_slider.setValue(value)
        self.lod_slider.blockSignals(False)
        self._activate_manual_distance()

    def _configure_switch_distance(self, scene):
        """Clamp the slider to the loaded scene's highest actual RES threshold."""
        maximum = max_switch_distance(scene)
        value = min(self.lod_spin.value(), maximum)
        for control in (self.lod_slider, self.lod_spin):
            control.blockSignals(True)
            control.setRange(0, maximum)
            control.setValue(value)
            control.setEnabled(maximum > 0)
            control.blockSignals(False)
        self.lod_slider.setSingleStep(max(1, maximum // 500))
        self.lod_slider.setPageStep(max(1, maximum // 20))
        self.lod_max_label.setText(
            f"0 – {maximum:,} raw model units (highest RES threshold)"
            if maximum else "No SWITCH DISTANCE thresholds found")
        self._lod_changed()

    def _sync_source_distance_filter(self):
        """Mirror the renderer's validated model, RES setting and camera."""
        if not hasattr(self, "source_pane"):
            return
        model = self.viewer._model
        eye = (self.viewer._camera_eye_model()
               if model is not None and self.viewer._mesh is not None
               else None)
        self.source_pane.set_distance_filter_context(
            model, self.viewer.lod_distance, eye)

    def _lod_changed(self, *args):
        self.viewer.lod_distance = resolve_lod_distance(
            self.lod_mode_combo.currentData(), self.lod_spin.value())
        self.viewer.invalidate_visibility()
        self._sync_source_distance_filter()
        self._refresh_source_polygon_visibility()

    def _visibility_updated(self, message):
        self.visibility_label.setText(message)
        self._update_polygon_status()
        self._sync_source_distance_filter()
        self._refresh_source_polygon_visibility()

    def _update_polygon_status(self, *args):
        text = self.polygon_edit.text().strip()
        model = self.viewer._model
        if not text:
            self.polygon_status.setText("Enter a polygon body offset to inspect")
            return
        try:
            offset = int(text, 16 if text.lower().startswith('0x') else 10)
        except ValueError:
            self.polygon_status.setText("Enter a decimal or 0x hexadecimal offset")
            return
        if model is None:
            self.polygon_status.setText("Load a model first")
        elif offset not in model.polygons:
            self.polygon_status.setText(f"@{offset}: not a parsed POLY record")
        elif self.viewer.render_mode == 'all':
            self.polygon_status.setText(f"@{offset}: all-polygon mode (BSP ignored)")
        elif self.viewer._visibility_dirty:
            self.polygon_status.setText(f"@{offset}: recalculating BSP selection")
        elif offset not in self.viewer._visible_set:
            self.polygon_status.setText(f"@{offset}: EXCLUDED by BSP or selected LOD")
        elif (self.viewer._scene is None or
              self.viewer._scene.polygon_lookup.get((0, offset))
              not in self.viewer._mesh.polygon_ranges):
            self.polygon_status.setText(f"@{offset}: selected by BSP, but degenerate / not meshed")
        else:
            self.polygon_status.setText(
                f"@{offset}: SELECTED by BSP (may still be covered by another polygon)")

    def _fixed_camera_coords_changed(self, *_):
        self.viewer.set_fixed_camera_eye(
            *(spin.value() for spin in self.fixed_camera_coords))
        if self.viewer.fixed_camera_mode:
            self.statusBar().showMessage(
                "Fixed Camera | raw XYZ "
                + str(tuple(spin.value() for spin in self.fixed_camera_coords))
                + " | Drag to look | Wheel adjusts FOV | Pan disabled")

    def _fixed_camera_mode_changed(self, enabled):
        # Frame All exits Fixed Camera; keep toolbar, coordinate controls
        # and Qt perspective state synchronized without recursive signals.
        self.fixed_camera_button.blockSignals(True)
        self.fixed_camera_button.setChecked(enabled)
        self.fixed_camera_button.blockSignals(False)
        self.fixed_camera_controls.setVisible(enabled)
        self.perspective_toggle.blockSignals(True)
        self.perspective_toggle.setChecked(self.viewer.perspective)
        self.perspective_toggle.setEnabled(not enabled)
        self.perspective_toggle.blockSignals(False)
        self.statusBar().showMessage(
            "Fixed Camera | raw XYZ "
            + str(tuple(spin.value() for spin in self.fixed_camera_coords))
            + " | Drag to look | Wheel adjusts FOV | Pan disabled | "
              "Frame All exits preview"
            if enabled else
            "Exterior camera restored | Left-drag orbit | Shift-left/middle pan")

    def _set_perspective(self, checked):
        self.viewer.perspective = checked
        # Orthographic BSP must use parallel-ray direction rather than the
        # finite perspective camera position. Reevaluate on every toggle.
        self.viewer.invalidate_visibility()

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

    def load(self, path, *, reuse_model=False):
        if self._busy():
            return
        next_path = Path(path)
        if not reuse_model and self.source_pane.dirty:
            answer = QMessageBox.question(
                self, 'Discard unsaved N3 edits?',
                'Opening another model will discard unsaved .3D source text. '
                'Save the source first if you want to keep it.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if not reuse_model:
            self._source_invalid = False
            self._source_applied = False
            self._last_valid_source_text = None
            self._source_queued = None
            self.source_pane.reset()
        if not reuse_model and self.model_path is not None and (
                self.model_path.resolve() != next_path.resolve()):
            # Assignments belong to the open asset, not a previous car.
            self.mip_overrides.clear()
            self.object_overrides.clear()
            self.body_mip = None
            self.fallback_mip = None
        self.model_path = next_path
        self._preserve_view = reuse_model
        self.load_label.setText(f"Loading {Path(path).name}… (background worker)")
        self.stats_label.setText("Loading geometry and MIP atlas…")
        self.worker = LoadWorker(
            path, self.palette_path, self.texture_folder, self.fallback_mip,
            objects_folder=self.objects_folder,
            mip_overrides=self.mip_overrides,
            object_overrides=self.object_overrides,
            body_mip=self.body_mip,
            existing_model=(self.viewer._model if reuse_model else None),
            source_text=(self._last_valid_source_text
                         if reuse_model and self._source_applied else None),
            source_path=(self.source_pane.source_path
                         if reuse_model and self._source_applied else None),
            appearance_override=(self.viewer._scene.appearance
                                 if reuse_model and self._source_applied else None))
        self.worker.ready.connect(self._loaded)
        self.worker.failed.connect(self._load_failed)
        self.worker.start()

    def _loaded(self, mesh, stats, model, atlas, palette, scene,
                *, from_source=False):
        self._info = stats
        was_reloading = self._preserve_view
        self.viewer.set_mesh(mesh, model, atlas, palette, scene,
                             preserve_view=was_reloading)
        self._configure_switch_distance(scene)
        self._preserve_view = False
        self._sync_source_distance_filter()
        self._source_target_changed(self.source_pane.current_target())
        # Keep manual mode selection for ambiguous files and all background
        # rebuilds. Only clearly recognized newly opened files select a tab.
        if not was_reloading and not from_source:
            suggested = suggest_workspace(self.model_path, stats)
            if suggested is not None:
                self.workspace_tabs.setCurrentIndex(WORKSPACE_MODES.index(suggested))
        self.palette_status.setText(
            f"Palette: {self.palette_path.name} (256 colors)")
        self._show_mip_stats(stats)
        self.car_status.setText(
            f"Individual-car RECOLOR: {stats['recolor_pairs']} mappings"
            f" | referenced carshape(s): {len(model.external_names)}"
            f" | active texture overrides: {len(self.mip_overrides) + int(self.body_mip is not None)}")
        self.track_status.setText(workspace_scene_summary("track", stats))
        self.object_status.setText(workspace_scene_summary("object", stats))
        previous_ref = self.car_ref_combo.currentData()
        self.car_ref_combo.blockSignals(True)
        self.car_ref_combo.clear()
        if stats['appearance_geometry']:
            name = stats['appearance_geometry']
            self.car_ref_combo.addItem(name, name)
        else:
            self.car_ref_combo.addItem("(opened geometry)", "")
        if previous_ref:
            selected = self.car_ref_combo.findData(previous_ref)
            if selected >= 0:
                self.car_ref_combo.setCurrentIndex(selected)
        self.car_ref_combo.blockSignals(False)
        previous_material = self.material_combo.currentData()
        self.material_combo.blockSignals(True)
        self.material_combo.clear()
        if stats['body_textured_faces']:
            label = ("Car body" +
                     (f" ({stats['appearance_mip']})" if stats['appearance_mip']
                      else " (POLY [T])"))
            self.material_combo.addItem(label, BODY_MATERIAL)
        for name in stats['material_names']:
            if name == stats['appearance_mip'] and stats['appearance_mip']:
                continue
            self.material_combo.addItem(f"External/material: {name}", name)
        if previous_material:
            selected = self.material_combo.findData(previous_material)
            if selected >= 0:
                self.material_combo.setCurrentIndex(selected)
        self.material_combo.blockSignals(False)
        if stats['missing_textures'] or stats['texture_errors']:
            details = (list(stats['missing_textures'][:5]) +
                       list(stats['texture_errors'][:3]))
            self.statusBar().showMessage(
                "MIP diagnostics: " + "; ".join(details))

        self.load_label.setText(
            f"{stats['file']} → {stats['geometry_file']}  |  vertices {stats['model_vertices']:,}  |  "
            f"planes {stats['model_planes']:,}  |  "
            f"external instances {stats['dynamic_instances']:,} loaded | "
            f"RES switches {stats['switches']:,} | "
            f"{len(stats['external_warnings'])} missing/problematic objects")
        self.stats_label.setText(
            f"Parse {stats['parse_ms']:.0f} ms  |  "
            f"Mesh {stats['mesh_ms']:.0f} ms  |  "
            f"Upload {(self.viewer.upload_ms or 0):.1f} ms  |  "
            f"{mesh.polygon_count:,} polygons / {mesh.triangle_count:,} triangles  |  "
            f"skipped {mesh.skipped_polygons:,}  |  "
            f"fallback fans {mesh.fan_fallbacks:,}  |  "
            f"buffer {mesh.size_bytes / 1048576:.1f} MiB")
        problem_count = (len(stats['external_warnings']) +
                         len(stats['missing_textures']) +
                         len(stats['texture_errors']))
        self.statusBar().showMessage(
            f"{Path(stats['file']).name} | {mesh.polygon_count:,} polygons | "
            + (f"{problem_count} asset warnings — see Assets" if problem_count
               else "Ready"))
        if not from_source and self.source_toggle.isChecked():
            self._ensure_source_loaded()

    def _load_failed(self, message):
        self.load_label.setText("Load failed; previous model preserved")
        self.stats_label.setText(message)
        QMessageBox.critical(self, "Cannot load Papyrus model", message)

    def closeEvent(self, event):
        self._timer.stop()
        if self._source_export_worker is not None and self._source_export_worker.isRunning():
            self._source_export_worker.wait()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait()
        self.viewer.shutdown_gl()
        if self.report_path and self._info and self.viewer._mesh is not None:
            mesh = self.viewer._mesh
            payload = {
                "schema": 1,
                "renderer": "GPU prototype; Qt/PyOpenGL flat-colour depth test",
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
                "mip_atlas_bytes": (self.viewer._atlas.size_bytes
                                    if self.viewer._atlas else 0),
                "mip_textures_loaded": self._info.get("texture_count", 0),
                "mip_textured_polygons": self._info.get("textured_faces", 0),
                "mip_textures_missing": list(self._info.get("missing_textures", ())),
                "mip_load_errors": list(self._info.get("texture_errors", ())),
                "palette_basename": self.palette_path.name,
                "recolor_pairs": self._info.get("recolor_pairs", 0),
                "appearance_geometry": self._info.get("appearance_geometry", ""),
                "appearance_mip": self._info.get("appearance_mip", ""),
                "body_livery_override": bool(self.body_mip),
                "material_names": list(self._info.get("material_names", ())),
                "dynamic_instances": self._info.get("dynamic_instances", 0),
                "external_warnings": list(self._info.get("external_warnings", ())),
                "switches_in_models": self._info.get("switches", 0),
                "render_mode": self.viewer.render_mode,
                "lod_distance": self.viewer.lod_distance,
                "bsp_selected_polygons": len(self.viewer._visible_set),
                "bsp_draw_indices": self.viewer._index_count,
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
