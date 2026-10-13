import pytest

from tso_generator import tso_generator


QtWidgets = pytest.importorskip("PyQt5.QtWidgets")


@pytest.fixture
def qapp(monkeypatch, tmp_path):
    # Keep machine-specific palette paths and saved objects out of UI tests.
    monkeypatch.setattr(tso_generator, "INI_PATH", tmp_path / "tso_generator.ini")
    monkeypatch.setattr(tso_generator, "TEMPLATE_JSON_PATH", tmp_path / "templates.json")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_grandstand_crowd_controls_save_reload_and_export(monkeypatch, qapp, tmp_path):
    saved_objects = []
    output_path = tmp_path / "grandstand.3D"
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName",
        lambda *args: (str(output_path), "3D files (*.3D)"),
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args: None)
    window = tso_generator.build_window(
        project_templates={}, measurement_unit="feet", run_event_loop=False,
        on_templates_changed=lambda objects: saved_objects.append(objects),
    )
    try:
        assert window.grandstand_crowd_pieces_spin.isHidden()
        window.shape_combo.setCurrentText("grandstand")
        assert not window.grandstand_crowd_pieces_spin.isHidden()
        assert not window.grandstand_crowd_mip_edit.isHidden()
        assert window.grandstand_crowd_mip_edit.text() == "crowd"
        window.grandstand_crowd_pieces_spin.setValue(3)
        window.grandstand_crowd_mip_edit.setText("fans.mip")
        window.grandstand_crowd_ul_u_spin.setValue(10)
        window.grandstand_crowd_ul_v_spin.setValue(20)
        window.grandstand_crowd_lr_u_spin.setValue(200)
        window.grandstand_crowd_lr_v_spin.setValue(80)
        window.refresh_preview()
        assert len([name for name, _vs in window.preview._faces if name.startswith("seatB_")]) == 3
        values = window.collect_current_values()
        window.generate_clicked()
        text = output_path.read_text(encoding="utf-8")
        assert text.count('MATERIAL MIP="fans", GROUP=3, POLY [T]') == 3
        assert "T=<10,80>" in text
        assert "T=<200,20>" in text
        assert "% coordinate_uom: feet" in text
        assert "gs_c3_tf_r: [<100, 0, 3>, T=<200,80>];" in text
        saved = saved_objects[-1]["grandstand"]
        assert saved["grandstand_crowd_pieces"] == "3"
        assert saved["grandstand_crowd_ul_u"] == "10"
        window.apply_values({"building_shape": "grandstand"})
        assert window.grandstand_crowd_pieces_spin.value() == 1
        assert window.grandstand_crowd_mip_edit.text() == ""
        assert window.grandstand_crowd_ul_u_spin.value() == 0
        window.apply_values(saved)
        assert window.collect_current_values() == values
        window._select_template("grandstand")
        window.grandstand_crowd_mip_edit.setText("newfans")
        assert "grandstand" in window._dirty_objects
        window.save_template_clicked()
        assert saved_objects[-1]["grandstand"]["grandstand_crowd_mip"] == "newfans"
        window.shape_combo.setCurrentText("rectangular")
        assert window.grandstand_crowd_pieces_spin.isHidden()
        assert window.grandstand_crowd_mip_edit.isHidden()
        assert window.grandstand_crowd_ul_widget.isHidden()
    finally:
        window.close()


def test_generator_window_has_live_3d_preview(monkeypatch, qapp):
    window = tso_generator.build_window(run_event_loop=False)
    try:
        assert isinstance(window.preview, QtWidgets.QOpenGLWidget)
        assert window.preview.toolTip() == "Drag to rotate; use the mouse wheel to zoom"
        assert window.preview._verts
        original_vertex_count = len(window.preview._verts)

        window.shape_combo.setCurrentText("circular")
        window.sides_spin.setValue(7)
        window.refresh_preview()

        assert len(window.preview._verts) != original_vertex_count
        assert window.front_preview_btn.text() == "Front View"
        assert window.top_preview_btn.text() == "Top View"
        assert window.reset_preview_btn.text() == "Reset View"

        window.front_preview_btn.click()
        assert (window.preview._yaw, window.preview._pitch) == (0.0, 0.0)
        window.top_preview_btn.click()
        assert (window.preview._yaw, window.preview._pitch) == (0.0, 90.0)
    finally:
        window.close()


