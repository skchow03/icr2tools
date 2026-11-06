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
        GL_DEPTH_TEST, GL_POLYGON_OFFSET_FILL, GL_DYNAMIC_DRAW, GL_ELEMENT_ARRAY_BUFFER, GL_FALSE, GL_FLOAT, GL_FRAGMENT_SHADER, GL_LINK_STATUS,
        GL_STATIC_DRAW, GL_TRIANGLES, GL_LINES, GL_UNSIGNED_INT, GL_UNSIGNED_BYTE,
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
        glPolygonOffset,
        glViewport, glGenTextures, glDeleteTextures, glBindTexture,
        glActiveTexture, glTexImage2D, glTexParameteri, glPixelStorei,
        glUniform1i, glUniform3f,
    )
    from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPointF, QRectF, QSettings
    from PySide6.QtGui import (
        QColor, QPainter, QPen, QBrush, QSurfaceFormat, QShortcut, QKeySequence,
    )
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
        QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
        QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
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
from gpu_viewer.wireframe import make_wireframe
from gpu_viewer.visibility import (
    FIXED_CAMERA_DEFAULT_EYE, camera_in_model_units, fixed_eye_view_target,
)
from gpu_viewer.scene import build_scene, ordered_scene_indices, load_car_or_model
from gpu_viewer.skybox import (
    load_preferred_track_skybox, skybox_view_matrix,
)
from gpu_viewer.track_lod import DEFAULT_WINDOW_COUNTS
from gpu_viewer.track_navigation import (
    find_matching_trk, TrackNavigation, DEFAULT_LONG_STEP_FT,
    DEFAULT_LAT_STEP_FT, UNITS_PER_FOOT,
)
from gpu_viewer.sprites import prepare_scene_sprites, draw_runs
from gpu_viewer.sprite_gl import PMPGLRenderer
from gpu_viewer.textures import (build_atlas, load_palette,
                                 find_model_sunny_palette)
