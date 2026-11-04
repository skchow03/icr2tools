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
import numpy as np
import faulthandler
faulthandler.enable()
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QSurfaceFormat, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gpu_viewer.main import Window, ortho_projection, perspective_projection
from gpu_viewer.source_inspection import (
    index_source_targets, target_offset, polygon_mesh_range,
    vertex_screen_position,
)


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


def _make_car_wrapper(path):
    """Actual MATERIAL child=0 RECOLOR wrapper, like cit74.3do."""
    body = bytearray(struct.pack('<4i', -(1<<31)+14, 1, 44, 155))
    root = len(body)
    body.extend(struct.pack('<4i', -(1<<31)+4, 0, 0, 0))
    names = b'car74'.ljust(8, bytes(1)) + b'roadcar'.ljust(8, bytes(1))
    path.write_bytes(struct.pack('<5i', len(body), root, 1, 0, 1) +
                     names + body)


def _workspace_switch_keeps_document(window):
    """Changing tool panels must not reload or alter the shared GPU/N3 model."""
    tabs = window.workspace_tabs
    if [tabs.tabText(i) for i in range(tabs.count())] != [
            "Car", "Track", "Object"]:
        return False
    original_tab = tabs.currentIndex()
    view = window.viewer
    before = (view._model, view._mesh, view._scene,
              view._vbo, view._vao, view.azimuth, view.elevation,
              window.source_pane.revision, window.source_pane.dirty)
    try:
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            after = (view._model, view._mesh, view._scene,
                     view._vbo, view._vao, view.azimuth, view.elevation,
                     window.source_pane.revision, window.source_pane.dirty)
            if any(a is not b if i < 3 else a != b
                   for i, (a, b) in enumerate(zip(before, after))):
                return False
    finally:
        tabs.setCurrentIndex(original_tab)
    return True


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
        # Open the synthetic individual-car wrapper, NOT the base geometry.
        # This exercises the exact empty-viewport failure from cit74.3do.
        wrapper = local.parent / 'car74.3do'
        _make_car_wrapper(wrapper)
        shutil.copyfile(ROOT / 'fixtures' / 'ind96.mip',
                        local.parent / 'car74.mip')
        path = wrapper
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([sys.argv[0]])
    window = Window(path, benchmark=True)
    # Also exercise the historical global fallback for geometry-only models.
    window.fallback_mip = ROOT / "fixtures" / "ind96.mip"
    # Ensure QOpenGLWidget is deleted while QApplication/GLX remain alive;
    # PySide6 6.12 can bus-error during interpreter-finalization otherwise.
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.resize(900, 680)
    window.show()
    def close_smoke():
        # Smoke edits are intentionally unsaved. Discard the test source only
        # during teardown so the application's real exit guard stays intact.
        window.source_pane.reset()
        window.close()

    started = perf_counter()
    result = {"ok": False, "error": "timed out"}
    reload_state = {"started":False, "completed":False, "vbo":None}
    fixed = {"tested": False}
    inspection = {"tested": False}
    live = {"opened":False, "invalid_sent":False, "invalid_seen":False,
            "valid_sent":False, "valid_seen":False,
            "vbo":None, "azimuth":None, "source":None}
    def reload_completed(*args):
        reload_state["completed"] = True
    def check():
        elapsed = perf_counter() - started
        view = window.viewer
        if (dynamic_test and window._info and view._vao is not None
                and view._frame_count >= 3 and not reload_state["started"]):
            reload_state["started"] = True
            reload_state["vbo"] = view._vbo
            window.reload_mips()
            window.worker.ready.connect(reload_completed)
        if (dynamic_test and reload_state["completed"] and
                not window.worker.isRunning()):
            pane = window.source_pane
            if not live["opened"]:
                live["opened"] = True
                window.source_toggle.setChecked(True)
            elif pane.ready and not live["invalid_sent"]:
                live["source"] = pane.get_source()
                live["vbo"] = view._vbo
                live["azimuth"] = view.azimuth
                # Viewport's F/R shortcuts must not swallow actual text
                # typed into the N3 editor.
                pane.editor.setFocus()
                pane.editor.moveCursor(QTextCursor.MoveOperation.End)
                QTest.keyClicks(pane.editor, "FR")
                if not pane.get_source().endswith("FR"):
                    result["error"] = "F/R viewport shortcuts intercepted N3 editor input"
                    timer.stop()
                    close_smoke()
                    app.quit()
                    return
                pane.editor.setPlainText(live["source"] + "\nBROKEN: FACE INVALID;\n")
                pane.apply_now()
                live["invalid_sent"] = True
            elif (live["invalid_sent"] and not live["valid_sent"] and
                  window._source_invalid and not pane.pending):
                if view._vbo != live["vbo"]:
                    result["error"] = "Invalid source changed the GPU vertex buffer"
                    timer.stop()
                    close_smoke()
                    app.quit()
                    return
                live["invalid_seen"] = True
                pane.editor.setPlainText(live["source"] + "\n% Live N3 source preview smoke\n")
                pane.apply_now()
                live["valid_sent"] = True
            elif (live["valid_sent"] and window._source_applied and
                  not window._source_invalid and not pane.pending and
                  window.worker is not None and not window.worker.isRunning()):
                live["valid_seen"] = True
        if dynamic_test and live["valid_seen"] and not fixed["tested"]:
            # Exercise the actual user controls, not just the helper math.
            # Both BSP/RES and OpenGL must use editable raw Papyrus XYZ.
            prior = (view.target.copy(), view.distance, view.half_height,
                     view.azimuth, view.elevation, view.perspective, view._vbo)
            # Fixed Camera controls are in the on-demand Advanced dialog.
            # Open the dialog before asserting coordinate-control visibility.
            window.open_settings_dialog("advanced")
            window.fixed_camera_button.setChecked(True)
            if not (window.fixed_camera_button.text() == 'Fixed Camera' and
                    view.fixed_camera_mode and view.perspective and
                    window.fixed_camera_controls.isVisible() and
                    [spin.value() for spin in window.fixed_camera_coords] ==
                    [0, 0, 5000] and
                    window.perspective_toggle.isChecked() and
                    not window.perspective_toggle.isEnabled()):
                result["error"] = "Fixed Camera did not enter default (0,0,5000) mode"
            else:
                view.azimuth += .7
                view.elevation = .3
                for expected in ((0, 0, 5000), (12500, -8000, 1500),
                                 (0, 0, 10000)):
                    for spin, value in zip(window.fixed_camera_coords, expected):
                        spin.setValue(value)
                    raw_eye = view._camera_eye_model()
                    view_matrix, _, _ = view._camera_view_matrix()
                    eye_gpu = (np.asarray(expected, dtype=np.float64)
                               - np.asarray(view._mesh.center)) / view._mesh.scale
                    in_eye_space = view_matrix @ np.append(eye_gpu, 1.0)
                    if (not np.allclose(raw_eye, expected, atol=1e-7, rtol=0)
                        or not np.allclose(in_eye_space[:3], (0,0,0), atol=1e-9)
                        or view._vbo != prior[6]
                        or not view._visibility_dirty):
                        result["error"] = "Editing XYZ did not update GL/BSP fixed eye"
                        break
            # Toggling off must preserve user-selected coordinates and
            # restore the exact original external orbit camera.
            window.fixed_camera_button.setChecked(False)
            if (view.fixed_camera_mode or
                window.fixed_camera_controls.isVisible() or
                not np.array_equal(view.target, prior[0]) or
                (view.distance, view.half_height, view.azimuth,
                 view.elevation, view.perspective) != prior[1:6] or
                not window.perspective_toggle.isEnabled() or
                [spin.value() for spin in window.fixed_camera_coords] !=
                [0, 0, 10000]):
                result["error"] = "Fixed Camera exit failed to restore exterior view"
            fixed["tested"] = True
            if result["error"] != "timed out":
                timer.stop()
                close_smoke()
                app.quit()
                return
        if (dynamic_test and live["valid_seen"] and fixed["tested"] and
                not inspection["tested"]):
            pane = window.source_pane
            inspected_vbo = view._vbo
            targets = index_source_targets(pane.get_source()).targets
            poly = next((
                item for item in targets
                if item.kind == "polygon" and
                polygon_mesh_range(
                    view._scene, view._mesh,
                    target_offset(view._model, item.kind, item.label))
            ), None)
            if poly is None:
                result["error"] = "Source POLY target cannot be mapped to visible GPU geometry"
            else:
                pane.editor.setTextCursor(QTextCursor(
                    pane.editor.document().findBlockByNumber(poly.first_line)))
                expected = target_offset(view._model, "polygon", poly.label)
                if (view.inspection_kind != "polygon" or
                        view.inspection_offset != expected):
                    result["error"] = "Source POLY cursor did not activate GPU highlight"
                elif view.grabFramebuffer().isNull():
                    result["error"] = "Rendering highlighted POLY produced an empty framebuffer"
                else:
                    view_matrix, _, _ = view._camera_view_matrix()
                    aspect = max(1, view.width()) / max(1, view.height())
                    near = 0.001
                    far = max(100.0, 40.0 * view.distance)
                    if view.perspective:
                        projection = perspective_projection(
                            aspect, near, far,
                            view.fixed_camera_fov if view.fixed_camera_mode else 60.0)
                    else:
                        projection = ortho_projection(view.half_height,
                                                      aspect, near, far)
                    candidates = []
                    for item in targets:
                        if item.kind != "vertex":
                            continue
                        offset = target_offset(view._model, item.kind, item.label)
                        point = vertex_screen_position(
                            view._model, view._mesh, offset,
                            projection @ view_matrix, view.width(), view.height())
                        if point is not None and (
                                10 <= point[0] < view.width() - 10 and
                                10 <= point[1] < view.height() - 10):
                            candidates.append((item, offset, point))
                    if not candidates:
                        result["error"] = "No onscreen source vertex available to test marker"
                    else:
                        item, offset, point = candidates[len(candidates) // 2]
                        pane.editor.setTextCursor(QTextCursor(
                            pane.editor.document().findBlockByNumber(item.first_line)))
                        if (view.inspection_kind != "vertex" or
                                view.inspection_offset != offset):
                            result["error"] = "Source vertex cursor did not activate GPU dot"
                        else:
                            picture = view.grabFramebuffer()
                            pixel = picture.pixelColor(
                                int(round(point[0])), int(round(point[1])))
                            if (picture.isNull() or pixel.red() < 210 or
                                    pixel.green() < 190 or pixel.blue() > 150):
                                result["error"] = "Vertex dot was not visible in framebuffer"
                            elif view._vbo != inspected_vbo:
                                result["error"] = "Moving the source caret rebuilt GPU geometry"
            inspection["tested"] = True
            if result["error"] != "timed out":
                timer.stop()
                close_smoke()
                app.quit()
                return
        if (window._info and view._vao is not None and
                view._frame_count >= 8 and elapsed >= 1.25 and
                (not dynamic_test or
                 (reload_state["completed"] and not window.worker.isRunning()
                  and live["valid_seen"] and fixed["tested"]
                  and inspection["tested"]))):
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
                  (view._scene.appearance is None or
                   view._scene.appearance.geometry_name != 'roadcar' or
                   view._scene.recolor_pairs != 1 or
                   view._model.path.stem.casefold() != 'roadcar' or
                   window.material_combo.itemData(0) != '__car_body__')):
                result["error"] = "Individual-car MATERIAL->RECOLOR wrapper did not load its base car"
            elif (dynamic_test and
                  (view._scene.loaded_instances != 5 or
                   view._mesh.polygon_count <= len(view._model.polygons) or
                   view._visibility_info.get("instances_visited", 0) != 6)):
                result["error"] = "DYNAMIC child geometry/BSP order missing in GPU draw"
            elif (dynamic_test and
                  (reload_state["vbo"] != view._vbo or
                   not reload_state["completed"])):
                result["error"] = "MIP reload unexpectedly rebuilt the GPU vertex buffer"
            elif dynamic_test and (
                    not live["invalid_seen"] or not live["valid_seen"] or
                    abs(view.azimuth - live["azimuth"]) > 1e-9 or
                    not view._scene.appearance):
                result["error"] = "Live source compile did not preserve camera/appearance"
            elif not _workspace_switch_keeps_document(window):
                result["error"] = "Workspace tab switch changed shared model/source/camera"
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
                    close_smoke()
                    app.quit()
                    return
                screenshot = Path(os.environ.get(
                    "GPU_SMOKE_SCREENSHOT", "gpu_viewer_smoke.png"))
                image.save(str(screenshot))
                # Switch to the independent GL_LINES boundary pass, render a
                # real framebuffer, then restore the original filled mode.
                previous_mode = window.mode_combo.currentIndex()
                window.mode_combo.setCurrentIndex(
                    window.mode_combo.findData("wire"))
                outline_image = view.grabFramebuffer()
                wire_ok = (
                    view._wire_vao is not None and
                    view._wire_mesh is not None and
                    view._wire_mesh.segment_count > 0 and
                    not outline_image.isNull() and
                    outline_image != image)
                window.mode_combo.setCurrentIndex(previous_mode)
                if not wire_ok:
                    result["error"] = "Wireframe GL_LINES pass was empty or unchanged"
                    timer.stop()
                    close_smoke()
                    app.quit()
                    return
                result["ok"] = True
                result["error"] = ""
                print(
                    f"GPU smoke passed: {view._mesh.polygon_count} polygons; "
                    f"{view._mesh.triangle_count} triangles; "
                    f"upload {view.upload_ms:.1f} ms; "
                    f"MIP faces {len(view._atlas.polygon_rects)}; "
                    f"external instances {view._scene.loaded_instances}; "
                    f"MIP hot reload {reload_state['completed']}; "
                    f"N3 invalid/valid preview {live['invalid_seen']}/{live['valid_seen']}; "
                    f"fixed camera XYZ {fixed['tested']}; "
                    f"source POLY/vertex inspected {inspection['tested']}; "
                    f"observed {view.fps:.1f} FPS; screenshot {screenshot}",
                    flush=True,
                )
            timer.stop()
            print("Closing Qt window",flush=True)
            close_smoke()
            print("Qt window closed",flush=True)
            app.quit()
        elif elapsed > 45:
            result["error"] = (
                f"timeout loading or drawing: {window.stats_label.text()} | "
                f"source {window.source_pane.status.text()} | live {live} | "
                f"ctx={view._program is not None}, "
                f"buffer={view._vao is not None}, frames={view._frame_count}"
            )
            timer.stop()
            close_smoke()
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