def test_grandstand_colors_use_palette_preview_save_and_export(monkeypatch, qapp, tmp_path):
    saved_objects = []
    output_path = tmp_path / "grandstand.3D"
    palette_path = tmp_path / "SUNNY.PCX"
    palette = [(i, i, 255 - i) for i in range(256)]
    palette_path.write_bytes(b"pcx data\x0c" + bytes(channel for rgb in palette for channel in rgb))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args: (str(output_path), "3D files (*.3D)"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args: None)
    window = tso_generator.build_window(
        project_templates={}, project_palette_path=palette_path, run_event_loop=False,
        on_templates_changed=lambda objects: saved_objects.append(objects),
    )
    parts = {"front": 11, "sides": 22, "back": 33, "crowd": 44, "bottom": 55}
    try:
        for part in parts:
            picker = getattr(window, f"grandstand_{part}_picker")
            assert picker.isHidden()
            assert picker._palette == palette
        window.shape_combo.setCurrentText("grandstand")
        window.grandstand_crowd_pieces_spin.setValue(3)
        for part, color in parts.items():
            picker = getattr(window, f"grandstand_{part}_picker")
            assert not picker.isHidden()
            picker.set_color_index(color)
        assert window.roof_bright_picker.isHidden()
        window.refresh_preview()
        face_colors = window.preview._face_colors
        for face, index in {"seatFront": 11, "seatLs": 22, "seatRs": 22, "seatBack": 33, "seatD": 55}.items():
            assert face_colors[face] == palette[index]
        assert all(face_colors[f"seatB_{i}"] == palette[44] for i in (1, 2, 3))
        window.generate_clicked()
        text = output_path.read_text()
        assert "seatBack: POLY <33>" in text
        assert text.count('MATERIAL MIP="crowd", GROUP=3, POLY [T] <44>') == 3
        saved = saved_objects[-1]["grandstand"]
        assert all(saved[f"grandstand_{part}_color"] == str(color) for part, color in parts.items())
        legacy = dict(saved)
        for part in parts:
            legacy[f"grandstand_{part}_color"] = ""
        window.apply_values(legacy)
        assert window.grandstand_front_picker.color_index() == 202
        assert window.grandstand_sides_picker.color_index() == 202
        assert window.grandstand_back_picker.color_index() == 200
        assert window.grandstand_crowd_picker.color_index() == 200
        assert window.grandstand_bottom_picker.color_index() == 201
        window.apply_values(saved)
        assert all(window.collect_current_values()[f"grandstand_{part}_color"] == color for part, color in parts.items())
        window._select_template("grandstand")
        window.grandstand_back_picker.set_color_index(66)
        assert "grandstand" in window._dirty_objects
        window.save_template_clicked()
        assert saved_objects[-1]["grandstand"]["grandstand_back_color"] == "66"
        window.shape_combo.setCurrentText("tree")
        assert all(getattr(window, f"grandstand_{part}_picker").isHidden() for part in parts)
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


def test_project_object_name_defaults_object_list_filename(
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
        assert window.save_template_btn.text() == "Save Current to Project"
        assert window.save_all_templates_btn.text() == "Save All to Project"
        assert window.add_template_btn.text() == "Add New Object"
        assert window.rename_template_btn.text() == "Rename Object"
        assert not hasattr(window, "load_template_btn")
        assert window.generate_btn.text() == "Export .3D file"
        assert window.add_to_project_btn.text() == "Add to Object List"
        assert any(
            label.text() == "Project Objects"
            for label in window.findChildren(QtWidgets.QLabel)
        )

        window.add_template_clicked()
        assert window.template_list.currentItem().text() == "scoring_tower"
        window.add_to_project_clicked()

        assert suggested_paths == [str(tmp_path / "scoring_tower.3D")]
        assert added_objects[0][0] == tmp_path / "scoring_tower.3D"
        assert "scoring_tower" in saved_objects[-1]
        assert (tmp_path / "scoring_tower.3D").is_file()
    finally:
        window.close()


def test_generator_uses_sg_create_uom_for_display_and_saving(
    monkeypatch, qapp, tmp_path
):
    output_path = tmp_path / "metric-object.3D"
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
        assert not hasattr(window, "output_uom_combo")
        window.width_spin.setValue(1.0)
        window.depth_spin.setValue(2.0)
        window.generate_clicked()

        text = output_path.read_text(encoding="utf-8")
        assert "% coordinate_uom: meter" in text
        assert "c0: [<1, 0, 0>];" in text
        assert "d0: [<1, 2, 0>];" in text
    finally:
        window.close()


def test_project_export_does_not_add_to_object_list(monkeypatch, qapp, tmp_path):
    output_path = tmp_path / "export-only.3D"
    added_objects = []
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args: (str(output_path), "3D files (*.3D)"),
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args: None)

    window = tso_generator.build_window(
        project_templates={},
        on_add_object=lambda path, parameters: added_objects.append(
            (path, parameters)
        ),
        default_save_dir=tmp_path,
        run_event_loop=False,
    )
    try:
        window.generate_clicked()

        assert output_path.is_file()
        assert added_objects == []
    finally:
        window.close()


