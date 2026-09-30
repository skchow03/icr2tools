import pytest

from tso_generator import tso_generator


QtWidgets = pytest.importorskip("PyQt5.QtWidgets")


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_generator_window_has_live_3d_preview(monkeypatch, qapp):
    windows = []

    def capture_window(_app):
        windows.extend(
            widget
            for widget in QtWidgets.QApplication.topLevelWidgets()
            if widget.windowTitle() == "ICR2 Building Generator"
        )
        return 0

    monkeypatch.setattr(QtWidgets.QApplication, "exec_", capture_window)

    tso_generator.build_window()

    assert windows
    window = windows[-1]
    try:
        assert isinstance(window.preview, QtWidgets.QOpenGLWidget)
        assert window.preview.toolTip() == "Drag to rotate; use the mouse wheel to zoom"
        assert window.preview._verts
        original_vertex_count = len(window.preview._verts)

        window.shape_combo.setCurrentText("circular")
        window.sides_spin.setValue(7)
        window.refresh_preview()

        assert len(window.preview._verts) != original_vertex_count
        assert window.reset_preview_btn.text() == "Reset View"
    finally:
        window.close()


def test_project_generator_uses_project_palette_without_palette_controls(
    monkeypatch, qapp, tmp_path
):
    monkeypatch.setattr(
        tso_generator, "INI_PATH", tmp_path / "missing-tso-generator.ini"
    )
    palette = bytes(value % 256 for value in range(768))
    palette_path = tmp_path / "SUNNY.PCX"
    palette_path.write_bytes(b"pcx data" + bytes([0x0C]) + palette)

    window = tso_generator.build_window(
        project_templates={},
        project_palette_path=palette_path,
        run_event_loop=False,
    )
    try:
        assert window.palette[0] == (0, 1, 2)
        assert window.palette[255] == (253, 254, 255)
        assert not hasattr(window, "sunny_edit")
        assert not hasattr(window, "sunny_browse")
        assert all(
            "sunny.pcx" not in action.text().lower()
            for action in window.findChildren(QtWidgets.QAction)
        )
        assert "sunny_pcx" not in window.collect_current_values()
    finally:
        window.close()


def test_project_object_name_defaults_combined_generation_filename(
    monkeypatch, qapp, tmp_path
):
    saved_objects = []
    added_objects = []
    suggested_paths = []

    monkeypatch.setattr(
        tso_generator, "INI_PATH", tmp_path / "missing-tso-generator.ini"
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("scoring_tower", True),
    )

    def choose_output(_parent, _title, suggested_path, _file_filter):
        suggested_paths.append(suggested_path)
        return str(tmp_path / "scoring_tower.3D"), "3D files (*.3D)"

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", choose_output)

    window = tso_generator.build_window(
        project_templates={},
        on_templates_changed=lambda objects: saved_objects.append(objects),
        on_add_object=lambda path, parameters: added_objects.append(
            (path, parameters)
        ),
        default_save_dir=tmp_path,
        run_event_loop=False,
    )
    try:
        assert window.save_template_btn.text() == "Save to Project"
        assert window.generate_btn.text() == (
            "Generate .3D and Add to SG CREATE Object List"
        )
        assert not hasattr(window, "add_to_project_btn")
        assert any(
            label.text() == "Project Objects"
            for label in window.findChildren(QtWidgets.QLabel)
        )

        window.save_template_clicked()
        assert window.template_list.currentItem().text() == "scoring_tower"
        window.generate_clicked()

        assert suggested_paths == [str(tmp_path / "scoring_tower.3D")]
        assert added_objects[0][0] == tmp_path / "scoring_tower.3D"
        assert "scoring_tower" in saved_objects[-1]
        assert (tmp_path / "scoring_tower.3D").is_file()
    finally:
        window.close()


def test_generator_uses_selected_display_uom_and_can_save_another_uom(
    monkeypatch, qapp, tmp_path
):
    output_path = tmp_path / "metric-input-inches-output.3D"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args: (str(output_path), "3D files (*.3D)"),
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args: None)
    window = tso_generator.build_window(
        project_templates={}, measurement_unit="meter", run_event_loop=False
    )
    try:
        assert window.width_spin.suffix() == " m"
        window.width_spin.setValue(1.0)
        window.depth_spin.setValue(2.0)
        window.output_uom_combo.setCurrentIndex(
            window.output_uom_combo.findData("inch")
        )
        window.generate_clicked()

        text = output_path.read_text(encoding="utf-8")
        assert "% coordinate_uom: inch" in text
        assert "c0: [<39.370079, 0, 0>];" in text
        assert "d0: [<39.370079, 78.740157, 0>];" in text
    finally:
        window.close()