from gpu_viewer.appearance import DARK_COLORS, load_colors, save_colors, validated_colors
from gpu_viewer.appearance_dialog import AppearanceDialog
from gpu_viewer.confirmations import confirm_destructive_action
from gpu_viewer.source_tab import SourcePane
from gpu_viewer.scale_dialog import ScaleModelDialog
from gpu_viewer.source_inspection import (
    target_offset, polygon_mesh_range, polygon_inspection_notice,
    vertex_screen_position, raw_point_screen_position, bsp_winding_arrows,
    VertexPicker, PolygonPicker,
)
from gpu_viewer.workspaces import (
    WORKSPACE_MODES, suggest_workspace, workspace_scene_summary,
    resolve_lod_distance, max_switch_distance,
)
from gpu_viewer.menus import install_menus, remember_recent_model, update_model_actions
from gpu_viewer.load_diagnostics import LoadIssue, collect_load_issues, format_load_log
from gpu_viewer.polygon_split import split_n3_polygon, polygon_boundary_refs


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
uniform vec3 u_inspect_dark_tint;
uniform vec3 u_inspect_light_tint;
uniform int u_wireframe;
uniform vec3 u_wire_color;
uniform vec3 u_selected_wire_color;
out vec4 fragColor;
void main() {
    // Wireframe is a separate untextured line pass. Do not sample MIP/PCX.
    if (u_wireframe != 0) {
        fragColor = vec4(
            u_wireframe == 2 ? u_selected_wire_color : u_wire_color, 1.0);
        return;
    }
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
        // Brightening clips pale/white POLYs to white, making selection
        // invisible. Use a warm tint for dark pixels, a strong contrasting
        // blue tint for bright pixels, and a smooth transition for MIPs.
        float brightness = dot(color, vec3(0.2126, 0.7152, 0.0722));
        float light_mix = smoothstep(0.48, 0.75, brightness);
        vec3 on_dark = mix(color, u_inspect_dark_tint, 0.74);
        vec3 on_light = mix(color, u_inspect_light_tint, 0.82);
        color = mix(on_dark, on_light, light_mix);
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
                 appearance_override=None, auto_local_palette=False):
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
        self.auto_local_palette = auto_local_palette

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
            selected_palette = self.palette_path
            palette_warning = None
            auto_palette = False
            local_sunny = (find_model_sunny_palette(self.path)
                           if self.auto_local_palette else None)
            if local_sunny is not None:
                try:
                    palette = load_palette(local_sunny)
                except (OSError, ValueError) as exc:
                    # A damaged SUNNY.PCX must not prevent opening otherwise
                    # valid geometry. Fall back to the existing user palette.
                    palette_warning = (
                        f"{local_sunny.name}: {exc}; "
                        f"using {self.palette_path.name}")
                    palette = load_palette(self.palette_path)
                else:
                    selected_palette = local_sunny
                    auto_palette = True
            else:
                palette = load_palette(self.palette_path)
            # HORIZ is a separate camera-locked background for indexed tracks.
            # Try valid HORIZ.3DO files first; malformed/nonrenderable ones do
            # not prevent a standalone HORIZ.3D from being compiled in memory.
            if scene.track_section_lods:
                scene.skybox, sky_notes = load_preferred_track_skybox(
                    self.path, palette.astype(np.float32) / 255.0,
                    objects_folder=self.objects_folder,
                    texture_folder=self.texture_folder)
                if scene.skybox is None:
                    scene.skybox_error = sky_notes
                elif sky_notes:
                    scene.warnings = tuple(
                        dict.fromkeys((*scene.warnings, sky_notes)))
            # A companion <trackstem>.TRK supplies physics centerline XYZ,
            # tangent and elevation for the camera, independently of 3DO BSP.
            # Ignore unrelated .TRK files in the directory.
            if scene.track_section_lods:
                trk_path = find_matching_trk(self.path)
                if trk_path is not None:
                    try:
                        scene.track_navigation = TrackNavigation.from_file(trk_path)
                    except (OSError, ValueError, IndexError, TypeError,
                            OverflowError, ZeroDivisionError) as exc:
                        scene.track_navigation_error = f"{trk_path.name}: {exc}"
            # Decode every PMP variant once in this worker, including
            # nested DYNAMIC/EXTERN placements and nonselected BSP branches.
            # RG8 palette-index/alpha images stay independent of PCX colors.
            scene.sprite_resources = prepare_scene_sprites(
                scene, objects_folder=self.objects_folder,
                texture_folder=self.texture_folder)
            scene.geometry.sprite_bounds = scene.sprite_resources.bounds_points
            atlas = build_atlas(scene.geometry, self.path,
                                texture_folder=self.texture_folder,
                                fallback_mip=self.fallback_mip,
                                mip_overrides=self.mip_overrides,
                                body_mip=self.body_mip)
            mesh = make_mesh(scene.geometry,
                             palette.astype(np.float32) / 255.0, atlas)
            stats = {
                "file": self.path.name,
                "palette_path": selected_palette,
                "palette_auto": auto_palette,
                "palette_warning": palette_warning,
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
                "pmp_warnings": scene.sprite_resources.warnings,
                "pmp_images": len(scene.sprite_resources.images),
                "pmp_placements": len(scene.sprite_resources.placements),
                "switches": sum(len(inst.model.switches)
                                for inst in scene.instances),
                "track_section_lists": len(scene.track_section_lods or {}),
                "skybox_path": str(scene.skybox.path) if scene.skybox else "",
                "skybox_error": scene.skybox_error or "",
                "trk_path": (str(scene.track_navigation.path)
                             if scene.track_navigation else ""),
                "trk_error": scene.track_navigation_error or "",
                "skybox_missing_mips": (scene.skybox.atlas.missing_names
                                        if scene.skybox else ()),
                "skybox_texture_errors": (scene.skybox.atlas.errors
                                          if scene.skybox else ()),
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
            from text_3d import export_compilable_text
            if self.opened_path.suffix.lower() == '.3d':
                # Preserve authored N3 source, including user comments/names.
                source = self.opened_path.read_text(encoding='utf-8-sig')
                target = self.opened_path
            else:
                # For individual-car wrappers, export BASE geometry, not the
                # zero-polygon MATERIAL->RECOLOR wrapper. Standalone source
                # does not need original 3DO offsets to recompile.
                source = export_compilable_text(self.model)
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
    trackDriveModeChanged = Signal(bool)
    trackDrivePositionChanged = Signal(object)
    vertexPicked = Signal(int)  # root-model vertex body offset from a click
    polygonPicked = Signal(int)  # root-model POLY body offset from a click

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
        self._inspection_dark_uniform = None
        self._inspection_light_uniform = None
        self._atlas_texture = None
        self._palette_texture = None
        self._sky_vao = None
        self._sky_vbo = None
        self._sky_ebo = None
        self._sky_atlas_texture = None
        self._sky_index_count = 0
        self.sky_enabled = True
        self._sprite_renderer = None
        self._sprite_events = ()
        self._atlas = None
        self._palette = None
        self.textures_enabled = True
        self.sprites_enabled = True
        # Papyrus texture coordinates address an infinitely tiled MIP;
        # clamp-to-edge remains an explicit diagnostic option in Display.
        self.texture_repeat = True
        self.texture_upload_ms = None
        self._resources_released = False
        self._vbo = None
        self._ebo = None
        self._surface_ebo = None
        self._surface_index_count = 0
        self._wire_vao = None
        self._wire_vbo = None
        self._wire_ebo = None
        self._wire_mesh = None
        self._wire_index_count = 0
        self._wire_uniform = None
        self._wire_color_uniform = None
        self._selected_wire_color_uniform = None
        self.colors = dict(DARK_COLORS)
        self._vao = None
        self._mesh = None
        self._vertex_picker = None
        self._polygon_picker = None
        self.pick_mode = 'vertex'  # explicit polygon mode; vertices by default
        self._model = None
        self._scene = None
        self.inspection_kind = None
        self.inspection_offset = None
        self.inspection_points = None
        self.split_preview_points = None
        self.render_mode = 'painter'  # painter | depth | all | wire
        self.lod_distance = 'auto'  # auto=per-RES anchor, None=all, number=manual
        self.track_detail = 'hi'  # 'window' is DLONG-local when TRK is available
        self.track_window_counts = DEFAULT_WINDOW_COUNTS
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
        self.track_navigation = None
        self.track_drive_enabled = False
        self._track_drive_pose = None
        self._saved_track_view = None
        self.track_forward_step_ft = DEFAULT_LONG_STEP_FT
        self.track_lateral_step_ft = DEFAULT_LAT_STEP_FT
        self.fixed_camera_eye = tuple(FIXED_CAMERA_DEFAULT_EYE)
        self.fixed_camera_fov = 60.0
        self._saved_external_view = None
        self._drag = None
        self._pick_press = None
        self._pick_dragged = False
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
            self._inspection_dark_uniform = glGetUniformLocation(
                program, "u_inspect_dark_tint")
            self._inspection_light_uniform = glGetUniformLocation(
                program, "u_inspect_light_tint")
            self._wire_uniform = glGetUniformLocation(program, "u_wireframe")
            self._wire_color_uniform = glGetUniformLocation(program, "u_wire_color")
            self._selected_wire_color_uniform = glGetUniformLocation(
                program, "u_selected_wire_color")
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
            self._upload_skybox()
            self._upload_sprite_assets()

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
            if self._surface_ebo is not None:
                glDeleteBuffers(1, [self._surface_ebo])
                self._surface_ebo = None
            self._surface_index_count = 0
            self._release_wire_buffers()
            self._wire_mesh = None
            self._delete_skybox_buffers()
            textures = [tex for tex in (self._atlas_texture, self._palette_texture)
                        if tex is not None]
            if textures:
                glDeleteTextures(len(textures), textures)
            self._atlas_texture = self._palette_texture = None
            if self._sprite_renderer is not None:
                self._sprite_renderer.release()
                self._sprite_renderer = None
            glDeleteProgram(self._program)
            self._program = None
        finally:
            self.doneCurrent()

    def set_mesh(self, mesh: MeshData, model, atlas, palette, scene,
                 *, preserve_view=False):
        self._mesh = mesh
        self._model = model
        self._vertex_picker = VertexPicker.from_model(model, mesh)
        self._polygon_picker = PolygonPicker.from_scene(scene, mesh)
        self._scene = scene
        self._sprite_events = ()
        self._surface_index_count = 0
        self._wire_mesh = None
        self._wire_index_count = 0
        self.inspection_kind = None
        self.inspection_offset = None
        self.inspection_points = None
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
                self._upload_skybox()
                self._upload_sprite_assets()
            finally:
                self.doneCurrent()
        self.update()

    def set_appearance_colors(self, colors):
        """Change viewport drawing colors without rebuilding buffers or meshes."""
        self.colors = validated_colors(colors)
        self.update()

    def _vertex_marker_colors(self):
        return (QColor(self.colors["viewport_vertex_outline"]),
                QColor(self.colors["viewport_vertex_dot"]))

    def _wire_color_rgb(self, name):
        color = QColor(self.colors[name])
        return color.redF(), color.greenF(), color.blueF()

    def set_source_inspection(self, kind=None, offset=None, *, plane_points=None):
        """Select one source overlay; do not alter model, BSP, or GPU buffers.

        BSP uses three ordered raw XYZ points from the source plane operand,
        not a binary plane's normal (which does not preserve winding).
        """
        points = None
        if kind == "bsp" and plane_points is not None:
            try:
                points = tuple(tuple(float(x) for x in xyz)
                               for xyz in plane_points)
                if len(points) != 3 or any(len(xyz) != 3 for xyz in points):
                    points = None
                elif not all(np.isfinite(x) for xyz in points for x in xyz):
                    points = None
            except (TypeError, ValueError):
                points = None
            kind, offset = ("bsp", None) if points is not None else (None, None)
        elif kind not in ("polygon", "vertex") or offset is None:
            kind, offset = None, None
        if ((self.inspection_kind, self.inspection_offset,
             self.inspection_points) != (kind, offset, points)):
            self.inspection_kind = kind
            self.inspection_offset = offset
            self.inspection_points = points
            self.update()

    def set_split_preview(self, points=None):
        """Two proposed cut points in raw Papyrus XYZ, or None."""
        normalized = (tuple(tuple(float(v) for v in p) for p in points)
                      if points is not None else None)
        if self.split_preview_points != normalized:
            self.split_preview_points = normalized
            self.update()

    def _paint_split_preview(self, projection, view):
        if self.split_preview_points is None or self._mesh is None:
            return
        matrix = projection @ view
        points = [raw_point_screen_position(
            self._mesh, xyz, matrix, self.width(), self.height())
            for xyz in self.split_preview_points]
        if len(points) != 2 or any(point is None for point in points):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#40e6e2")
        painter.setPen(QPen(color, 3, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(*points[0]), QPointF(*points[1]))
        painter.setPen(QPen(QColor("#12313b"), 2))
        painter.setBrush(QBrush(color))
        for point in points:
            painter.drawEllipse(QPointF(*point), 5, 5)
        painter.end()

    def _paint_source_inspection_markers(self, projection, view):
        """Draw source cursor markers over either GL render mode.

        All paths are QPainter geometry (no text glyphs rendered inside GL):
        cyan BSP 1→2→3→1 winding arrows vs yellow single-vertex edit dot.
        """
        kind = self.inspection_kind
        if kind not in ("vertex", "bsp"):
            return
        matrix = projection @ view
        if kind == "vertex":
            position = vertex_screen_position(
                self._model, self._mesh, self.inspection_offset,
                matrix, self.width(), self.height())
            if position is None:
                return
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            outline, fill = self._vertex_marker_colors()
            painter.setPen(QPen(outline, 2))
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(QPointF(*position), 6.0, 6.0)
            painter.end()
            return

        if self.inspection_points is None:
            return
        positions = tuple(raw_point_screen_position(
            self._mesh, xyz, matrix, self.width(), self.height())
            for xyz in self.inspection_points)
        if all(point is None for point in positions):
            return
        arrow_color = QColor(self.colors["viewport_bsp_arrow"])
        dot_color = QColor(self.colors["viewport_bsp_vertex"])
        outline = QColor(self.colors["viewport_bsp_outline"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(arrow_color, 2.8))
        for start, end, left, right in bsp_winding_arrows(positions):
            # Shaft and two chevrons at its destination show winding order.
            painter.drawLine(QPointF(*start), QPointF(*end))
            painter.drawLine(QPointF(*end), QPointF(*left))
            painter.drawLine(QPointF(*end), QPointF(*right))
        painter.setPen(QPen(outline, 2.2))
        painter.setBrush(QBrush(dot_color))
        for point in positions:
            if point is not None:
                painter.drawEllipse(QPointF(*point), 9.5, 9.5)
        painter.end()

    def _release_wire_buffers(self):
        """Release cached boundary geometry in a current OpenGL context."""
        if self._wire_vao is not None:
            glDeleteVertexArrays(1, [self._wire_vao])
            self._wire_vao = None
        if self._wire_vbo is not None:
            glDeleteBuffers(1, [self._wire_vbo])
            self._wire_vbo = None
        if self._wire_ebo is not None:
            glDeleteBuffers(1, [self._wire_ebo])
            self._wire_ebo = None
        self._wire_index_count = 0

    def _ensure_wireframe_buffers(self):
        """Build boundary edges only when first requested for this model."""
        if self._program is None or self._mesh is None or self._scene is None:
            return
        if self._wire_vao is not None:
            return
        if self._wire_mesh is None:
            self._wire_mesh = make_wireframe(self._scene.geometry, self._mesh)
        payload = self._wire_mesh.vertices
        self._wire_vao = int(glGenVertexArrays(1))
        self._wire_vbo = int(glGenBuffers(1))
        self._wire_ebo = int(glGenBuffers(1))
        glBindVertexArray(self._wire_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._wire_vbo)
        glBufferData(GL_ARRAY_BUFFER, payload.nbytes,
                     payload if payload.size else None, GL_STATIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 12, ctypes.c_void_p(0))
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._wire_ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, 0, None, GL_DYNAMIC_DRAW)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _refresh_wire_visibility(self):
        """Select original polygon edges by RES and track detail, not BSP.

        The fully expanded branch view remains available via Show all detail
        levels. Otherwise the standard camera-relative/manual RES distance
        applies exactly as in the filled renderer, while all BSP-facing
        branches remain see-through.
        """
        all_branches = self.lod_distance is None and not self._track_lod_active()
        if all_branches:
            # Preserve the legacy full-geometry diagnostic in explicit
            # Show all detail levels for non-track models.
            self._wire_index_count = 0
            self._visible_set = frozenset(self._model.polygons)
            self._visibility_info = {}
            self._visibility_dirty = False
            self.visibilityChanged.emit(
                f"Wireframe: {self._wire_mesh.segment_count:,} boundary edges "
                f"across {self._wire_mesh.polygon_count:,} polygons "
                "(all RES branches; BSP ignored; no triangle diagonals)")
            return

        eye = self._camera_eye_model()
        direction = None
        if not self.perspective:
            direction = (
                math.cos(self.elevation) * math.sin(self.azimuth),
                -math.cos(self.elevation) * math.cos(self.azimuth),
                math.sin(self.elevation))
        detail = self.track_detail if self._track_lod_active() else None
        window = None
        if detail == 'window':
            nav = self.track_navigation
            if nav is not None and self._scene.track_section_dlongs:
                window = (nav.dlong, nav.length, self.track_window_counts)
                detail = None
            else:
                detail = 'hi'
        indices, visible, info = ordered_scene_indices(
            self._scene, self._wire_mesh, eye, self.lod_distance,
            view_direction=direction, bsp_mode='off',
            track_detail=detail, track_window=window)
        glBindVertexArray(self._wire_vao)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._wire_ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes,
                     indices if indices.size else None, GL_DYNAMIC_DRAW)
        glBindVertexArray(0)
        self._wire_index_count = int(indices.size)
        self._visible_set = visible
        self._visibility_info = info
        self._visibility_dirty = False
        selected = ("selected track polygons" if self._track_lod_active()
                    else "selected polygons")
        self.visibilityChanged.emit(
            f"Wireframe: {self._wire_index_count // 2:,} boundary edges "
            f"across {info['mesh_polygons']:,} {selected} "
            "(RES respected; BSP ignored)")

    def _paint_wireframe(self, projection, view):
        """Only GL_LINES: no filled faces, sprites, skybox, or diagonal edges."""
        self._ensure_wireframe_buffers()
        if self._wire_vao is None:
            glUseProgram(0)
            return
        if self._visibility_dirty:
            self._refresh_wire_visibility()
        glUniform1i(self._wire_uniform, 1)
        glBindVertexArray(self._wire_vao)
        if self.lod_distance is None and not self._track_lod_active():
            if self._wire_mesh.vertices.size:
                glDrawArrays(GL_LINES, 0, len(self._wire_mesh.vertices))
        elif self._wire_index_count:
            glDrawElements(GL_LINES, self._wire_index_count, GL_UNSIGNED_INT, None)

        notice = None
        if self.inspection_kind == "polygon":
            flattened = self._scene.polygon_lookup.get((0, self.inspection_offset))
            span = self._wire_mesh.polygon_ranges.get(flattened)
            if span is None:
                notice = "POLY has no renderable outline in this scene"
            elif (self.lod_distance is not None or self._track_lod_active()) and (
                    self.inspection_offset not in self._visible_set):
                notice = "POLY not drawn: inactive SWITCH DISTANCE / track detail"
            else:
                glUniform1i(self._wire_uniform, 2)
                glDrawArrays(GL_LINES, *span)
                glUniform1i(self._wire_uniform, 1)
        glBindVertexArray(0)
        glUniform1i(self._wire_uniform, 0)
        glUseProgram(0)
        self._set_visibility_warning(notice)
        self._paint_source_inspection_markers(projection, view)

    def _upload_mesh(self):
        if self._program is None:
            return
        started = perf_counter()
        self._release_wire_buffers()
        self._wire_mesh = None
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
        if self._surface_ebo is not None:
            glDeleteBuffers(1, [self._surface_ebo])
            self._surface_ebo = None
        self._surface_index_count = 0
        self._visibility_dirty = True
        has_sprites = (self._scene is not None and
                       getattr(self._scene, "sprite_resources", None) is not None and
                       bool(self._scene.sprite_resources.placements))
        if self._mesh is not None and (self._mesh.vertices.size or has_sprites):
            # PMP-only 3DOs have no polygon VBO contents, but still need a
            # live VAO/EBO so BSP traversal and sprite draw passes run.
            payload = np.ascontiguousarray(
                self._mesh.vertices, dtype=np.float32).tobytes()
            self._vao = int(glGenVertexArrays(1))
            self._vbo = int(glGenBuffers(1))
            self._ebo = int(glGenBuffers(1))
            self._surface_ebo = int(glGenBuffers(1))
            glBindVertexArray(self._vao)
            glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
            glBufferData(GL_ARRAY_BUFFER, len(payload),
                         payload if payload else None, GL_STATIC_DRAW)
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

    def _delete_skybox_buffers(self):
        """Called only while the widget's OpenGL context is current."""
        if self._sky_vao is not None:
            glDeleteVertexArrays(1, [self._sky_vao])
            self._sky_vao = None
        if self._sky_vbo is not None:
            glDeleteBuffers(1, [self._sky_vbo])
            self._sky_vbo = None
        if self._sky_ebo is not None:
            glDeleteBuffers(1, [self._sky_ebo])
            self._sky_ebo = None
        if self._sky_atlas_texture is not None:
            glDeleteTextures(1, [self._sky_atlas_texture])
            self._sky_atlas_texture = None
        self._sky_index_count = 0

    def _upload_skybox(self):
        """Upload the sky's own VBO, EBO and MIP atlas once per model load."""
        self._delete_skybox_buffers()
        sky = self._scene.skybox if self._scene is not None else None
        if sky is None or not sky.indices.size:
            return
        payload = np.ascontiguousarray(sky.mesh.vertices, dtype=np.float32)
        indices = np.ascontiguousarray(sky.indices, dtype=np.uint32)
        self._sky_vao = int(glGenVertexArrays(1))
        self._sky_vbo = int(glGenBuffers(1))
        self._sky_ebo = int(glGenBuffers(1))
        glBindVertexArray(self._sky_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._sky_vbo)
        glBufferData(GL_ARRAY_BUFFER, payload.nbytes, payload, GL_STATIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 52, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 52, ctypes.c_void_p(12))
        for location, length, offset in ((2, 1, 24), (3, 2, 28),
                                         (4, 4, 36)):
            glEnableVertexAttribArray(location)
            glVertexAttribPointer(
                location, length, GL_FLOAT, GL_FALSE, 52, ctypes.c_void_p(offset))
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._sky_ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        glBindVertexArray(0)
        self._sky_index_count = int(indices.size)
        self._sky_atlas_texture = int(glGenTextures(1))
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._sky_atlas_texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        pixels = np.ascontiguousarray(sky.atlas.pixels, dtype=np.uint8)
        height, width = pixels.shape
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, width, height, 0,
                     GL_RED_INTEGER, GL_UNSIGNED_BYTE, pixels)

    def _draw_skybox(self, view, aspect):
        """Draw at a fixed local eye with camera rotation; no sky parallax."""
        sky = self._scene.skybox if self._scene is not None else None
        if (not self.sky_enabled or sky is None or self._sky_vao is None
                or not self._sky_index_count):
            return
        # A perspective background is used even for the orthographic track
        # editor, so the enclosed sky always fills the distant background.
        sky_projection = perspective_projection(
            aspect, 0.001, 100.0,
            self.fixed_camera_fov if (self.fixed_camera_mode or self.track_drive_enabled) else 60.0)
        sky_view = skybox_view_matrix(view, sky.mesh)
        mvp = np.ascontiguousarray(
            (sky_projection @ sky_view).T, dtype=np.float32)
        glDisable(GL_DEPTH_TEST)
        glUniformMatrix4fv(self._uniform, 1, GL_FALSE, mvp)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._sky_atlas_texture)
        glBindVertexArray(self._sky_vao)
        glDrawElements(GL_TRIANGLES, self._sky_index_count, GL_UNSIGNED_INT, None)
        # The caller restores the main view transform, atlas, and depth mode.

    def _upload_sprite_assets(self):
        """Upload indexed PMP assets on the GUI GL thread, never the worker."""
        if self._program is None or self._scene is None:
            return
        assets = getattr(self._scene, "sprite_resources", None)
        if assets is None or not assets.images:
            if self._sprite_renderer is not None:
                self._sprite_renderer.upload(None)
            return
        if self._sprite_renderer is None:
            self._sprite_renderer = PMPGLRenderer()
        self._sprite_renderer.upload(assets)

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

    def _track_lod_active(self):
        return bool(self._scene is not None and
                    self._scene.track_section_lods and self.track_detail)

    def set_render_mode(self, mode):
        if mode not in ('painter', 'depth', 'all', 'wire'):
            raise ValueError(f"Unknown render mode: {mode}")
        self.render_mode = mode
        if mode == 'all' and not self._track_lod_active():
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
        if self.track_drive_enabled and self._track_drive_pose is not None:
            return self._track_drive_pose.eye
        if self.fixed_camera_mode:
            return self.fixed_camera_eye
        return camera_in_model_units(
            self._mesh.center, self._mesh.scale, self.target,
            self.azimuth, self.elevation, self.distance)

    def _camera_view_matrix(self):
        """Fixed and track cameras change orientation without moving their eye."""
        target = self.target
        if (self.track_drive_enabled and self._track_drive_pose is not None
                and self._mesh is not None):
            target = fixed_eye_view_target(
                self._mesh.center, self._mesh.scale, self._track_drive_pose.eye,
                self.azimuth, self.elevation, self.distance)
        elif self.fixed_camera_mode and self._mesh is not None:
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
        window = None
        detail = self.track_detail if self._track_lod_active() else None
        if detail == 'window':
            navigation = self.track_navigation
            if (navigation is not None and self._scene.track_section_dlongs):
                window = (navigation.dlong, navigation.length,
                          self.track_window_counts)
                detail = None
            else:
                detail = 'hi'  # No TRK/metadata: safe global HI fallback.
        use_tsd = bool(self.render_mode == 'depth'
                       and self._scene.track_surface_details)
        traversal = ordered_scene_indices(
            self._scene, self._mesh, eye,
            None if self.render_mode == 'all' else self.lod_distance,
            view_direction=direction, with_sprites=True,
            with_surface_details=use_tsd,
            bsp_mode='off' if self.render_mode == 'all' else 'original',
            track_detail=detail, track_window=window)
        if use_tsd:
            indices, visible, info, sprite_events, surface_indices = traversal
        else:
            indices, visible, info, sprite_events = traversal
            surface_indices = np.empty(0, dtype=np.uint32)
        glBindVertexArray(self._vao)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes,
                     indices if indices.size else None, GL_DYNAMIC_DRAW)
        if self._surface_ebo is not None:
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._surface_ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, surface_indices.nbytes,
                         surface_indices if surface_indices.size else None,
                         GL_DYNAMIC_DRAW)
            # The regular EBO is the VAO's persistent binding; after drawing
            # decals below it must be restored too.
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBindVertexArray(0)
        self._surface_index_count = int(surface_indices.size)
        self._index_count = len(indices)
        self._sprite_events = sprite_events
        self._visible_set = visible
        self._visibility_info = info
        self._visibility_dirty = False
        self.visibilityChanged.emit(
            f"BSP visible {info['mesh_polygons']:,}/{self._mesh.polygon_count:,} "
            f"renderable polygons | {info['triangles']:,} triangles | "
            f"{info['tested_planes']:,} plane tests | "
            f"{info['culled_nodes']:,} pruned nodes | "
            f"{info['lod_selections']:,} LOD selections | "
            f"{info['instances_visited']:,} instances | "
            f"{info['pmp_sprites']:,} PMP sprites"
        )

    def _projection_and_view(self):
        """Use identical camera/frustum math for rendering and vertex clicks."""
        width = max(1, self.width())
        height = max(1, self.height())
        aspect = width / height
        near = 0.001
        far = max(100.0, 40.0 * self.distance)
        view, _, _ = self._camera_view_matrix()
        if self.perspective:
            projection = perspective_projection(
                aspect, near, far,
                self.fixed_camera_fov
                if (self.fixed_camera_mode or self.track_drive_enabled) else 60.0)
        else:
            projection = ortho_projection(
                self.half_height, aspect, near, far)
        return projection, view

    def set_pick_mode(self, mode):
        if mode not in ('vertex', 'polygon'):
            raise ValueError(f"Unknown viewport pick mode: {mode}")
        self.pick_mode = mode

    def pick_nearest_polygon(self, x, y):
        """Pick a rendered root POLY, honoring the current BSP/RES selection.

        Geometry from DYNAMIC/external child files is not selectable in the
        root .3D Source pane. Picking reads the existing GPU mesh on the CPU
        without touching GL or changing the drawn scene.
        """
        if self._polygon_picker is None or self._mesh is None:
            return None
        all_visible = (self.render_mode == 'all' and
                       not self._track_lod_active())
        if self._visibility_dirty and not all_visible:
            return None
        selected = None if all_visible else self._visible_set
        if selected is not None and not selected:
            return None
        projection, view = self._projection_and_view()
        return self._polygon_picker.nearest(
            projection @ view, x, y, self.width(), self.height(),
            eligible_offsets=selected)

    def pick_nearest_vertex(self, x, y):
        """Pick the closest on-screen *root* vertex near a left-click.

        DYNAMIC/external children have separate source files and cannot be
        selected in the currently edited root N3 pane. Honor the latest
        BSP/RES/track selection when it is available; never force unselected
        geometry into the view. No GL calls or source modifications.
        """
        if self._vertex_picker is None or self._mesh is None:
            return None
        if self._visibility_dirty and not (
                self.render_mode == 'all' and not self._track_lod_active()):
            return None
        selected = None
        if not (self.render_mode == 'all' and
                not self._track_lod_active()):
            if not self._visible_set:
                return None
            selected = set()
            for polygon_offset in self._visible_set:
                polygon = self._model.polygons.get(polygon_offset)
                if polygon is not None:
                    selected.update(polygon.unique_refs)
            if not selected:
                return None
        projection, view = self._projection_and_view()
        return self._vertex_picker.nearest(
            projection @ view, x, y, self.width(), self.height(),
            eligible_offsets=selected)

    def paintGL(self):
        if self._program is None:
            return
        # QOpenGLWidget makes its Qt-owned framebuffer current before
        # paintGL. Raw GL operates on it without taking ownership of it.
        w=max(1,int(self.width()*self.devicePixelRatioF()))
        h=max(1,int(self.height()*self.devicePixelRatioF()))
        glViewport(0,0,w,h)
        if self.render_mode in ('painter', 'wire'):
            # Wireframe is see-through; painter respects original LIST order. Depth testing
            # would defeat authored overlaps and coincident BSP2 front/back.
            glDisable(GL_DEPTH_TEST)
        else:
            glEnable(GL_DEPTH_TEST)
        glClearColor(*QColor(self.colors['viewport_background']).getRgbF())
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self._vao is None:
            return
        aspect=w/h
        projection, view = self._projection_and_view()
        matrix=np.ascontiguousarray((projection@view).T,dtype=np.float32)
        glUseProgram(self._program)
        glUniform3f(self._wire_color_uniform,
                    *self._wire_color_rgb("viewport_wire"))
        glUniform3f(self._selected_wire_color_uniform,
                    *self._wire_color_rgb("viewport_selected_wire"))
        glUniform3f(self._inspection_dark_uniform,
                    *self._wire_color_rgb("viewport_poly_tint_dark"))
        glUniform3f(self._inspection_light_uniform,
                    *self._wire_color_rgb("viewport_poly_tint_light"))
        glUniformMatrix4fv(self._uniform,1,GL_FALSE,matrix)
        glUniform1i(self._texture_uniform, int(self.textures_enabled))
        glUniform1i(self._repeat_uniform, int(self.texture_repeat))
        glUniform1i(self._inspection_uniform, 0)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._atlas_texture or 0)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self._palette_texture or 0)
        if self.render_mode == 'wire':
            self._paint_wireframe(projection, view)
            self._paint_split_preview(projection, view)
            return
        self._draw_skybox(view, aspect)
        glUniformMatrix4fv(self._uniform, 1, GL_FALSE, matrix)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._atlas_texture or 0)
        if self.render_mode != 'painter':
            glEnable(GL_DEPTH_TEST)
        if (self.render_mode != 'all' or self._track_lod_active()) and self._visibility_dirty:
            self._refresh_visibility()
        glBindVertexArray(self._vao)
        pmp_enabled = (self.textures_enabled and self.sprites_enabled and
                       self._sprite_renderer is not None and
                       self._scene is not None and
                       getattr(self._scene, "sprite_resources", None) is not None)
        if self.render_mode == 'all' and not self._track_lod_active():
            glDrawArrays(GL_TRIANGLES,0,self._mesh.vertices.shape[0])
            if pmp_enabled:
                # Diagnostic mode deliberately includes all LOD/BSP variants.
                for placement in self._scene.sprite_resources.placements.values():
                    self._draw_pmp(placement, projection, view)
        elif pmp_enabled and self._sprite_events:
            # Split the SAME EBO at sprite insertion markers so LIST/DYNAMIC
            # painter ordering remains faithful without repacking geometry.
            for command in draw_runs(self._index_count, self._sprite_events):
                if command[0] == "polygons":
                    glDrawElements(GL_TRIANGLES, command[2], GL_UNSIGNED_INT,
                                   ctypes.c_void_p(command[1] * 4))
                else:
                    placement = self._scene.sprite_resources.placements.get(
                        command[1])
                    if placement is not None:
                        self._draw_pmp(placement, projection, view)
        elif self._index_count:
            glDrawElements(GL_TRIANGLES, self._index_count, GL_UNSIGNED_INT, None)

        # Papyrus TSDs are coplanar or nearly coplanar POLYs painted onto
        # textured road sections. With GPU depth testing, drawing them only
        # once can lose depth tests and interleave road/marking pixels. Keep
        # authored BSP selection, then redraw ONLY the visible TSD triangles
        # with a slight depth bias toward the eye. Depth still rejects road
        # markings hidden by genuinely closer scenery. No source XYZ edits.
        # One batched draw avoids a GL call per stripe/line section.
        if (self.render_mode == 'depth' and self._surface_index_count and
                self._surface_ebo is not None):
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-1.0, -4.0)
            try:
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._surface_ebo)
                glDrawElements(GL_TRIANGLES, self._surface_index_count,
                               GL_UNSIGNED_INT, None)
            finally:
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
                glDisable(GL_POLYGON_OFFSET_FILL)

        # Source highlighting never draws a BSP/LOD-excluded polygon.
        # Apply contrast-aware color tinting to selected rendered faces.
        notice = None
        if self.inspection_kind == "polygon":
            span = polygon_mesh_range(
                self._scene, self._mesh, self.inspection_offset)
            if span is None or not span[1]:
                notice = "POLY has no renderable triangles in this scene"
            elif ((self.render_mode != "all" or self._track_lod_active()) and
                  self.inspection_offset not in self._visible_set):
                notice = polygon_inspection_notice(
                    self._model, self.inspection_offset, self._visible_set,
                    self.lod_distance, self._camera_eye_model(),
                    self.render_mode)
            else:
                # The selected face is part of the active traversal; tint
                # bright (even white) and dark polygons differently.
                glDisable(GL_DEPTH_TEST)
                glUniform1i(self._inspection_uniform, 1)
                glDrawArrays(GL_TRIANGLES, *span)
                glUniform1i(self._inspection_uniform, 0)

        glBindVertexArray(0)
        glUseProgram(0)
        self._set_visibility_warning(notice)
        self._paint_source_inspection_markers(projection, view)
        self._paint_split_preview(projection, view)

    def _draw_pmp(self, placement, projection, view):
        """Draw one palette-indexed transparent billboard at its BSP site."""
        self._sprite_renderer.draw(
            placement, self._mesh, projection, view, self._palette_texture)
        # Restore polygon state for the next BSP span or source highlight.
        glUseProgram(self._program)
        glBindVertexArray(self._vao)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._atlas_texture or 0)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self._palette_texture or 0)

    def _on_frame_swapped(self):
        now = perf_counter()
        self._frame_count += 1
        self._frametimes.append(now)
        if len(self._frametimes) >= 2:
            duration = self._frametimes[-1] - self._frametimes[0]
            if duration > 0.25:
                self.fps = (len(self._frametimes) - 1) / duration

    def set_track_navigation(self, navigation, *, preserve=False):
        """Attach a TRK without changing the already loaded geometry.

        Recompiling a track retains DLONG/DLAT and the user's on/off choice.
        Opening a different track starts at the start/finish line.
        """
        previous = self.track_navigation
        same = bool(preserve and navigation is not None and previous is not None
                    and navigation.path.resolve() == previous.path.resolve())
        active = self.track_drive_enabled
        if same:
            navigation.set_coordinates(previous.dlong, previous.dlat)
        elif active:
            self.set_track_drive_enabled(False)
        self.track_navigation = navigation
        if navigation is None:
            self._track_drive_pose = None
            return
        if same:
            if active:
                self._update_track_drive_pose()
        else:
            self.set_track_drive_enabled(True)

    def set_track_drive_enabled(self, enabled):
        """Follow TRK centerline in perspective, or restore prior orbit."""
        enabled = bool(enabled)
        if enabled and self.track_navigation is None:
            return
        if enabled == self.track_drive_enabled:
            return
        if enabled:
            if self.fixed_camera_mode:
                self.set_fixed_camera_mode(False)
            self._saved_track_view = (
                self.target.copy(), self.distance, self.half_height,
                self.perspective, self.azimuth, self.elevation)
            self.track_drive_enabled = True
            self.perspective = True
            self.fixed_camera_fov = 60.0
            self._update_track_drive_pose()
        else:
            self.track_drive_enabled = False
            self._track_drive_pose = None
            if self._saved_track_view is not None:
                (target, self.distance, self.half_height, self.perspective,
                 self.azimuth, self.elevation) = self._saved_track_view
                self.target = target.copy()
            self._saved_track_view = None
            self.invalidate_visibility()
        self.trackDriveModeChanged.emit(enabled)

    def _update_track_drive_pose(self):
        if not self.track_drive_enabled or self.track_navigation is None:
            return
        pose = self.track_navigation.pose()
        self._track_drive_pose = pose
        self.azimuth, self.elevation = pose.azimuth, pose.elevation
        self.trackDrivePositionChanged.emit(pose)
        self.invalidate_visibility()

    def move_track_drive(self, *, forward_feet=0.0, left_feet=0.0):
        if not self.track_drive_enabled or self.track_navigation is None:
            return False
        self.track_navigation.move(
            forward_feet=forward_feet, left_feet=left_feet)
        self._update_track_drive_pose()
        return True

    def keyPressEvent(self, event):
        """W/Up forward, S/Down backward, A/Left left, D/Right right."""
        if self.track_drive_enabled and not (
                event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                     | Qt.KeyboardModifier.AltModifier)):
            multiplier = (5 if event.modifiers()
                          & Qt.KeyboardModifier.ShiftModifier else 1)
            key = event.key()
            forward, left = 0.0, 0.0
            if key in (Qt.Key.Key_W, Qt.Key.Key_Up):
                forward = self.track_forward_step_ft * multiplier
            elif key in (Qt.Key.Key_S, Qt.Key.Key_Down):
                forward = -self.track_forward_step_ft * multiplier
            elif key in (Qt.Key.Key_A, Qt.Key.Key_Left):
                left = self.track_lateral_step_ft * multiplier
            elif key in (Qt.Key.Key_D, Qt.Key.Key_Right):
                left = -self.track_lateral_step_ft * multiplier
            else:
                super().keyPressEvent(event)
                return
            self.move_track_drive(forward_feet=forward, left_feet=left)
            event.accept()
            return
        super().keyPressEvent(event)

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
        if enabled and self.track_drive_enabled:
            self.set_track_drive_enabled(False)
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
        if self.track_drive_enabled:
            self.set_track_drive_enabled(False)
        if self.fixed_camera_mode:
            self.set_fixed_camera_mode(False)
        self.target[:] = 0
        self.distance = 4.0
        self.half_height = 1.6
        self.invalidate_visibility()

    def set_view(self, name):
        if self.track_drive_enabled:
            self.set_track_drive_enabled(False)
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
        if self.fixed_camera_mode or self.track_drive_enabled:
            # Fixed/track camera position stays put; wheel changes FOV.
            # letting skybox authors examine details while stationary.
            self.fixed_camera_fov = min(110.0, max(20.0, self.fixed_camera_fov * multiplier))
            self.update()
        else:
            self.half_height = min(1000.0, max(.0001, self.half_height * multiplier))
            self.distance = min(1000.0, max(.001, self.distance * multiplier))
            self.invalidate_visibility()
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._drag = (event.position(), event.button())
        self._pick_press = (
            event.position(), event.button(), event.modifiers())
        self._pick_dragged = False
        event.accept()

    def mouseReleaseEvent(self, event):
        pressed = self._pick_press
        self._drag = None
        self._pick_press = None
        if (pressed is not None
                and pressed[1] == Qt.MouseButton.LeftButton
                and event.button() == Qt.MouseButton.LeftButton
                and not self._pick_dragged
                and not (pressed[2] | event.modifiers())
                & Qt.KeyboardModifier.ShiftModifier):
            if self.pick_mode == 'polygon':
                offset = self.pick_nearest_polygon(
                    event.position().x(), event.position().y())
                if offset is not None:
                    self.polygonPicked.emit(offset)
            else:
                offset = self.pick_nearest_vertex(
                    event.position().x(), event.position().y())
                if offset is not None:
                    self.vertexPicked.emit(offset)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        old, button = self._drag
        dx = event.position().x() - old.x()
        dy = event.position().y() - old.y()
        if self._pick_press is not None:
            origin = self._pick_press[0]
            if ((event.position().x() - origin.x())**2 +
                    (event.position().y() - origin.y())**2 > 16):
                self._pick_dragged = True
        self._drag = (event.position(), button)
        if button == Qt.MouseButton.MiddleButton or (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            if not self.fixed_camera_mode and not self.track_drive_enabled:
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
        self._loaded_file_path = None  # committed open, not an in-flight/failed file
        self._find_text = ""
        self._preserve_view = False
        self._source_invalid = False
        self._source_busy_revision = None
        self._source_queued = None
        self._source_export_worker = None
        self._source_export_model = None
        self._source_applied = False
        self._last_valid_source_text = None
        self._source_save_target = None
        self._pending_vertex_pick = None
        self._pending_polygon_pick = None
        self._split_polygon_offset = None
        self._pending_split_label = None
        self.appearance_colors = load_colors(QSettings("ICR2Tools", "GPUViewer"))
        self.viewer = GLViewport()
        self.viewer.set_appearance_colors(self.appearance_colors)
        self.load_label = QLabel("Open a .3D or .3DO model")
        self.load_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats_label = QLabel("No model loaded")
        self.visibility_label = QLabel("BSP status will appear here")
        self.polygon_status = QLabel("Enter a polygon body offset to inspect")
        self.palette_status = QLabel("Palette: bundled gamepal.pcx")
        self.texture_status = QLabel("MIPs: no model loaded")
        self.sprite_status = QLabel("PMP sprites: no model loaded")
        self.car_status = QLabel("Individual-car RECOLOR: not loaded")
        root = QWidget()
        layout = QVBoxLayout(root)
        # Collapsible, scrollable settings leave the majority of the window to the model.
        # The document area contains only the GPU viewport and N3 editor.
        # The former sidebar widgets live in nonmodal, scrollable dialogs,
        # so all existing controls and signal connections remain intact.
        self.settings_dialogs = {}
        self._load_issues = ()
        self._load_log_file = None
        self._init_load_error_dialog()
        model_layout = self._make_settings_dialog("model", "Model Settings")
        display_layout = self._make_settings_dialog("display", "Display Settings")
        assets_layout = self._make_settings_dialog("assets", "Asset Settings")
        advanced_layout = self._make_settings_dialog(
            "advanced", "Advanced Diagnostics")

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
        # Menu state is backed by this control, but there is no toolbar.
        self.source_toggle = QPushButton(".3D Source", self)
        self.source_toggle.setCheckable(True)
        self.source_toggle.toggled.connect(self._toggle_source)
        self.source_toggle.hide()
        self.benchmark_toggle = QCheckBox("Continuous 60 Hz benchmark")
        self.benchmark_toggle.setChecked(benchmark)
        advanced_layout.addWidget(self.benchmark_toggle)

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
        self.mode_combo.addItem("Papyrus drawing order (no depth)", "painter")
        self.mode_combo.addItem("BSP selection + GPU depth", "depth")
        self.mode_combo.addItem("All polygons + GPU depth", "all")
        self.mode_combo.addItem("Wireframe (polygon outlines only)", "wire")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        advanced_layout.addWidget(self.mode_combo)

        # Compact control bar lives directly above the GPU viewport, not in
        # the optional Display Settings dialog. Reuse the existing widgets and
        # LOD signals; there must be only one authoritative distance value.
        self.distance_bar = QWidget()
        distance_row = QHBoxLayout(self.distance_bar)
        distance_row.setContentsMargins(5, 3, 5, 3)
        distance_row.setSpacing(6)
        distance_row.addWidget(QLabel("Projection"))
        self.projection_combo = QComboBox()
        self.projection_combo.setObjectName("projectionCombo")
        self.projection_combo.addItem("Perspective", True)
        self.projection_combo.addItem("Orthographic", False)
        self.projection_combo.setToolTip(
            "Switch camera projection. Fixed Camera and TRK driving "
            "require Perspective.")
        self.projection_combo.currentIndexChanged.connect(
            self._projection_changed)
        self.perspective_toggle.setChecked(True)
        distance_row.addWidget(self.projection_combo)
        distance_row.addWidget(QLabel("Pick"))
        self.pick_mode_combo = QComboBox()
        self.pick_mode_combo.setObjectName("viewportPickMode")
        self.pick_mode_combo.addItem("Vertices", "vertex")
        self.pick_mode_combo.addItem("Polys", "polygon")
        self.pick_mode_combo.setToolTip(
            "Viewport left-click selects vertices by default. Select Polys "
            "to click polygon faces and jump to their .3D source row.")
        self.pick_mode_combo.currentIndexChanged.connect(
            lambda _: self.viewer.set_pick_mode(self.pick_mode_combo.currentData()))
        distance_row.addWidget(self.pick_mode_combo)
        self.split_button = QPushButton("Split polygon…")
        self.split_button.setCheckable(True)
        self.split_button.setObjectName("openPolygonSplitPanel")
        self.split_button.setToolTip(
            "Open the polygon split controls beneath the viewport; click "
            "a face in Polys pick mode to select the target.")
        self.split_button.toggled.connect(self._toggle_split_tool)
        distance_row.addWidget(self.split_button)
        distance_label = QLabel("SWITCH DISTANCE")
        distance_label.setToolTip(
            "Controls RES/SWITCH DISTANCE in the currently opened model.")
        distance_row.addWidget(distance_label)
        self.lod_mode_combo = QComboBox()
        self.lod_mode_combo.addItem("Auto", "auto")
        self.lod_mode_combo.addItem("Manual", "manual")
        self.lod_mode_combo.addItem("All levels", "all")
        self.lod_mode_combo.setToolTip(
            "Auto: camera-relative to each RES anchor. Manual: exact "
            "distance on the slider. All levels: ignore RES thresholds.")
        self.lod_mode_combo.currentIndexChanged.connect(self._lod_changed)
        distance_row.addWidget(self.lod_mode_combo)
        self.lod_slider = QSlider(Qt.Orientation.Horizontal)
        self.lod_slider.setRange(0, 0)
        self.lod_slider.setEnabled(False)
        self.lod_slider.setToolTip(
            "Manual SWITCH DISTANCE in raw Papyrus model units. "
            "Drag or use the arrows to enable Manual mode.")
        self.lod_slider.sliderPressed.connect(self._activate_manual_distance)
        self.lod_slider.valueChanged.connect(self._slider_distance_changed)
        distance_row.addWidget(self.lod_slider, 1)
        self.lod_spin = QSpinBox()
        self.lod_spin.setRange(0, 0)
        self.lod_spin.setKeyboardTracking(False)
        self.lod_spin.setToolTip(
            "Exact SWITCH DISTANCE; editing selects Manual mode.")
        self.lod_spin.valueChanged.connect(self._spin_distance_changed)
        self.lod_spin.setEnabled(False)
        distance_row.addWidget(self.lod_spin)
        self.lod_max_label = QLabel("No RES")
        self.lod_max_label.setToolTip(
            "The slider's maximum is the highest SWITCH DISTANCE threshold "
            "in the loaded scene.")
        distance_row.addWidget(self.lod_max_label)
        display_layout.addWidget(QLabel(
            "SWITCH DISTANCE / RES is adjusted above the viewport."))

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
        self.show_sprites = QCheckBox("PMP sprites (PMP/PMP2)")
        self.show_sprites.setToolTip(
            "Render viewpoint-selected billboards from this 3DO and nested "
            "referenced objects. Requires Textures enabled.")
        self.show_sprites.setChecked(True)
        self.show_sprites.toggled.connect(self._sprites_toggled)
        display_layout.addWidget(self.show_sprites)
        self.repeat_uv = QCheckBox("Repeat UV (tile MIPs)")
        self.repeat_uv.setChecked(self.viewer.texture_repeat)
        self.repeat_uv.setToolTip(
            "Repeat MIP pixels in U and V when coordinates extend beyond the "
            "individual image's dimensions. Applies to .3D and .3DO alike; "
            "uncheck only to diagnose clamp-to-edge rendering.")
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
        track_layout.addWidget(QLabel("Track section detail"))
        self.track_detail_combo = QComboBox()
        self.track_detail_combo.addItem("Camera window (HI / MED / LO)", "window")
        self.track_detail_combo.addItem("HI (4 geometry slots)", "hi")
        self.track_detail_combo.addItem("MED (2 geometry slots)", "med")
        self.track_detail_combo.addItem("LO (1 geometry slot)", "lo")
        self.track_detail_combo.setCurrentIndex(
            self.track_detail_combo.findData('hi'))
        self.track_detail_combo.model().item(0).setEnabled(False)
        self.track_detail_combo.setEnabled(False)
        self.track_detail_combo.setToolTip(
            "Camera window uses section DATA DLONG positions and the TRK "
            "camera (8 HI, 5 MED, 3 LO ahead and behind). Other sections "
            "are omitted. Global HI/MED/LO remain available for overview.")
        self.track_detail_combo.currentIndexChanged.connect(self._track_detail_changed)
        track_layout.addWidget(self.track_detail_combo)
        self.track_detail_status = QLabel(
            "No eight-entry Papyrus track section index detected")
        self.track_detail_status.setWordWrap(True)
        track_layout.addWidget(self.track_detail_status)
        track_layout.addWidget(QLabel(
            "Camera window sections each way (current section always HI)"))
        window_counts = QHBoxLayout()
        self.track_window_spins = []
        for label, count in zip(('HI', 'MED', 'LO'), DEFAULT_WINDOW_COUNTS):
            window_counts.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(0, 250)
            spin.setValue(count)
            spin.setEnabled(False)
            spin.setToolTip(
                f"Number of {label} sections in each direction from the "
                "camera. Zero disables this tier; overlaps use closer detail.")
            spin.valueChanged.connect(self._track_window_changed)
            window_counts.addWidget(spin)
            self.track_window_spins.append(spin)
        track_layout.addLayout(window_counts)
        self.track_drive_checkbox = QCheckBox("TRK camera — follow racing direction")
        self.track_drive_checkbox.setEnabled(False)
        self.track_drive_checkbox.setToolTip(
            "Find a same-named .TRK beside this track. Follow its physics "
            "centerline from DLONG=0 at 6 feet above the surface. Click the "
            "3D viewport, then W/Up forward, S/Down back, A/Left left "
            "(+DLAT), D/Right right (-DLAT); hold Shift for 5x movement.")
        self.track_drive_checkbox.toggled.connect(self._track_drive_toggled)
        track_layout.addWidget(self.track_drive_checkbox)
        self.trk_drive_status = QLabel("No matching .TRK loaded")
        self.trk_drive_status.setWordWrap(True)
        track_layout.addWidget(self.trk_drive_status)
        track_steps = QHBoxLayout()
        track_steps.addWidget(QLabel("Forward ft/key"))
        self.trk_forward_step = QSpinBox()
        self.trk_forward_step.setRange(1, 1000)
        self.trk_forward_step.setValue(int(DEFAULT_LONG_STEP_FT))
        self.trk_forward_step.valueChanged.connect(self._trk_steps_changed)
        track_steps.addWidget(self.trk_forward_step)
        track_steps.addWidget(QLabel("Lateral ft/key"))
        self.trk_lateral_step = QSpinBox()
        self.trk_lateral_step.setRange(1, 100)
        self.trk_lateral_step.setValue(int(DEFAULT_LAT_STEP_FT))
        self.trk_lateral_step.valueChanged.connect(self._trk_steps_changed)
        track_steps.addWidget(self.trk_lateral_step)
        track_layout.addLayout(track_steps)
        self.trk_reset_button = QPushButton("Go to DLONG = 0 / DLAT = 0")
        self.trk_reset_button.setEnabled(False)
        self.trk_reset_button.clicked.connect(self._reset_trk_camera)
        track_layout.addWidget(self.trk_reset_button)
        self.show_skybox = QCheckBox("Skybox (horiz.3do / horiz.3d)")
        self.show_skybox.setChecked(True)
        self.show_skybox.setEnabled(False)
        self.show_skybox.setToolTip(
            "Display HORIZ.3DO or HORIZ.3D as a camera-following background at "
            "its local eye (0, 0, 1000). Only available on indexed tracks.")
        self.show_skybox.toggled.connect(self._skybox_toggled)
        track_layout.addWidget(self.show_skybox)
        self.skybox_status = QLabel("No track skybox loaded")
        self.skybox_status.setWordWrap(True)
        track_layout.addWidget(self.skybox_status)
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
        self.viewport_panel = QWidget()
        self.viewport_layout = QVBoxLayout(self.viewport_panel)
        self.viewport_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport_layout.setSpacing(0)
        self.viewport_layout.addWidget(self.distance_bar)
        self.viewport_layout.addWidget(self.viewer, stretch=1)
        # Contextual split controls sit BELOW the GPU viewport rather than
        # consuming the N3 source editor's horizontal space.
        self.split_panel = QGroupBox("Polygon split")
        self.split_panel.setObjectName("polygonSplitPanel")
        split_layout = QVBoxLayout(self.split_panel)
        split_layout.setContentsMargins(8, 5, 8, 6)
        split_layout.setSpacing(4)
        split_top = QHBoxLayout()
        self.split_target_label = QLabel("Select a polygon in the viewport")
        self.split_target_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        split_top.addWidget(self.split_target_label, 1)
        self.split_mode_combo = QComboBox()
        self.split_mode_combo.addItem("Cut between edges (new vertices)", "edges")
        self.split_mode_combo.addItem("Diagonal between existing vertices", "vertices")
        self.split_mode_combo.currentIndexChanged.connect(
            self._split_controls_changed)
        split_top.addWidget(self.split_mode_combo)
        split_layout.addLayout(split_top)

        self.split_edge_row = QWidget()
        edge_row = QHBoxLayout(self.split_edge_row)
        edge_row.setContentsMargins(0, 0, 0, 0)
        self.split_edge_a = QComboBox()
        self.split_edge_b = QComboBox()
        self.split_fraction_a = QDoubleSpinBox()
        self.split_fraction_b = QDoubleSpinBox()
        for label, choice, fraction in (
                ("Edge A", self.split_edge_a, self.split_fraction_a),
                ("Edge B", self.split_edge_b, self.split_fraction_b)):
            edge_row.addWidget(QLabel(label))
            choice.setMinimumWidth(130)
            choice.currentIndexChanged.connect(self._split_controls_changed)
            edge_row.addWidget(choice, 1)
            edge_row.addWidget(QLabel("Fraction"))
            fraction.setDecimals(3)
            fraction.setRange(0.001, 0.999)
            fraction.setSingleStep(0.05)
            fraction.setValue(0.5)
            fraction.valueChanged.connect(self._split_controls_changed)
            edge_row.addWidget(fraction)
        split_layout.addWidget(self.split_edge_row)

        self.split_vertex_row = QWidget()
        vertex_row = QHBoxLayout(self.split_vertex_row)
        vertex_row.setContentsMargins(0, 0, 0, 0)
        self.split_vertex_a = QComboBox()
        self.split_vertex_b = QComboBox()
        for label, choice in (("Vertex A", self.split_vertex_a),
                              ("Vertex B", self.split_vertex_b)):
            vertex_row.addWidget(QLabel(label))
            choice.currentIndexChanged.connect(self._split_controls_changed)
            vertex_row.addWidget(choice, 1)
        split_layout.addWidget(self.split_vertex_row)

        split_bottom = QHBoxLayout()
        self.split_preview_check = QCheckBox("Preview proposed cut")
        self.split_preview_check.setChecked(True)
        self.split_preview_check.toggled.connect(self._split_controls_changed)
        split_bottom.addWidget(self.split_preview_check)
        split_bottom.addStretch(1)
        self.split_apply_button = QPushButton("Split polygon")
        self.split_apply_button.clicked.connect(self._commit_polygon_split)
        split_bottom.addWidget(self.split_apply_button)
        split_cancel = QPushButton("Close")
        split_cancel.clicked.connect(lambda: self.split_button.setChecked(False))
        split_bottom.addWidget(split_cancel)
        split_layout.addLayout(split_bottom)
        self.split_hint_label = QLabel(
            "Select a root-model POLY. Edge fractions run from 0 to 1.")
        self.split_hint_label.setWordWrap(True)
        split_layout.addWidget(self.split_hint_label)
        self.viewport_layout.addWidget(self.split_panel)
        self.split_panel.hide()
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.addWidget(self.viewport_panel)
        self.source_pane = SourcePane()
        self.source_pane.set_appearance_colors(self.appearance_colors)
        self.editor_splitter.addWidget(self.source_pane)
        self.editor_splitter.setStretchFactor(0, 2)
        self.editor_splitter.setStretchFactor(1, 1)
        self.source_pane.hide()
        layout.addWidget(self.editor_splitter, stretch=1)
        for label in (self.stats_label, self.visibility_label,
                      self.polygon_status, self.palette_status,
                      self.texture_status, self.sprite_status,
                      self.car_status,
                      self.track_status, self.object_status):
            label.setWordWrap(True)
        advanced_layout.addWidget(self.stats_label)
        advanced_layout.addWidget(self.visibility_label)
        advanced_layout.addWidget(self.polygon_status)
        assets_layout.addWidget(self.palette_status)
        assets_layout.addWidget(self.texture_status)
        assets_layout.addWidget(self.sprite_status)
        self.setCentralWidget(root)
        # Source is the only secondary pane, shown alongside the viewport.
        self.source_toggle.setChecked(True)
        install_menus(self)
        self._workspace_changed(self.workspace_tabs.currentIndex())
        self._sync_projection_controls()
        self.source_pane.editor.textChanged.connect(self._update_window_title)
        self.source_pane.editor.textChanged.connect(self._split_controls_changed)
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
        self.viewer.trackDriveModeChanged.connect(self._track_drive_mode_changed)
        self.viewer.trackDrivePositionChanged.connect(self._track_drive_position_changed)
        self.source_pane.compileRequested.connect(self._source_requested)
        self.source_pane.saveRequested.connect(self._save_source)
        self.source_pane.exportRequested.connect(self._export_compiled_source)
        self.source_pane.cursorTargetChanged.connect(self._source_target_changed)
        self.viewer.vertexPicked.connect(self._viewport_vertex_picked)
        self.viewer.polygonPicked.connect(self._viewport_polygon_picked)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._benchmark_tick)
        self.benchmark_toggle.toggled.connect(self._toggle_benchmark)
        if benchmark:
            self._timer.start()
        if path:
            # Opening after the window is visible avoids blocking Qt setup.
            QTimer.singleShot(0, lambda: self.load(path))

    def _set_appearance_colors(self, colors):
        """Apply a consistent source/viewport palette and persist it per user."""
        self.appearance_colors = validated_colors(colors)
        self.source_pane.set_appearance_colors(self.appearance_colors)
        self.viewer.set_appearance_colors(self.appearance_colors)
        save_colors(QSettings("ICR2Tools", "GPUViewer"), self.appearance_colors)

    def customize_colors(self):
        AppearanceDialog(
            self.appearance_colors, self._set_appearance_colors, self).exec()

    def _init_load_error_dialog(self):
        """One nonmodal window for the latest model-load diagnostics."""
        dialog = QDialog(self)
        dialog.setObjectName("loadErrorLogDialog")
        dialog.setWindowTitle("Load Error Log — ICR2 GPU Viewer")
        dialog.setModal(False)
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        self.load_error_summary = QLabel("No model loaded")
        self.load_error_summary.setWordWrap(True)
        layout.addWidget(self.load_error_summary)
        self.load_error_text = QPlainTextEdit(dialog)
        self.load_error_text.setObjectName("loadErrorLogText")
        self.load_error_text.setReadOnly(True)
        self.load_error_text.setPlainText(
            "No model has been loaded yet.\n")
        layout.addWidget(self.load_error_text, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        copy_button = buttons.addButton(
            "Copy Log", QDialogButtonBox.ButtonRole.ActionRole)
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.load_error_text.toPlainText()))
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)
        self.load_error_dialog = dialog

    def _update_load_error_log(self, filename, issues, *, auto_show=False):
        """Replace stale diagnostics; auto-popup only after user model loads."""
        self._load_log_file = str(filename)
        self._load_issues = tuple(issues)
        count = len(self._load_issues)
        basename = Path(filename).name
        self.load_error_summary.setText(
            f"{basename}: {count} load issue{'s' if count != 1 else ''}"
            if count else f"{basename}: no reported load issues")
        self.load_error_text.setPlainText(
            format_load_log(filename, self._load_issues))
        self.load_error_text.moveCursor(
            self.load_error_text.textCursor().MoveOperation.Start)
        if auto_show:
            if count:
                self.open_load_error_log()
            else:
                # Don't leave a previous model's automatic issue popup open
                # after a fresh, clean model load.
                self.load_error_dialog.hide()

    def open_load_error_log(self):
        """View the latest log even after dismissing its automatic popup."""
        dialog = self.load_error_dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _make_settings_dialog(self, key, title):
        """Create an optional settings window without occupying viewport space."""
        dialog = QDialog(self)
        dialog.setObjectName(f"{key}SettingsDialog")
        dialog.setWindowTitle(f"{title} — ICR2 GPU Viewer")
        dialog.setModal(False)
        dialog.resize(520, 640)
        outer = QVBoxLayout(dialog)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        content = QWidget()
        controls = QVBoxLayout(content)
        controls.setContentsMargins(12, 12, 12, 12)
        controls.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.close)
        outer.addWidget(buttons)
        self.settings_dialogs[key] = dialog
        return controls

    def open_settings_dialog(self, key, *, workspace=None):
        """Open a dialog on demand; never transfer/recreate control state."""
        if workspace is not None:
            self.workspace_tabs.setCurrentIndex(workspace)
        dialog = self.settings_dialogs[key]
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _workspace_changed(self, index):
        if 0 <= index < self.workspace_tabs.count():
            self.fallback_controls.setVisible(
                self.workspace_tabs.tabText(index) != "Car")
        self._update_window_title()

    def _update_window_title(self):
        """Show the last successfully loaded file and unsaved source edits."""
        workspace = self.workspace_tabs.tabText(
            self.workspace_tabs.currentIndex())
        title = f"ICR2 GPU Viewer — {workspace} workspace"
        if self._loaded_file_path is not None:
            changed = " *" if self.source_pane.dirty else ""
            title = f"{self._loaded_file_path.name}{changed} — {title}"
        self.setWindowTitle(title)

    def _edit_source_command(self, command):
        """Standard text operations target the focused editor or N3 source."""
        widget = QApplication.focusWidget()
        while widget is not None and not isinstance(
                widget, (QPlainTextEdit, QLineEdit)):
            widget = widget.parentWidget()
        if widget is None:
            if not self.source_pane.ready:
                self._source_toolbar_action(lambda: None)
                return
            if self.source_pane.source_stack.currentWidget() != self.source_pane.editor:
                self.source_pane._show_all_filters()
            widget = self.source_pane.editor
        if command not in ("copy", "selectAll") and widget.isReadOnly():
            return
        getattr(widget, command)()

    def _scale_model(self):
        """Ask for a uniform multiply/divide factor and edit canonical N3.

        If source is lazy-loaded, request it without silently scaling an old
        model. The edit stays in the source document until Save/Export.
        """
        if not self.source_pane.ready:
            self._source_toolbar_action(lambda: None)
            return
        dialog = ScaleModelDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            result = self.source_pane.scale_model(
                dialog.factor_text, divide=dialog.divide)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot scale .3D model", str(exc))
            return
        self.statusBar().showMessage(
            result.summary() + ". Recompiling; changes are not saved.")

    def _find_source(self, *, next_match=False):
        """Find across the complete N3 text, including hidden filter rows."""
        if not self.source_pane.ready:
            self._source_toolbar_action(lambda: None)
            return
        if not self.source_toggle.isChecked():
            self.source_toggle.setChecked(True)
        if self.source_pane.source_stack.currentWidget() != self.source_pane.editor:
            self.source_pane._show_all_filters()
        if not next_match:
            query, accepted = QInputDialog.getText(
                self, "Find in .3D Source", "Find text:",
                QLineEdit.EchoMode.Normal, self._find_text)
            if not accepted or not query:
                return
            self._find_text = query
        if not self._find_text:
            return
        editor = self.source_pane.editor
        if not editor.find(self._find_text):
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            if not editor.find(self._find_text):
                self.statusBar().showMessage(
                    f"Not found in .3D Source: {self._find_text}")
                return
        editor.setFocus(Qt.FocusReason.OtherFocusReason)

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

    def _sprites_toggled(self, checked):
        self.viewer.sprites_enabled = checked
        self.viewer.update()

    def _repeat_toggled(self, checked):
        self.viewer.texture_repeat = checked
        self.viewer.update()

    def _trk_steps_changed(self, *_):
        self.viewer.track_forward_step_ft = float(self.trk_forward_step.value())
        self.viewer.track_lateral_step_ft = float(self.trk_lateral_step.value())

    def _track_drive_toggled(self, enabled):
        self.viewer.set_track_drive_enabled(enabled)
        if enabled:
            self.viewer.setFocus(Qt.FocusReason.OtherFocusReason)

    def _reset_trk_camera(self):
        nav = self.viewer.track_navigation
        if nav is None:
            return
        nav.set_coordinates(0.0, 0.0)
        if not self.viewer.track_drive_enabled:
            self.viewer.set_track_drive_enabled(True)
        else:
            self.viewer._update_track_drive_pose()
        self.viewer.setFocus(Qt.FocusReason.OtherFocusReason)

    def _track_drive_mode_changed(self, enabled):
        self.track_drive_checkbox.blockSignals(True)
        self.track_drive_checkbox.setChecked(enabled)
        self.track_drive_checkbox.blockSignals(False)
        self._sync_projection_controls()
        if enabled:
            self.viewer.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_trk_status()

    def _track_drive_position_changed(self, pose):
        self._update_trk_status()

    def _update_trk_status(self):
        nav = self.viewer.track_navigation
        if nav is None:
            return
        pose = nav.pose()
        state = "Driving" if self.viewer.track_drive_enabled else "Available, off"
        self.trk_drive_status.setText(
            f"{nav.path.name}: {state} | section {pose.section} | "
            f"DLONG {pose.dlong/UNITS_PER_FOOT:,.1f} ft "
            f"({pose.dlong:,.0f} units) | "
            f"DLAT {pose.dlat/UNITS_PER_FOOT:+,.1f} ft "
            f"({pose.dlat:+,.0f} units) | "
            f"camera XYZ ({pose.eye[0]:,.0f}, {pose.eye[1]:,.0f}, "
            f"{pose.eye[2]:,.0f}) | Click viewport, use WASD/arrows; "
            f"Shift = 5x")

    def _toggle_split_tool(self, enabled):
        self.split_panel.setVisible(enabled)
        if enabled:
            self.pick_mode_combo.setCurrentIndex(
                self.pick_mode_combo.findData("polygon"))
            target = self.source_pane.current_target()
            if target and target[0] == "polygon":
                offset = target_offset(self.viewer._model, *target)
                if offset is not None:
                    self._set_split_target(offset)
            self._split_controls_changed()
        else:
            self.viewer.set_split_preview()

    def _set_split_target(self, offset):
        """Populate cut choices from the exact selected root POLY order."""
        model = self.viewer._model
        if model is None or offset not in model.polygons:
            offset = None
        if offset == self._split_polygon_offset:
            self._split_controls_changed()
            return
        self._split_polygon_offset = offset
        polygon = model.polygons[offset] if offset is not None else None
        for combo in (self.split_edge_a, self.split_edge_b,
                      self.split_vertex_a, self.split_vertex_b):
            combo.blockSignals(True)
            combo.clear()
        try:
            if polygon is not None:
                refs = polygon_boundary_refs(polygon)
                for i, ref in enumerate(refs):
                    self.split_vertex_a.addItem(f"#{i+1}  @{ref}", i)
                    self.split_vertex_b.addItem(f"#{i+1}  @{ref}", i)
                    name = f"#{i+1}  @{ref} → @{refs[(i+1)%len(refs)]}"
                    self.split_edge_a.addItem(name, i)
                    self.split_edge_b.addItem(name, i)
                opposite = len(refs) // 2
                self.split_edge_b.setCurrentIndex(opposite)
                self.split_vertex_b.setCurrentIndex(opposite)
        finally:
            for combo in (self.split_edge_a, self.split_edge_b,
                          self.split_vertex_a, self.split_vertex_b):
                combo.blockSignals(False)
        if polygon is None:
            self.split_target_label.setText("Select a root-model polygon")
        else:
            self.split_target_label.setText(
                f"Selected POLY @{offset} · {len(polygon_boundary_refs(polygon))} vertices · "
                f"palette {polygon.color}")
        self._split_controls_changed()

    def _split_controls_changed(self, *_):
        if not hasattr(self, "split_preview_check"):
            return  # Fraction spin boxes emit during panel construction.
        mode = self.split_mode_combo.currentData()
        self.split_edge_row.setVisible(mode == "edges")
        self.split_vertex_row.setVisible(mode == "vertices")
        model = self.viewer._model
        offset = self._split_polygon_offset
        valid = (model is not None and offset in model.polygons
                 and self.source_pane.ready and not self.source_pane.pending
                 and not self._source_invalid and self._source_queued is None
                 and self._source_busy_revision is None)
        points = None
        hint = "Choose a root-model POLY by clicking its face."
        if valid:
            polygon = model.polygons[offset]
            refs = polygon_boundary_refs(polygon)
            n = len(refs)
            if mode == "edges":
                a = self.split_edge_a.currentData()
                b = self.split_edge_b.currentData()
                valid = a is not None and b is not None and a != b
                if valid:
                    def edge_point(i, t):
                        start = model.vertices[refs[i]].xyz
                        end = model.vertices[refs[(i+1) % n]].xyz
                        return tuple(start[j] + (end[j]-start[j])*t
                                     for j in range(3))
                    points = (edge_point(a, self.split_fraction_a.value()),
                              edge_point(b, self.split_fraction_b.value()))
                hint = ("Choose two different edges; fraction 0.5 is the "
                        "midpoint. Matching adjacent faces are updated.")
            else:
                a = self.split_vertex_a.currentData()
                b = self.split_vertex_b.currentData()
                valid = (n >= 4 and a is not None and b is not None
                         and a != b and (a-b) % n not in (1, n-1))
                if valid:
                    points = (model.vertices[refs[a]].xyz,
                              model.vertices[refs[b]].xyz)
                hint = ("Choose two nonadjacent vertices to make an internal "
                        "diagonal; no new vertices will be created.")
        elif model is not None and offset in model.polygons:
            hint = ("Prepare or validate the editable .3D Source first. "
                    "A pending or invalid source cannot be split.")
        self.split_apply_button.setEnabled(bool(valid))
        self.split_hint_label.setText(hint)
        self.viewer.set_split_preview(
            points if (self.split_panel.isVisible()
                       and self.split_preview_check.isChecked()
                       and valid) else None)

    def _commit_polygon_split(self):
        if not self.split_apply_button.isEnabled():
            return
        model = self.viewer._model
        offset = self._split_polygon_offset
        mode = self.split_mode_combo.currentData()
        a, b = ((self.split_edge_a.currentData(),
                 self.split_edge_b.currentData()) if mode == "edges" else
                (self.split_vertex_a.currentData(),
                 self.split_vertex_b.currentData()))
        try:
            candidate = split_n3_polygon(
                model, self.source_pane.get_source(), offset, mode=mode,
                index_a=a, index_b=b,
                fraction_a=self.split_fraction_a.value(),
                fraction_b=self.split_fraction_b.value())
        except (ValueError, OverflowError, KeyError) as exc:
            QMessageBox.warning(self, "Cannot split polygon", str(exc))
            return
        action = ("two new edge vertices" if mode == "edges"
                  else "an existing-vertex diagonal")
        details = (
            f"Split POLY @{offset} using {action}?\n\n"
            "The parent will refer to a LIST of two polygons. "
            f"New vertices: {candidate.new_vertices}. "
            f"Updated adjacent polygons: {candidate.updated_neighbors}.\n\n"
            "Original .3D declarations and comments outside the affected "
            "POLYs remain intact. Undo in the Source editor reverses the cut; "
            "Save .3D Source or Export compiled 3DO to persist it.")
        if candidate.warnings:
            details += ("\n\nWarnings:\n" +
                        "\n".join(candidate.warnings[:4]))
        reply = QMessageBox.question(
            self, "Split selected polygon", details,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.source_pane.apply_source_replacement(
                candidate.source, f"Split POLY @{offset} ({mode})")
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot apply polygon split", str(exc))
            return
        self._pending_split_label = candidate.first_polygon_label
        self.viewer.set_split_preview()
        self.split_apply_button.setEnabled(False)
        self.source_pane.apply_now()
        self.statusBar().showMessage(
            f"Splitting POLY @{offset}; validating N3 and rebuilding GPU preview…")

    def _toggle_source(self, checked):
        self.source_pane.setVisible(checked)
        if checked:
            self.editor_splitter.setSizes([780, 480])
            self._ensure_source_loaded()
            self._source_target_changed(self.source_pane.current_target())
        else:
            self.viewer.set_source_inspection()
            self.source_pane.set_polygon_visibility(None)

    def _viewport_vertex_picked(self, offset):
        """Reveal and jump to the picked root-model vertex declaration."""
        model = self.viewer._model
        if model is None or offset not in model.vertices:
            return
        if self.source_pane.ready and (
                self.source_pane.pending or self._source_invalid):
            self.statusBar().showMessage(
                "Apply or fix the edited .3D Source before selecting vertices.")
            return
        self._pending_polygon_pick = None
        self._pending_vertex_pick = (model, offset)
        if not self.source_toggle.isChecked():
            self.source_toggle.setChecked(True)
        if self.source_pane.ready:
            self._finish_pending_vertex_pick()
        else:
            self._ensure_source_loaded()

    def _finish_pending_vertex_pick(self):
        pending = self._pending_vertex_pick
        if pending is None or not self.source_pane.ready:
            return
        self._pending_vertex_pick = None
        model, offset = pending
        if model is not self.viewer._model:
            return
        if self.source_pane.goto_model_vertex(model, offset):
            self.statusBar().showMessage(
                f"Selected vertex @{offset} in .3D Source")
        else:
            self.statusBar().showMessage(
                f"Vertex @{offset} has no matching declaration in .3D Source")

    def _viewport_polygon_picked(self, offset):
        """Reveal the clicked POLY in the source editor or filtered row list."""
        model = self.viewer._model
        if model is None or offset not in model.polygons:
            return
        if self.source_pane.ready and (
                self.source_pane.pending or self._source_invalid):
            self.statusBar().showMessage(
                "Apply or fix the edited .3D Source before selecting polygons.")
            return
        self._pending_vertex_pick = None
        self._set_split_target(offset)
        self._pending_polygon_pick = (model, offset)
        if not self.source_toggle.isChecked():
            self.source_toggle.setChecked(True)
        if self.source_pane.ready:
            self._finish_pending_polygon_pick()
        else:
            self._ensure_source_loaded()

    def _finish_pending_polygon_pick(self):
        pending = self._pending_polygon_pick
        if pending is None or not self.source_pane.ready:
            return
        self._pending_polygon_pick = None
        model, offset = pending
        if model is not self.viewer._model:
            return
        if self.source_pane.goto_model_polygon(model, offset):
            self.statusBar().showMessage(
                f"Selected POLY @{offset} in .3D Source")
        else:
            self.statusBar().showMessage(
                f"POLY @{offset} has no matching declaration in .3D Source")

    def _source_target_changed(self, target):
        if (not self.source_toggle.isChecked() or
                self.source_pane.pending or self._source_invalid or
                target is None):
            self.viewer.set_source_inspection()
            self.source_pane.set_polygon_visibility(None)
            return
        kind, label = target
        if kind == "bsp":
            points = self.source_pane.current_bsp_points(self.viewer._model)
            self.viewer.set_source_inspection("bsp", plane_points=points)
            self.source_pane.set_polygon_visibility(None)
            return
        offset = target_offset(self.viewer._model, kind, label)
        self.viewer.set_source_inspection(kind, offset)
        self._refresh_source_polygon_visibility()
        if kind == 'polygon' and self.split_panel.isVisible():
            self._set_split_target(offset)

    def _refresh_source_polygon_visibility(self):
        target = self.source_pane.current_target()
        if (not self.source_toggle.isChecked() or
                self._source_invalid or target is None or
                target[0] != "polygon" or
                self.viewer._model is None or
                (self.viewer._visibility_dirty and
                 (self.viewer.render_mode != "all" or
                  self.viewer._track_lod_active()))):
            self.source_pane.set_polygon_visibility(None)
            return
        offset = target_offset(self.viewer._model, "polygon", target[1])
        span = polygon_mesh_range(self.viewer._scene,
                                  self.viewer._mesh, offset)
        if span is None or not span[1]:
            self.source_pane.set_polygon_visibility(False)
        else:
            self.source_pane.set_polygon_visibility(
                (self.viewer.render_mode == "all" and
                 not self.viewer._track_lod_active()) or
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
        self._finish_pending_vertex_pick()
        self._finish_pending_polygon_pick()
        self._split_controls_changed()

    def _source_export_failed(self, candidate, error):
        if candidate is self.viewer._model:
            self.source_pane.status.setText(
                f'Cannot generate editable source: {error}')
            self._source_invalid = True

    def _source_requested(self, revision, source):
        # Keep only the latest revision while the previous worker runs.
        self._source_queued = (revision, source)
        self._split_controls_changed()
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
            if self._pending_split_label is not None:
                target = model.n3_label_offsets.get(self._pending_split_label)
                self._pending_split_label = None
                self._set_split_target(target)
                if target is not None:
                    self.source_pane.goto_model_polygon(model, target)
            self._split_controls_changed()
        if self._source_queued is not None:
            QTimer.singleShot(40, self._pump_source)

    def _source_compile_failed(self, rev, error):
        self._source_busy_revision = None
        if rev == self.source_pane.revision:
            self._source_invalid = True
            self.source_pane.mark_error(rev, error)
            self._pending_split_label = None
            self._split_controls_changed()
        if self._source_queued is not None:
            QTimer.singleShot(40, self._pump_source)

    def _save_source(self, *, save_as=False):
        """Save editable N3 text; Save As always chooses a destination.

        The first regular Save also asks for a path so the original input
        file is never overwritten without an explicit user decision.
        """
        if not self.source_pane.ready:
            return False
        target = None if save_as else self._source_save_target
        if target is None:
            suggested = self._source_save_target
            if suggested is None:
                suggested = self.source_pane.source_path.with_name(
                    self.source_pane.source_path.stem + '_edited.3d')
            path, _ = QFileDialog.getSaveFileName(
                self, 'Save editable N3 source', str(suggested),
                'Papyrus N3 (*.3d);;All files (*)')
            if not path:
                return False
            target = Path(path)
        if target.suffix.lower() != '.3d':
            QMessageBox.warning(self, 'Invalid source extension',
                                'Save N3 source with a .3D extension.')
            return False
        if target.resolve() == self.source_pane.source_path.resolve():
            if not confirm_destructive_action(
                    self, 'Overwrite original .3D source?',
                    f'Saving here will overwrite the original source file '
                    f'"{target.name}". Existing file contents will be lost.',
                    'Overwrite original'):
                return False
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
            return False
        self._source_save_target = target
        self.source_pane.mark_saved()
        self._update_window_title()
        self.source_pane.status.setText(
            f'Saved {target.name}.' +
            (' Source is not currently valid; GPU preview still shows last valid model.'
             if self._source_invalid or self.source_pane.pending else ''))
        return True

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
        """Re-read main and skybox MIPs while preserving camera and edits."""
        if self._busy() or self.model_path is None:
            return
        scene = self.viewer._scene
        if scene is None or self.viewer._mesh is None:
            return
        if scene.skybox is not None:
            # The sky has an independent atlas; the normal texture worker
            # only covers the main scene. Rebuild both atlas buffers here.
            self.statusBar().showMessage("Reloading track and HORIZ sky MIPs…")
            self.load(self.model_path, reuse_model=True)
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
        # MIP reload may repair or introduce errors. Refresh the menu log
        # without interrupting interactive texture iteration with popups.
        self._update_load_error_log(
            self.model_path or stats.get("file", "(no model)"),
            collect_load_issues(self._info))
        if stats['missing_textures'] or stats['texture_errors']:
            self.statusBar().showMessage(
                "MIP issues: " + "; ".join(
                    list(stats['missing_textures'][:5]) +
                    list(stats['texture_errors'][:3])))

    def _mip_reload_failed(self, message):
        self.statusBar().showMessage("MIP reload failed; previous livery retained")
        QMessageBox.warning(self, "MIP reload failed", message)

    def _skybox_toggled(self, checked):
        self.viewer.sky_enabled = bool(checked)
        self.viewer.update()

    def _track_window_changed(self, *_):
        self.viewer.track_window_counts = tuple(
            spin.value() for spin in self.track_window_spins)
        if self.viewer.track_detail == 'window':
            hi, med, lo = self.viewer.track_window_counts
            self.track_detail_status.setText(
                f"Camera window: current section HI, {hi} HI / {med} MED / "
                f"{lo} LO sections in each direction; all others omitted")
            self.viewer.invalidate_visibility()

    def _track_detail_changed(self, *args):
        self.viewer.track_detail = self.track_detail_combo.currentData()
        self.viewer.invalidate_visibility()
        self._refresh_source_polygon_visibility()
        self._update_polygon_status()

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
            f"Max {maximum:,}" if maximum else "No RES")
        self.lod_max_label.setToolTip(
            f"Range: 0 to {maximum:,} raw model units (highest RES threshold)"
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
        elif (self.viewer.render_mode == 'all' and
              not self.viewer._track_lod_active()):
            self.polygon_status.setText(f"@{offset}: all-polygon mode (BSP ignored)")
        elif (self.viewer.render_mode == 'wire' and
              self.viewer.lod_distance is None and
              not self.viewer._track_lod_active()):
            self.polygon_status.setText(
                f"@{offset}: wireframe (all RES branches; BSP ignored)")
        elif self.viewer._visibility_dirty:
            self.polygon_status.setText(f"@{offset}: recalculating BSP selection")
        elif offset not in self.viewer._visible_set:
            self.polygon_status.setText(
                f"@{offset}: EXCLUDED by BSP or selected LOD"
                if self.viewer.render_mode != 'wire' else
                f"@{offset}: EXCLUDED by SWITCH DISTANCE or track detail")
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
        self._sync_projection_controls()
        self.statusBar().showMessage(
            "Fixed Camera | raw XYZ "
            + str(tuple(spin.value() for spin in self.fixed_camera_coords))
            + " | Drag to look | Wheel adjusts FOV | Pan disabled | "
              "Frame All exits preview"
            if enabled else
            "Exterior camera restored | Left-drag orbit | Shift-left/middle pan")

    def _projection_changed(self, *_):
        if self.projection_combo.isEnabled():
            self.perspective_toggle.setChecked(
                bool(self.projection_combo.currentData()))

    def _sync_projection_controls(self):
        """Keep menu, legacy checkbox and viewport selector in lockstep."""
        enabled = not (self.viewer.fixed_camera_mode or
                       self.viewer.track_drive_enabled)
        self.perspective_toggle.blockSignals(True)
        self.perspective_toggle.setChecked(self.viewer.perspective)
        self.perspective_toggle.setEnabled(enabled)
        self.perspective_toggle.blockSignals(False)
        self.projection_combo.blockSignals(True)
        self.projection_combo.setCurrentIndex(
            self.projection_combo.findData(bool(self.viewer.perspective)))
        self.projection_combo.setEnabled(enabled)
        self.projection_combo.blockSignals(False)
        if hasattr(self, "perspective_menu_action"):
            self.perspective_menu_action.setChecked(self.viewer.perspective)

    def _set_perspective(self, checked):
        if (self.viewer.fixed_camera_mode or self.viewer.track_drive_enabled):
            self._sync_projection_controls()
            return
        self.viewer.perspective = bool(checked)
        self._sync_projection_controls()
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
            if not confirm_destructive_action(
                    self, 'Unsaved .3D source changes',
                    f'Opening "{next_path.name}" will discard unsaved .3D '
                    'source edits. Save the source first if you want '
                    'to keep these changes.',
                    'Discard changes'):
                return
        if not reuse_model:
            self._source_invalid = False
            self._source_applied = False
            self._last_valid_source_text = None
            self._source_save_target = None
            self._source_queued = None
            self._pending_vertex_pick = None
            self._pending_polygon_pick = None
            self._pending_split_label = None
            self._set_split_target(None)
            self.split_button.setChecked(False)
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
                                 if reuse_model and self._source_applied else None),
            auto_local_palette=not reuse_model)
        self.worker.ready.connect(self._loaded)
        self.worker.failed.connect(self._load_failed)
        self.worker.start()

    def _loaded(self, mesh, stats, model, atlas, palette, scene,
                *, from_source=False):
        self._info = stats
        # Commit the auto-selected palette only after the whole model has
        # loaded successfully. Failed loads leave the prior palette intact.
        self.palette_path = Path(stats.get("palette_path", self.palette_path))
        was_reloading = self._preserve_view
        self.viewer.set_mesh(mesh, model, atlas, palette, scene,
                             preserve_view=was_reloading)
        # Indexed tracks default to BSP-selected polygons with GPU depth;
        # car/object modes keep their original painter default. Preserve an
        # explicitly chosen method across recompiles and asset reloads.
        if not was_reloading and not from_source:
            requested = 'depth' if scene.track_section_lods else 'painter'
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(requested))
        self.viewer.set_track_navigation(
            scene.track_navigation, preserve=was_reloading or from_source)
        if not was_reloading and not from_source:
            # Every newly opened asset uses perspective, independent of the
            # previous file's selected projection.
            if not self.viewer.perspective:
                self.viewer.perspective = True
                self.viewer.invalidate_visibility()
        self._sync_projection_controls()
        if not from_source and self.model_path is not None:
            self._loaded_file_path = self.model_path
        self._update_window_title()
        nav = self.viewer.track_navigation
        self.track_drive_checkbox.setEnabled(nav is not None)
        self.trk_reset_button.setEnabled(nav is not None)
        self.track_drive_checkbox.blockSignals(True)
        self.track_drive_checkbox.setChecked(self.viewer.track_drive_enabled)
        self.track_drive_checkbox.blockSignals(False)
        if nav is not None:
            self._update_trk_status()
        elif scene.track_navigation_error:
            self.trk_drive_status.setText(
                f"TRK could not be loaded: {scene.track_navigation_error}")
        else:
            self.trk_drive_status.setText(
                f"No {self.model_path.stem}.trk found beside this model"
                if scene.track_section_lods else
                "TRK navigation is available for recognized tracks only")
        self._configure_switch_distance(scene)
        self._preserve_view = False
        self._sync_source_distance_filter()
        self._source_target_changed(self.source_pane.current_target())
        self._split_controls_changed()
        # Keep manual mode selection for ambiguous files and all background
        # rebuilds. Only clearly recognized newly opened files select a tab.
        if not was_reloading and not from_source:
            suggested = suggest_workspace(self.model_path, stats)
            if suggested is not None:
                self.workspace_tabs.setCurrentIndex(WORKSPACE_MODES.index(suggested))
        palette_note = (" · model folder"
                        if stats.get("palette_auto") else "")
        self.palette_status.setText(
            f"Palette: {self.palette_path.name} (256 colors){palette_note}")
        self._show_mip_stats(stats)
        self.sprite_status.setText(
            f"PMP sprites: {stats['pmp_placements']} placements / "
            f"{stats['pmp_images']} images loaded | "
            f"{len(stats['pmp_warnings'])} missing or invalid"
            + (": " + "; ".join(stats['pmp_warnings'][:3])
               if stats['pmp_warnings'] else ""))
        self.car_status.setText(
            f"Individual-car RECOLOR: {stats['recolor_pairs']} mappings"
            f" | referenced carshape(s): {len(model.external_names)}"
            f" | active texture overrides: {len(self.mip_overrides) + int(self.body_mip is not None)}")
        self.track_status.setText(workspace_scene_summary("track", stats))
        skybox = scene.skybox
        # Reopening a different asset defaults the detected skybox to ON;
        # recompile and texture/asset reloads retain the user's choice.
        if not was_reloading and not from_source:
            self.show_skybox.blockSignals(True)
            self.show_skybox.setChecked(skybox is not None)
            self.show_skybox.blockSignals(False)
        self.show_skybox.setEnabled(skybox is not None)
        self.viewer.sky_enabled = self.show_skybox.isChecked() and skybox is not None
        if skybox is not None:
            self.skybox_status.setText(
                f"{skybox.path.name}: {len(skybox.atlas.loaded_names)} sky MIPs loaded"
                f" | {len(skybox.atlas.missing_names)} missing"
                + (" (" + ", ".join(skybox.atlas.missing_names[:4]) + ")"
                   if skybox.atlas.missing_names else ""))
        elif scene.skybox_error:
            self.skybox_status.setText(f"Skybox could not be loaded: {scene.skybox_error}")
        else:
            self.skybox_status.setText(
                "No horiz.3do found beside track or in external objects folder"
                if scene.track_section_lods else
                "Skybox only available for recognized indexed tracks")
        section_count = stats.get('track_section_lists', 0)
        metadata_count = len(scene.track_section_dlongs or {})
        can_window = (section_count > 0 and metadata_count == section_count
                      and self.viewer.track_navigation is not None)
        self.track_detail_combo.model().item(
            self.track_detail_combo.findData('window')).setEnabled(can_window)
        self.track_detail_combo.setEnabled(bool(section_count))
        for spin in self.track_window_spins:
            spin.setEnabled(can_window)
        # New matching track defaults to adaptive DLONG selection; retaining
        # another mode on source compile/reload is intentional.
        current_detail = self.track_detail_combo.currentData()
        if not was_reloading and not from_source:
            current_detail = 'window' if can_window else 'hi'
        elif current_detail == 'window' and not can_window:
            current_detail = 'hi'
        self.track_detail_combo.setCurrentIndex(
            self.track_detail_combo.findData(current_detail))
        self.viewer.track_detail = current_detail
        self.viewer.invalidate_visibility()
        if section_count:
            self.track_detail_status.setText(
                f"{section_count} indexed sections | DLONG DATA recovered: "
                f"{metadata_count}/{section_count} | "
                + (f"Camera window enabled ({self.viewer.track_window_counts[0]} HI / "
                   f"{self.viewer.track_window_counts[1]} MED / "
                   f"{self.viewer.track_window_counts[2]} LO each way). "
                   "Current section is HI; everything outside is omitted."
                   if can_window else
                   "Camera-local LOD requires matching TRK and valid DATA; "
                   "global HI/MED/LO remains available."))
        else:
            self.track_detail_status.setText(
                "No Papyrus track section index detected")
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
            f"buffer {mesh.size_bytes / 1048576:.1f} MiB | "
            f"PMP {stats['pmp_images']} images")
        issues = collect_load_issues(stats)
        self._update_load_error_log(
            self.model_path or stats['file'], issues,
            auto_show=not from_source and not was_reloading)
        problem_count = len(issues)
        self.statusBar().showMessage(
            f"{Path(stats['file']).name} | {mesh.polygon_count:,} polygons | "
            + ((f"{stats['palette_warning']} — View > Load Error Log")
               if stats.get("palette_warning") else
               (f"{problem_count} load issues — View > Load Error Log")
               if problem_count else "Ready"))
        if not from_source and not was_reloading and self.model_path is not None:
            remember_recent_model(self, self.model_path)
        update_model_actions(self)
        if not from_source and self.source_toggle.isChecked():
            self._ensure_source_loaded()
        if self.viewer.track_drive_enabled and not was_reloading and not from_source:
            self.viewer.setFocus(Qt.FocusReason.OtherFocusReason)

    def _load_failed(self, message):
        self.load_label.setText("Load failed; previous model preserved")
        self.stats_label.setText(message)
        self._update_load_error_log(
            self.model_path or "(no model)",
            (LoadIssue("Model load", message),), auto_show=True)
        self.statusBar().showMessage(
            "Model load failed — View > Load Error Log")

    def closeEvent(self, event):
        if self.source_pane.dirty:
            if not confirm_destructive_action(
                    self, 'Unsaved .3D source changes',
                    'Closing the viewer will discard unsaved .3D source edits. '
                    'Save the source first if you want to keep these changes.',
                    'Discard changes'):
                event.ignore()
                return
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