@pytest.mark.parametrize("measurement_unit", ["feet", "inch", "meter", "500ths"])
def test_distance_fields_allow_large_values_in_every_display_unit(
    qapp, measurement_unit
):
    window = tso_generator.build_window(
        project_templates={},
        measurement_unit=measurement_unit,
        run_event_loop=False,
    )
    try:
        window.width_spin.setValue(120.0)

        assert window.width_spin.maximum() == tso_generator.DISTANCE_INPUT_MAX
        assert window.width_spin.value() == 120.0
    finally:
        window.close()


def test_project_objects_switch_immediately_and_mark_unsaved_edits(qapp):
    window = tso_generator.build_window(
        project_templates={
            "Garage": {"width": 6000, "depth": 12000},
            "Tower": {"width": 18000, "depth": 18000},
        },
        measurement_unit="feet",
        run_event_loop=False,
    )
    try:
        garage = window.template_list.item(0)
        tower = window.template_list.item(1)
        window.template_list.setCurrentItem(garage)
        assert window.width_spin.value() == pytest.approx(1.0)

        window.width_spin.setValue(7.0)
        assert garage.text() == "Garage *"
        window.template_list.setCurrentItem(tower)
        assert window.width_spin.value() == pytest.approx(3.0)

        window.template_list.setCurrentItem(garage)
        assert window.width_spin.value() == pytest.approx(7.0)
    finally:
        window.close()


def test_save_current_and_save_all_persist_the_expected_objects(qapp):
    saved_objects = []
    window = tso_generator.build_window(
        project_templates={
            "Garage": {"width": 6000, "depth": 12000},
            "Tower": {"width": 18000, "depth": 18000},
        },
        measurement_unit="feet",
        on_templates_changed=lambda objects: saved_objects.append(objects),
        run_event_loop=False,
    )
    try:
        garage = window.template_list.item(0)
        tower = window.template_list.item(1)
        window.template_list.setCurrentItem(garage)
        window.width_spin.setValue(7.0)
        window.template_list.setCurrentItem(tower)
        window.width_spin.setValue(4.0)

        window.save_template_clicked()
        assert float(saved_objects[-1]["Tower"]["width"]) == pytest.approx(24000)
        assert float(saved_objects[-1]["Garage"]["width"]) == pytest.approx(6000)
        assert window.template_list.item(0).text() == "Garage *"

        window.save_all_templates_clicked()
        assert float(saved_objects[-1]["Garage"]["width"]) == pytest.approx(42000)
        assert window._dirty_objects == set()
    finally:
        window.close()


def test_add_and_rename_project_object(monkeypatch, qapp):
    responses = iter([("New Garage", True), ("Renamed Garage", True)])
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: next(responses),
    )
    saved_objects = []
    window = tso_generator.build_window(
        project_templates={},
        on_templates_changed=lambda objects: saved_objects.append(objects),
        run_event_loop=False,
    )
    try:
        window.shape_combo.setCurrentText("tree")
        window.add_template_clicked()

        assert window.template_list.currentItem().text() == "New Garage"
        assert window.shape_combo.currentText() == "rectangular"
        assert window.roof_combo.currentText() == "flat"
        assert saved_objects[-1]["New Garage"]["building_shape"] == "rectangular"
        assert saved_objects[-1]["New Garage"]["roof_type"] == "flat"

        window.rename_template_clicked()
        assert window.template_list.currentItem().text() == "Renamed Garage"
        assert "New Garage" not in saved_objects[-1]
        assert "Renamed Garage" in saved_objects[-1]
    finally:
        window.close()


def test_new_object_defaults_have_consistent_real_world_sizes(qapp):
    metric = tso_generator.build_window(
        project_templates={}, measurement_unit="meter", run_event_loop=False
    )
    feet = tso_generator.build_window(
        project_templates={}, measurement_unit="feet", run_event_loop=False
    )
    try:
        assert feet.width_spin.value() == pytest.approx(40.0)
        assert metric.width_spin.value() == pytest.approx(12.192)
        assert feet.bridge_clearance_spin.value() == pytest.approx(16.0)
        assert metric.bridge_clearance_spin.value() == pytest.approx(4.877, abs=0.001)
    finally:
        metric.close()
        feet.close()
