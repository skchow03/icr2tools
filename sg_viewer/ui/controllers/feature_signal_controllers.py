from __future__ import annotations


class MrkController:
    def __init__(self, host: object) -> None:
        self._host = host

    def connect_signals(self) -> None:
        h = self._host
        w = h._window
        w.mrk_add_entry_button.clicked.connect(h._on_mrk_add_entry_requested)
        w.mrk_delete_entry_button.clicked.connect(h._on_mrk_delete_entry_requested)
        w.mrk_move_up_button.clicked.connect(h._on_mrk_move_up_requested)
        w.mrk_move_down_button.clicked.connect(h._on_mrk_move_down_requested)
        w.mrk_textures_button.clicked.connect(h._on_mrk_textures_requested)
        w.mrk_generate_file_button.clicked.connect(h._on_mrk_generate_file_requested)
        w.mrk_save_button.clicked.connect(h._on_mrk_save_requested)
        w.mrk_load_button.clicked.connect(h._on_mrk_load_requested)
        w.mrk_texture_pattern_show_colors_checkbox.toggled.connect(h._on_mrk_texture_pattern_display_mode_changed)
        w.generate_pitwall_button.clicked.connect(h._generate_pitwall_txt)
        w.manual_wall_height_overrides_button.clicked.connect(h._on_manual_wall_height_overrides_requested)
        w.pitwall_wall_height_spin.valueChanged.connect(h._on_mrk_wall_height_changed)
        w.pitwall_armco_height_spin.valueChanged.connect(h._on_mrk_armco_height_changed)
        w.pitwall_length_multiplier_spin.valueChanged.connect(h._on_mrk_length_multiplier_changed)
        w.preview.set_mrk_length_multiplier(w.pitwall_length_multiplier())
        h._mrk_add_entry_action.triggered.connect(h._on_mrk_add_entry_requested)
        h._mrk_delete_entry_action.triggered.connect(h._on_mrk_delete_entry_requested)
        h._mrk_move_up_action.triggered.connect(h._on_mrk_move_up_requested)
        h._mrk_move_down_action.triggered.connect(h._on_mrk_move_down_requested)
        h._mrk_textures_action.triggered.connect(h._on_mrk_textures_requested)
        h._mrk_generate_file_action.triggered.connect(h._on_mrk_generate_file_requested)
        h._mrk_save_entries_action.triggered.connect(h._on_mrk_save_requested)
        h._mrk_load_entries_action.triggered.connect(h._on_mrk_load_requested)
        w.mrk_entries_table.itemSelectionChanged.connect(h._on_mrk_entry_selection_changed)
        w.mrk_entries_table.itemChanged.connect(h._on_mrk_entry_item_changed)
        w.mrk_entries_table.cellDoubleClicked.connect(h._on_mrk_entry_cell_double_clicked)


class TsdSignalController:
    def __init__(self, host: object) -> None:
        self._host = host

    def connect_signals(self) -> None:
        h = self._host
        c = h._tsd_controller
        w = h._window
        h._tsd_preview_refresh_timer.timeout.connect(c._refresh_tsd_preview_lines)
        w.tsd_add_line_button.clicked.connect(c._on_tsd_add_line_requested)
        w.tsd_delete_line_button.clicked.connect(c._on_tsd_delete_line_requested)
        w.tsd_move_line_up_button.clicked.connect(c._on_tsd_move_line_up_requested)
        w.tsd_move_line_down_button.clicked.connect(c._on_tsd_move_line_down_requested)
        w.tsd_save_file_button.clicked.connect(c._on_tsd_save_file_requested)
        w.tsd_generate_file_button.clicked.connect(c._on_tsd_generate_file_requested)
        w.tsd_load_file_button.clicked.connect(c._on_tsd_load_file_requested)
        w.tsd_remove_file_button.clicked.connect(c._on_tsd_remove_file_requested)
        w.tsd_files_combo.currentIndexChanged.connect(c._on_tsd_file_selection_changed)
        w.tsd_add_object_button.clicked.connect(c._on_tsd_add_object_requested)
        w.tsd_duplicate_object_button.clicked.connect(c._on_tsd_duplicate_object_requested)
        w.tsd_remove_selected_object_button.clicked.connect(c._on_tsd_remove_selected_object_requested)
        w.tsd_move_object_up_button.clicked.connect(c._on_tsd_move_object_up_requested)
        w.tsd_move_object_down_button.clicked.connect(c._on_tsd_move_object_down_requested)
        w.tsd_export_objects_button.clicked.connect(c._on_tsd_export_objects_requested)
        w.tsd_skid_marks_button.clicked.connect(c._on_tsd_skid_marks_requested)
        w.tsd_hide_centerline_nodes_checkbox.toggled.connect(h._on_tsd_hide_centerline_nodes_toggled)
        w.tsd_objects_table.itemSelectionChanged.connect(c._on_tsd_object_selection_changed)
        w.tsd_objects_table.cellClicked.connect(c._on_tsd_objects_table_cell_clicked)
        h._tsd_lines_model.dataChanged.connect(c._on_tsd_data_changed)
        h._tsd_lines_model.rowsInserted.connect(c._schedule_tsd_preview_refresh)
        h._tsd_lines_model.rowsRemoved.connect(c._schedule_tsd_preview_refresh)
        h._tsd_lines_model.modelReset.connect(c._schedule_tsd_preview_refresh)
        tsd_selection_model = w.tsd_lines_table.selectionModel()
        if tsd_selection_model is not None:
            tsd_selection_model.selectionChanged.connect(c._on_tsd_selection_changed)


