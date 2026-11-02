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
    from PySide6.QtCore import Qt, QThread, Signal, QTimer
    from PySide6.QtGui import QSurfaceFormat, QShortcut, QKeySequence
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
        QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox,
        QSplitter, QTabWidget, QVBoxLayout, QWidget,
    )
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except ImportError as exc:
    raise SystemExit(
        "GPU viewer dependencies are missing. Run:\n"
        "  python -m pip install -r icr2_3do_cad/gpu_viewer/requirements.txt\n"
        f"Original import error: {exc}"
    ) from exc

from gpu_viewer.mesh import MeshData, make_mesh, read_palette
from gpu_viewer.visibility import camera_in_model_units
from gpu_viewer.scene import build_scene, ordered_scene_indices, load_car_or_model
from gpu_viewer.textures import build_atlas, load_palette
from gpu_viewer.source_tab import SourcePane


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
    fragColor = vec4(texelFetch(u_palette, ivec2(index, 0), 0).rgb, 1.0);
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
        self._drag = None
        self._frametimes = deque(maxlen=240)
        self._frame_count = 0
        self.fps = 0.0
        self.frameSwapped.connect(self._on_frame_swapped)

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
        self._atlas = atlas
        self._palette = np.ascontiguousarray(palette, dtype=np.uint8)
        self._visibility_dirty = True
        self._visible_set = frozenset()
        self._visibility_info = {}
        self._frametimes.clear()
        self._frame_count = 0
        if not preserve_view:
            self.frame_all()
        if self._program is not None:
            self.makeCurrent()
            try:
                self._upload_mesh()
                self._upload_texture_assets()
            finally:
                self.doneCurrent()
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

    def _refresh_visibility(self):
        """Active GL context required. Never reparses or retessellates."""
        if self._model is None or self._mesh is None or self._vao is None:
            return
        eye = camera_in_model_units(
            self._mesh.center, self._mesh.scale, self.target,
            self.azimuth, self.elevation, self.distance)
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
        view,_,_=camera_view(self.azimuth,self.elevation,self.distance,self.target)
        if self.perspective:
            projection=perspective_projection(aspect,near,far)
        else:
            projection=ortho_projection(self.half_height,aspect,near,far)
        matrix=np.ascontiguousarray((projection@view).T,dtype=np.float32)
        glUseProgram(self._program)
        glUniformMatrix4fv(self._uniform,1,GL_FALSE,matrix)
        glUniform1i(self._texture_uniform, int(self.textures_enabled))
        glUniform1i(self._repeat_uniform, int(self.texture_repeat))
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
        glBindVertexArray(0)
        glUseProgram(0)

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
            _, right, up = camera_view(self.azimuth, self.elevation,
                                       self.distance, self.target)
            world_per_pixel = (2 * self.half_height) / max(self.height(), 1)
            self.target += (-dx * right + dy * up) * world_per_pixel
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
        self.setWindowTitle("ICR2 GPU Viewer — prototype")
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
        bspbar = QHBoxLayout()
        bspbar.addWidget(QLabel("Render:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Papyrus BSP painter", "painter")
        self.mode_combo.addItem("BSP selection + GPU depth", "depth")
        self.mode_combo.addItem("All polygons + GPU depth", "all")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        bspbar.addWidget(self.mode_combo)
        bspbar.addWidget(QLabel("LOD distance (game units):"))
        self.lod_spin = QSpinBox()
        self.lod_spin.setRange(0, 2000000000)
        self.lod_spin.setSingleStep(10000)
        self.lod_spin.setValue(0)
        self.lod_spin.valueChanged.connect(self._lod_changed)
        bspbar.addWidget(self.lod_spin)
        self.auto_lod = QCheckBox("Auto per anchor")
        self.auto_lod.setChecked(True)
        self.auto_lod.toggled.connect(self._lod_changed)
        bspbar.addWidget(self.auto_lod)
        self.lod_spin.setEnabled(False)
        self.all_lods = QCheckBox("All LOD branches (diagnostic)")
        self.all_lods.toggled.connect(self._lod_changed)
        bspbar.addWidget(self.all_lods)
        bspbar.addWidget(QLabel("Polygon @"))
        self.polygon_edit = QLineEdit()
        self.polygon_edit.setPlaceholderText("decimal or 0x...")
        self.polygon_edit.setMaximumWidth(135)
        self.polygon_edit.textChanged.connect(self._update_polygon_status)
        bspbar.addWidget(self.polygon_edit)
        layout.addLayout(bspbar)
        assetsbar = QHBoxLayout()
        palette_button = QPushButton("Open PCX palette…")
        palette_button.clicked.connect(self.open_palette_dialog)
        assetsbar.addWidget(palette_button)
        default_button = QPushButton("Default palette")
        default_button.clicked.connect(self.restore_palette)
        assetsbar.addWidget(default_button)
        folder_button = QPushButton("MIP folder…")
        folder_button.clicked.connect(self.choose_mip_folder)
        assetsbar.addWidget(folder_button)
        objects_button = QPushButton("3DO objects folder…")
        objects_button.clicked.connect(self.choose_objects_folder)
        assetsbar.addWidget(objects_button)
        fallback_button = QPushButton("Fallback MIP…")
        fallback_button.clicked.connect(self.choose_fallback_mip)
        assetsbar.addWidget(fallback_button)
        reset_mip = QPushButton("Clear fallback")
        reset_mip.clicked.connect(self.clear_fallback_mip)
        assetsbar.addWidget(reset_mip)
        self.show_textures = QCheckBox("Textures")
        self.show_textures.setChecked(True)
        self.show_textures.toggled.connect(self._textures_toggled)
        assetsbar.addWidget(self.show_textures)
        self.repeat_uv = QCheckBox("Repeat UV")
        self.repeat_uv.toggled.connect(self._repeat_toggled)
        assetsbar.addWidget(self.repeat_uv)
        layout.addLayout(assetsbar)
        carbar = QHBoxLayout()
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
        reload_button = QPushButton("Reload MIPs (R)")
        reload_button.clicked.connect(self.reload_mips)
        carbar.addWidget(reload_button)
        layout.addLayout(carbar)
        layout.addWidget(self.load_label)
        layout.addWidget(self.viewer, stretch=1)
        layout.addWidget(self.stats_label)
        layout.addWidget(self.visibility_label)
        layout.addWidget(self.polygon_status)
        layout.addWidget(self.palette_status)
        layout.addWidget(self.texture_status)
        layout.addWidget(self.car_status)
        self.setCentralWidget(root)
        QShortcut(QKeySequence("F"), self, activated=self.viewer.frame_all)
        QShortcut(QKeySequence("R"), self, activated=self.reload_mips)
        self.viewer.statsChanged.connect(self.statusBar().showMessage)
        self.viewer.visibilityChanged.connect(self._visibility_updated)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._benchmark_tick)
        self.benchmark_toggle.toggled.connect(self._toggle_benchmark)
        if benchmark:
            self._timer.start()
        if path:
            # Opening after the window is visible avoids blocking Qt setup.
            QTimer.singleShot(0, lambda: self.load(path))

    def _textures_toggled(self, checked):
        self.viewer.textures_enabled = checked
        self.viewer.update()

    def _repeat_toggled(self, checked):
        self.viewer.texture_repeat = checked
        self.viewer.update()

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
        self._update_polygon_status()

    def _lod_changed(self, *args):
        self.lod_spin.setEnabled(not (self.all_lods.isChecked()
                                      or self.auto_lod.isChecked()))
        self.viewer.lod_distance = (
            None if self.all_lods.isChecked()
            else 'auto' if self.auto_lod.isChecked()
            else self.lod_spin.value()
        )
        self.viewer.invalidate_visibility()

    def _visibility_updated(self, message):
        self.visibility_label.setText(message)
        self._update_polygon_status()

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
            existing_model=(self.viewer._model if reuse_model else None))
        self.worker.ready.connect(self._loaded)
        self.worker.failed.connect(self._load_failed)
        self.worker.start()

    def _loaded(self, mesh, stats, model, atlas, palette, scene):
        self._info = stats
        self.viewer.set_mesh(mesh, model, atlas, palette, scene,
                             preserve_view=self._preserve_view)
        self._preserve_view = False
        self.palette_status.setText(
            f"Palette: {self.palette_path.name} (256 colors)")
        self._show_mip_stats(stats)
        self.car_status.setText(
            f"Individual-car RECOLOR: {stats['recolor_pairs']} mappings"
            f" | referenced carshape(s): {len(model.external_names)}"
            f" | active texture overrides: {len(self.mip_overrides) + int(self.body_mip is not None)}")
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
        self.statusBar().showMessage(
            ("External 3DO issues: " + "; ".join(stats['external_warnings'][:3]))
            if stats['external_warnings'] else
            "BSP painter | auto RES | Left-drag orbit | Shift-left/middle pan | F frame")

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