class TracksideObjectsController:
    def __init__(self, host: object) -> None:
        self._host = host

    def connect_signals(self) -> None:
        h = self._host
        w = h._window
        h._tso_persist_timer.timeout.connect(h._persist_trackside_objects_for_current_track)
        w.tso_add_button.clicked.connect(h._on_tso_add_requested)
        w.tso_stamp_button.clicked.connect(h._on_tso_stamp_requested)
        w.tso_box_select_button.clicked.connect(h._on_tso_box_select_requested)
        w.tso_delete_button.clicked.connect(h._on_tso_delete_requested)
        w.tso_move_up_button.clicked.connect(h._on_tso_move_up_requested)
        w.tso_move_down_button.clicked.connect(h._on_tso_move_down_requested)
        w.tso_import_from_3d_button.clicked.connect(h._on_tso_import_from_3d_requested)
        w.tso_delete_all_button.clicked.connect(h._on_tso_delete_all_requested)
        w.tso_modify_elevations_button.clicked.connect(h._on_tso_modify_elevations_requested)
        w.tso_refresh_relative_boundary_button.clicked.connect(h._on_tso_refresh_relative_boundary_requested)
        w.tso_auto_update_relative_z_checkbox.toggled.connect(h._on_tso_auto_update_relative_z_toggled)
        w.tso_generate_file_button.clicked.connect(h._on_tso_generate_file_requested)
        w.tso_write_to_3d_file_button.clicked.connect(h._on_tso_write_to_3d_file_requested)
        w.tso_table.itemChanged.connect(h._on_tso_item_changed)
        w.tso_table.itemSelectionChanged.connect(h._on_tso_selection_changed)
        w.tso_table.cellClicked.connect(h._on_tso_table_cell_clicked)
        w.tso_visibility_sidebar.selectedTSOsChanged.connect(h._on_tso_visibility_row_selected)
        w.tso_visibility_sidebar.selectedTSOPillChanged.connect(h._on_tso_visibility_pill_selected)
        w.tso_visibility_sidebar.selectedTrackSectionChanged.connect(h._on_tso_visibility_track_section_selected)
        w.tso_visibility_sidebar.selectedTSOOrderChanged.connect(h._on_tso_visibility_order_changed)
        w.tso_visibility_sidebar.objectListsChanged.connect(h._on_tso_visibility_lists_changed)
        w.tso_visibility_sidebar.objectListsSaved.connect(h._on_tso_visibility_lists_saved)
        w.preview.set_trackside_object_drag_callback(h._on_preview_tso_dragged)
        w.preview.set_trackside_object_drag_end_callback(h._on_preview_tso_drag_ended)
        w.preview.set_trackside_map_click_callback(h._on_preview_tso_map_clicked)
        w.preview.set_trackside_box_select_callback(h._on_preview_tso_box_selected)


class Track3DController:
    def __init__(self, host: object) -> None:
        self._host = host

    def connect_signals(self) -> None:
        h = self._host
        w = h._window
        w.three_d_file_select_button.clicked.connect(h._on_select_track3d_file_requested)
        w.three_d_file_catalog_inspector_button.clicked.connect(h._on_three_d_catalog_inspector_requested)
        w.three_d_show_section_entries_button.clicked.connect(h._on_three_d_show_selected_section_entries)
        w.three_d_show_section_object_lists_button.clicked.connect(h._on_three_d_show_selected_section_object_lists)
        w.three_d_show_section_tsos_button.clicked.connect(h._on_three_d_show_selected_section_tsos)
        w.three_d_preview_object_list_changes_button.clicked.connect(h._on_three_d_preview_selected_object_lists)
        w.three_d_apply_object_list_changes_button.clicked.connect(h._on_three_d_apply_selected_object_lists)
        w.three_d_apply_tso_definitions_button.clicked.connect(h._on_three_d_apply_selected_tso_definitions)
        w.three_d_apply_face_materials_button.clicked.connect(h._on_three_d_apply_selected_face_materials)
        w.three_d_file_inspect_button.clicked.connect(h._on_three_d_inspect_requested)
        w.three_d_file_fix_copy_button.clicked.connect(h._on_three_d_fix_copy_requested)
        w.three_d_file_fix_in_place_button.clicked.connect(h._on_three_d_fix_in_place_requested)
        w.three_d_file_select_colors_button.clicked.connect(h._on_edit_track3d_colors_requested)
        w.three_d_file_apply_colors_button.clicked.connect(h._on_three_d_apply_color_replacements_requested)
