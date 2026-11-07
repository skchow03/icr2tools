"""Qt N3 source pane mirroring CPU SourceEditor semantics.

The editor owns text and revision numbers but never touches the OpenGL
context. The Window debounces/schedules worker compilation, discards stale
results and keeps the last valid mesh on compilation failure.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, Qt, QTime, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QKeySequence, QPalette, QShortcut, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListView, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QComboBox, QDoubleSpinBox,
    QStackedWidget, QStyledItemDelegate, QToolButton, QToolTip, QTextEdit,
    QVBoxLayout, QWidget, QWidgetAction,
)

from appearance import DARK_COLORS, validated_colors
from source_help import help_for_lines, help_for_statement
from source_change_log import format_rename_event
from source_scale import scale_n3_source
from source_symmetry import (
    named_vertices, plan_mirrored_vertices, coordinate_replacements,
)
from source_inspection import (index_source_targets, target_offset,
                                          bsp_plane_points)
from source_filters import CATEGORIES, index_source_entries
from active_source import (
    active_source_labels, plane_vertex_dependencies, entry_is_active,
)
from source_rename import (
    DECLARATION, edited_declaration_label, declaration_label, reference_spans,
    plan_pointer_rename, qt_utf16_offset,
)

# Same N3 token categories and error location heuristics as the CPU editor.
LEX_RE = re.compile(
    r'(?P<comment>%[^\n]*)|(?P<string>"[^"\n]*")|'
    r'(?P<keyword>\b(?:3D|VERSION|NIL|POLY|LINE|LIST|FACE2?|BSPF|BSPA|BSP2|BSPN|MATERIAL|GROUP|MIP|SWITCH|DISTANCE|DYNAMIC|EXTERN|SUPEROBJ|PMP2|SRB|RECOLOR|DYNO|DATA)\b)|'
    r'(?P<label>^[ \t]*[A-Za-z_][A-Za-z_0-9-]*(?=[ \t]*:))',
    re.I | re.M,
)


def find_error_line(source, error):
    match = re.search(r'\bline\s+(\d+)\b', error, re.I)
    if match:
        return max(1, int(match.group(1)))
    match = re.search(r"(?:in|at)\s+(?:record|label)\s+['\"]?([A-Za-z_][\w-]*)", error, re.I)
    if match:
        decl = re.search(r'(?m)^\s*' + re.escape(match.group(1)) + r'\s*:', source)
        if decl:
            return source.count('\n', 0, decl.start()) + 1
    match = re.search(r"(?:unresolved N3 pointer|unknown plane vertex):?\s*['\"]?([A-Za-z_][\w-]*)", error, re.I)
    if match:
        token = re.search(r'(?<![\w])' + re.escape(match.group(1)) + r'(?![\w])', source)
        if token:
            return source.count('\n', 0, token.start()) + 1
    return 1


class N3Highlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.formats = {}
        self.set_colors(DARK_COLORS)

    def set_colors(self, colors):
        tokens = {
            "comment": colors["source_comment"],
            "string": colors["source_string"],
            "keyword": colors["source_keyword"],
            "label": colors["source_label"],
        }
        self.formats = {}
        for name, color in tokens.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self.formats[name] = fmt
        # Like highlightBlock itself, limit recoloring to the first 1,500
        # blocks. A .3D file can contain millions of declarations; calling
        # rehighlight() on the entire QTextDocument on each color change
        # would make the picker stall for large tracks.
        block = self.document().firstBlock()
        count = 0
        while block.isValid() and count < 1500:
            self.rehighlightBlock(block)
            block = block.next()
            count += 1

    def highlightBlock(self, text):
        # Highlighting millions of generated N3 declarations can otherwise
        # make the UI unusable. All text remains available for editing.
        if self.currentBlock().blockNumber() >= 1500 or len(text) > 12000:
            return
        for match in LEX_RE.finditer(text):
            name = match.lastgroup
            if name:
                self.setFormat(match.start(), match.end()-match.start(),
                               self.formats[name])


class FilteredStatementsModel(QAbstractListModel):
    """Virtualized source entries with safe per-statement inline editing.

    The canonical QTextDocument always owns the text; model rows contain
    source spans, not copies of N3 to save or compile.
    """

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.entries = ()
        self.starts = ()
        self.active_line = None
        self.active_visibility = None

    def set_entries(self, entries):
        self.beginResetModel()
        self.entries = tuple(entries)
        self.starts = tuple(e.first_line for e in self.entries)
        self.endResetModel()

    def _row_at_line(self, line):
        if line is None or not self.starts:
            return None
        row = bisect_right(self.starts, line) - 1
        if row < 0 or line > self.entries[row].last_line:
            return None
        return row

    def set_inspection(self, line, visible):
        before = self._row_at_line(self.active_line)
        self.active_line = line
        self.active_visibility = visible
        after = self._row_at_line(line)
        for row in {before, after}:
            if row is not None:
                self.dataChanged.emit(
                    self.index(row), self.index(row),
                    [Qt.ItemDataRole.DisplayRole,
                     Qt.ItemDataRole.BackgroundRole,
                     Qt.ItemDataRole.ForegroundRole])

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None
        entry = self.entries[index.row()]
        # A MATERIAL containing an inline POLY is still categorized as
        # MATERIAL for filtering, but is an inspectable polygon row.
        target = self.owner._source_index.at_line(entry.first_line)
        active = (target is not None and target[0] in ("polygon", "vertex") and
                  self._row_at_line(self.active_line) == index.row() and
                  self.active_visibility is not None)
        if role == Qt.ItemDataRole.DisplayRole:
            status = (("  [VISIBLE]" if self.active_visibility else
                       "  [NOT DRAWN]") if active and target[0] == "polygon"
                      else "")
            return (f"{entry.first_line + 1:>6}  "
                    f"[{entry.category}]  {entry.preview}{status}")
        if active and role == Qt.ItemDataRole.BackgroundRole:
            return QColor(self.owner.colors["source_visible_background" if self.active_visibility else "source_hidden_background"])
        if active and role == Qt.ItemDataRole.ForegroundRole:
            return QColor(self.owner.colors["source_highlight_text"])
        if role == Qt.ItemDataRole.ToolTipRole:
            details = (f"Original line {entry.first_line + 1}"
                       + (f"–{entry.last_line + 1}" if
                          entry.last_line != entry.first_line else "")
                       + f" | {entry.category}")
            syntax = help_for_statement(self.owner._filtered_statement_text(entry))
            if syntax is not None:
                return syntax.tooltip_html(note=details)
            return details + ("\n\nDouble-click to edit this statement; "
                              "Ctrl+Enter applies, Esc cancels.")
        if role == Qt.ItemDataRole.UserRole:
            return entry.first_line
        if role == Qt.ItemDataRole.EditRole:
            return self.owner._filtered_statement_text(entry)
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and self.owner.ready:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (role != Qt.ItemDataRole.EditRole or not index.isValid() or
                not self.owner.ready or index.row() >= len(self.entries)):
            return False
        return self.owner._replace_filtered_statement(
            self.entries[index.row()], str(value))


class InlineStatementDelegate(QStyledItemDelegate):
    """Edit one complete N3 statement directly within the filtered list."""

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setFont(option.font)
        editor.setTabChangesFocus(True)
        editor.setToolTip(
            "Edit the statement directly. Ctrl+Enter applies; Esc cancels. "
            "Hover or press Ctrl+Shift+Space for N3 syntax help.")
        index.model().owner._register_inline_help_editor(editor)
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.ItemDataRole.EditRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.ItemDataRole.EditRole)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        entries = index.model().entries
        if 0 <= index.row() < len(entries):
            entry = entries[index.row()]
            rows = min(7, entry.last_line - entry.first_line + 1)
            size.setHeight(max(size.height(),
                               option.fontMetrics.lineSpacing() * rows + 10))
        return size

    def eventFilter(self, editor, event):
        if isinstance(editor, QPlainTextEdit) and event.type() == QEvent.Type.KeyPress:
            if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.commitData.emit(editor)
                self.closeEditor.emit(editor)
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.closeEditor.emit(
                    editor, QStyledItemDelegate.EndEditHint.RevertModelCache)
                return True
        return super().eventFilter(editor, event)


class SourcePane(QWidget):
    compileRequested = Signal(int, str)
    saveRequested = Signal()
    exportRequested = Signal()
    cursorTargetChanged = Signal(object)  # None or (kind, authored_label)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = dict(DARK_COLORS)
        self.revision = 0
        self.applied_revision = 0
        self.source_path = Path('new_model.3d')
        self.line_ending = '\n'
        self._setting = False
        self._last_error_line = None
        self._initial = ''
        self._ready = False
        self._source_index = index_source_targets("")
        self._last_cursor_target = None
        self._polygon_visible = None
        self._rename_snapshot = ""
        self._rename_pending = None  # (zero-based declaration line, original label)
        self._applying_rename = False
        self._filter_entries = ()
        self._filter_cache_revision = -1
        self._filter_sync = False
        self._filtered_edit_active = False
        self._filter_return_line = None
        self._distance_model = None
        self._distance_mode = "auto"
        self._distance_eye = (0.0, 0.0, 0.0)
        self._distance_dependencies_key = None
        self._distance_dependencies = {}
        self._distance_labels_key = None
        self._distance_labels = set()
        self._active_edit_line = None
        self._inline_help_editor = None
        # Mirror mode is intentionally session/model-local and OFF by default.
        # Last validated geometry is the only safe pairing reference.
        self._symmetry_baseline = ""
        self._symmetry_skip_once = False
        self._applying_symmetry = False

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        apply_button = QPushButton('Apply now')
        apply_button.clicked.connect(self.apply_now)
        controls.addWidget(apply_button)
        save_button = QPushButton('Save .3D as…')
        save_button.clicked.connect(self.saveRequested.emit)
        controls.addWidget(save_button)
        export_button = QPushButton('Export compiled .3DO…')
        export_button.clicked.connect(self.exportRequested.emit)
        controls.addWidget(export_button)
        error_button = QPushButton('Find error')
        error_button.clicked.connect(self.goto_error)
        controls.addWidget(error_button)
        self.auto_rename = QCheckBox("Auto-rename references")
        self.auto_rename.setChecked(True)
        self.auto_rename.setToolTip(
            "When a declaration label changes, update its N3 pointer references "
            "without changing comments, filenames or partial identifiers.")
        self.auto_rename.toggled.connect(self._auto_rename_toggled)
        controls.addWidget(self.auto_rename)
        layout.addLayout(controls)

        symmetry_row = QHBoxLayout()
        self.symmetry_enabled = QCheckBox("Symmetrical vertex editing")
        self.symmetry_enabled.setObjectName("symmetryEditingEnabled")
        self.symmetry_enabled.setChecked(False)
        self.symmetry_enabled.setToolTip(
            "OFF by default. Mirror source XYZ vertex edits across the "
            "chosen world plane; matching uses the last valid coordinates. "
            "Texture U/V values are never edited.")
        symmetry_row.addWidget(self.symmetry_enabled)
        symmetry_row.addWidget(QLabel("Plane"))
        self.symmetry_plane = QComboBox()
        self.symmetry_plane.setObjectName("symmetryPlane")
        for label in ("X", "Y", "Z"):
            self.symmetry_plane.addItem(label + "=constant", label)
        self.symmetry_plane.setToolTip(
            "X mirrors across YZ; Y across XZ; Z across XY.")
        symmetry_row.addWidget(self.symmetry_plane)
        symmetry_row.addWidget(QLabel("At"))
        self.symmetry_plane_at = QDoubleSpinBox()
        self.symmetry_plane_at.setObjectName("symmetryPlaneAt")
        self.symmetry_plane_at.setRange(-2_000_000_000, 2_000_000_000)
        self.symmetry_plane_at.setDecimals(3)
        self.symmetry_plane_at.setValue(0)
        self.symmetry_plane_at.setToolTip(
            "Raw Papyrus coordinate of the symmetry plane; usually 0.")
        self.symmetry_plane_at.setMaximumWidth(110)
        symmetry_row.addWidget(self.symmetry_plane_at)
        symmetry_row.addWidget(QLabel("Tolerance"))
        self.symmetry_tolerance = QDoubleSpinBox()
        self.symmetry_tolerance.setObjectName("symmetryTolerance")
        self.symmetry_tolerance.setRange(0, 1_000_000)
        self.symmetry_tolerance.setDecimals(3)
        self.symmetry_tolerance.setValue(0)
        self.symmetry_tolerance.setToolTip(
            "Maximum raw-coordinate difference for finding mirror points; "
            "0 requires exact matches. Multiple matches require a choice.")
        self.symmetry_tolerance.setMaximumWidth(94)
        symmetry_row.addWidget(self.symmetry_tolerance)
        layout.addLayout(symmetry_row)
        self.symmetry_enabled.toggled.connect(self._symmetry_toggled)
        for widget in (self.symmetry_plane, self.symmetry_plane_at,
                       self.symmetry_tolerance):
            widget.setEnabled(False)

        # The popup filters editable, independently bounded statements.
        # Never hide or delete QTextBlocks in the canonical document: doing
        # so could damage unrelated source during Backspace, undo or paste.
        filter_bar = QHBoxLayout()
        self.filter_button = QToolButton()
        self.filter_button.setText("Filter statements (all)")
        self.filter_button.setToolTip(
            "Choose N3 statement types to show or hide. Filtered statements "
            "remain editable in place; full source is preserved.")
        self.filter_menu = QMenu(self.filter_button)
        self.filter_button.setMenu(self.filter_menu)
        self.filter_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self._filter_checks = {}
        self._filter_counts = {}

        filter_widget = QWidget(self.filter_menu)
        filter_layout = QVBoxLayout(filter_widget)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(3)
        menu_actions = QHBoxLayout()
        all_button = QPushButton("Show all")
        all_button.clicked.connect(self._show_all_filters)
        menu_actions.addWidget(all_button)
        none_button = QPushButton("Hide all")
        none_button.clicked.connect(self._hide_all_filters)
        menu_actions.addWidget(none_button)
        filter_layout.addLayout(menu_actions)
        filter_layout.addWidget(QLabel("Statement types   ·   Only = isolate"))
        for category in CATEGORIES:
            row = QHBoxLayout()
            checkbox = QCheckBox(category)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._filters_changed)
            self._filter_checks[category] = checkbox
            row.addWidget(checkbox, 1)
            only = QPushButton("Only")
            only.setToolTip(f"Show only {category} entries")
            only.setMaximumWidth(52)
            only.clicked.connect(
                lambda checked=False, kind=category:
                self._only_filter(kind))
            row.addWidget(only)
            filter_layout.addLayout(row)
        self.current_distance_only = QCheckBox(
            "Active SWITCH DISTANCE branches only")
        self.current_distance_only.setObjectName("currentDistanceOnly")
        self.current_distance_only.setToolTip(
            "Only show declarations reachable through the current RES "
            "distance choices, including used vertices, POLYs, LIST, BSP, "
            "FACE, MATERIAL, DYNAMIC and SWITCH wrappers. "
            "This is LOD reachability, not camera BSP or occlusion.")
        self.current_distance_only.toggled.connect(self._apply_filters)
        filter_layout.addWidget(self.current_distance_only)
        popup = QWidgetAction(self.filter_menu)
        popup.setDefaultWidget(filter_widget)
        self.filter_menu.addAction(popup)
        self.filter_menu.aboutToShow.connect(self._filter_menu_opening)
        filter_bar.addWidget(self.filter_button)
        filter_bar.addWidget(QLabel("Find:"))
        self.filter_search = QLineEdit()
        self.filter_search.setPlaceholderText("Label or source text…")
        self.filter_search.setClearButtonEnabled(True)
        self.filter_search.textChanged.connect(self._apply_filters)
        filter_bar.addWidget(self.filter_search, 1)
        self.filter_status = QLabel("All source lines shown")
        filter_bar.addWidget(self.filter_status)
        layout.addLayout(filter_bar)

        self.status = QLabel('Open a .3D or .3DO to edit source.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont('Consolas', 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.editor.setTabStopDistance(72)
        self.editor.setUndoRedoEnabled(True)
        self.editor.setToolTip(
            "Hover over N3 commands for syntax and purpose. "
            "Ctrl+Shift+Space: show details; F2: rename pointer.")
        self.highlighter = N3Highlighter(self.editor.document())
        self.editor.textChanged.connect(self._edited)
        self.editor.cursorPositionChanged.connect(self._cursor_changed)
        self.filtered_model = FilteredStatementsModel(self)
        self.filtered_list = QListView()
        self.filtered_list.setModel(self.filtered_model)
        self.filtered_list.setUniformItemSizes(False)
        self.filtered_list.setAlternatingRowColors(True)
        self.filtered_list.setItemDelegate(InlineStatementDelegate(self.filtered_list))
        self.filtered_list.itemDelegate().closeEditor.connect(
            lambda *_: QTimer.singleShot(0, self._apply_filters))
        self.filtered_list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.SelectedClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed)
        self.filtered_list.setFont(font)
        self.filtered_list.setToolTip(
            "Select a statement to inspect in the GPU viewport. "
            "F2 renames its pointer; double-click edits the whole statement. "
            "Ctrl+Enter applies inline edits, Esc cancels.")
        self.filtered_list.selectionModel().currentChanged.connect(
            self._inspect_filtered_entry)
        self.filtered_page = QWidget()
        filtered_layout = QVBoxLayout(self.filtered_page)
        filtered_layout.setContentsMargins(0, 0, 0, 0)
        filtered_layout.addWidget(QLabel(
            "Editable filtered statements. Double-click or type to edit; "
            "Ctrl+Enter applies, Esc cancels."))
        filtered_layout.addWidget(self.filtered_list, 1)
        edit_button = QPushButton("Show full source at selected line")
        edit_button.clicked.connect(self._edit_filtered_entry)
        filtered_layout.addWidget(edit_button)

        self.source_stack = QStackedWidget()
        self.source_stack.addWidget(self.editor)
        self.source_stack.addWidget(self.filtered_page)
        layout.addWidget(self.source_stack, 1)

        # Short live signature hint; expanded guidance is available on hover
        # or from Ctrl+Shift+Space. The label cannot change N3 source.
        syntax_row = QHBoxLayout()
        self.syntax_help = QLabel(
            "N3 help — place the cursor on a command, or hover for syntax.")
        self.syntax_help.setObjectName("n3SyntaxHelp")
        self.syntax_help.setTextFormat(Qt.TextFormat.PlainText)
        self.syntax_help.setWordWrap(True)
        self.syntax_help.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.syntax_help.setMaximumHeight(
            self.syntax_help.fontMetrics().lineSpacing() * 4 + 8)
        syntax_row.addWidget(self.syntax_help, 1)
        syntax_button = QToolButton()
        syntax_button.setObjectName("n3SyntaxHelpButton")
        syntax_button.setText("?")
        syntax_button.setToolTip(
            "Show full N3 statement help at the cursor (Ctrl+Shift+Space)")
        syntax_button.clicked.connect(self.show_syntax_help)
        syntax_row.addWidget(syntax_button)
        layout.addLayout(syntax_row)

        # Read-only audit trail for programmatic edits. Four visible text
        # rows, scrollable independently of the editable N3 document.
        history_header = QHBoxLayout()
        history_header.addWidget(QLabel("Automatic source changes"))
        history_header.addStretch()
        clear_history = QPushButton("Clear log")
        clear_history.setToolTip("Clear the displayed change history only; "
                                 "do not modify or undo the .3D source.")
        history_header.addWidget(clear_history)
        layout.addLayout(history_header)
        self.change_log = QPlainTextEdit()
        self.change_log.setObjectName("automaticSourceChangeLog")
        self.change_log.setReadOnly(True)
        self.change_log.setUndoRedoEnabled(False)
        self.change_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.change_log.setFont(font)
        self.change_log.document().setMaximumBlockCount(2000)
        self.change_log.setPlaceholderText(
            "Automatic pointer and reference updates appear here.")
        self.change_log.setToolTip(
            "Per-model history of automatic edits with original line numbers. "
            "Select and copy entries as needed; Undo does not erase history.")
        self.change_log.setFixedHeight(
            self.change_log.fontMetrics().lineSpacing() * 4 + 14)
        layout.addWidget(self.change_log)
        clear_history.clicked.connect(self.change_log.clear)
        self.position = QLabel('Line 1, column 1')
        layout.addWidget(self.position)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(650)
        self._debounce.timeout.connect(self.apply_now)
        self._rename_timer = QTimer(self)
        self._rename_timer.setSingleShot(True)
        self._rename_timer.setInterval(450)
        self._rename_timer.timeout.connect(self._commit_pending_rename)
        self.rename_pointer_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_F2), self)
        self.rename_pointer_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.rename_pointer_shortcut.activated.connect(
            self.rename_selected_pointer)
        self.syntax_help_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+Space"), self)
        self.syntax_help_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.syntax_help_shortcut.activated.connect(self.show_syntax_help)
        # QAbstractItemView normally interprets F2 as "edit the entire row".
        # Intercept its keypress before the default view handler so this
        # shortcut always edits just the pointer label in either view.
        for widget in (self.editor, self.editor.viewport(),
                       self.filtered_list, self.filtered_list.viewport()):
            widget.installEventFilter(self)
        self.set_appearance_colors(self.colors)

    def set_appearance_colors(self, colors):
        """Apply colors without treating document formatting as a source edit."""
        was_setting = self._setting
        self._setting = True
        try:
            self.colors = validated_colors(colors)
            base = QColor(self.colors["source_background"])
            text = QColor(self.colors["source_text"])
            selection = QColor(self.colors["source_selection_background"])
            selection_text = QColor(self.colors["source_selection_text"])
            for widget in (self.editor, self.filtered_list, self.change_log):
                palette = widget.palette()
                palette.setColor(QPalette.ColorRole.Base, base)
                palette.setColor(QPalette.ColorRole.Text, text)
                palette.setColor(QPalette.ColorRole.Highlight, selection)
                palette.setColor(QPalette.ColorRole.HighlightedText, selection_text)
                palette.setColor(QPalette.ColorRole.AlternateBase,
                                 base.lighter(110) if base.lightness() < 128
                                 else base.darker(105))
                widget.setPalette(palette)
            # Rehighlighting can emit QTextDocument change notifications;
            # they must not trigger recompilation or invalidate source offsets.
            self.highlighter.set_colors(self.colors)
            self._refresh_extra_selections()
            if self.filtered_model.rowCount():
                self.filtered_model.dataChanged.emit(
                    self.filtered_model.index(0),
                    self.filtered_model.index(self.filtered_model.rowCount() - 1))
            self.filtered_list.viewport().update()
        finally:
            self._setting = was_setting

    def _register_inline_help_editor(self, editor):
        """Help for active filtered-row edits, before Ctrl+Enter commits them."""
        self._inline_help_editor = editor
        editor.destroyed.connect(
            lambda *_: setattr(self, "_inline_help_editor", None))
        editor.textChanged.connect(lambda e=editor: self._update_syntax_help(e))
        editor.cursorPositionChanged.connect(
            lambda e=editor: self._update_syntax_help(e))
        editor.viewport().installEventFilter(self)
        editor.installEventFilter(self)
        self._update_syntax_help(editor)

    def _help_at_document_line(self, line):
        """Inspect at most 48 nearby QTextBlocks, even for huge .3D tracks."""
        block = self.editor.document().findBlockByNumber(line)
        rows = []
        for _ in range(48):
            if not block.isValid():
                break
            rows.append(block.text())
            block = block.previous()
        if not rows:
            return None
        rows.reverse()
        return help_for_lines(rows, len(rows) - 1)

    def _active_syntax_help(self, inline_editor=None):
        if not self._ready:
            return None
        if inline_editor is not None:
            return help_for_lines(
                inline_editor.toPlainText().splitlines(),
                inline_editor.textCursor().blockNumber())
        if self.source_stack.currentWidget() is self.filtered_page:
            index = self.filtered_list.currentIndex()
            if not index.isValid() or index.row() >= len(self.filtered_model.entries):
                return None
            return help_for_statement(self._filtered_statement_text(
                self.filtered_model.entries[index.row()]))
        return self._help_at_document_line(
            self.editor.textCursor().blockNumber())

    def _update_syntax_help(self, inline_editor=None):
        if self._setting:
            return
        tip = self._active_syntax_help(inline_editor)
        self.syntax_help.setText(
            tip.compact() if tip is not None else
            "N3 help — place the cursor on a command, or hover for syntax.")
        self.syntax_help.setToolTip(
            tip.tooltip() if tip is not None else
            "Hover over an N3 statement for syntax and purpose.")

    def _show_source_tooltip(self, tip, editor, line):
        """Anchor wrapped help below the relevant line, inside Source pane.

        Native Qt tooltips anchored to the mouse or end of a long code row can
        spill to the LEFT of the editor. Anchor near the text area left edge,
        and below the line rather than in the model viewport. Qt may shift
        upward if there is not enough space below near the screen bottom.
        """
        if tip is None:
            QToolTip.hideText()
            return
        viewport = editor.viewport()
        block = editor.document().findBlockByNumber(line)
        if not block.isValid():
            return
        row = editor.cursorRect(QTextCursor(block))
        anchor = viewport.mapToGlobal(QPoint(12, row.bottom() + 6))
        QToolTip.showText(anchor, tip.tooltip_html(), viewport)

    def _show_filtered_tooltip(self, tip, index=None):
        """Keep filtered-row help below its row, on the Source side."""
        if tip is None:
            QToolTip.hideText()
            return
        view = self.filtered_list
        index = view.currentIndex() if index is None else index
        if not index.isValid():
            return
        row = view.visualRect(index)
        anchor = view.viewport().mapToGlobal(QPoint(12, row.bottom() + 6))
        QToolTip.showText(anchor, tip.tooltip_html(), view.viewport())

    def show_syntax_help(self):
        """Ctrl+Shift+Space or ? opens details below the source statement."""
        from PySide6.QtWidgets import QApplication
        inline = self._inline_help_editor
        if inline is None or QApplication.focusWidget() is not inline:
            inline = None
        tip = self._active_syntax_help(inline)
        if tip is None:
            return
        if inline is not None:
            self._show_source_tooltip(
                tip, inline, inline.textCursor().blockNumber())
        elif self.source_stack.currentWidget() is self.filtered_page:
            self._show_filtered_tooltip(tip)
        else:
            self._show_source_tooltip(
                tip, self.editor, self.editor.textCursor().blockNumber())

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.KeyPress and
                event.key() == Qt.Key.Key_F2 and
                watched in (self.editor, self.editor.viewport(),
                            self.filtered_list, self.filtered_list.viewport())):
            self.rename_selected_pointer()
            event.accept()
            return True
        if event.type() == QEvent.Type.ToolTip:
            inline = self._inline_help_editor
            if watched in (self.editor, self.editor.viewport()):
                point = (event.pos() if watched is self.editor.viewport()
                         else self.editor.viewport().mapFrom(
                             self.editor, event.pos()))
                block = self.editor.cursorForPosition(point).blockNumber()
                tip = (self._help_at_document_line(block)
                       if self._ready else None)
            elif inline is not None and watched in (
                    inline, inline.viewport()):
                point = (event.pos() if watched is inline.viewport()
                         else inline.viewport().mapFrom(inline, event.pos()))
                block = inline.cursorForPosition(point).blockNumber()
                tip = help_for_lines(
                    inline.toPlainText().splitlines(), block)
            elif watched in (self.filtered_list, self.filtered_list.viewport()):
                point = (event.pos() if watched is self.filtered_list.viewport()
                         else self.filtered_list.viewport().mapFrom(
                             self.filtered_list, event.pos()))
                index = self.filtered_list.indexAt(point)
                if index.isValid() and index.row() < len(self.filtered_model.entries):
                    entry = self.filtered_model.entries[index.row()]
                    tip = help_for_statement(self._filtered_statement_text(entry))
                    if tip is not None:
                        self._show_filtered_tooltip(tip, index)
                        return True
                return super().eventFilter(watched, event)
            else:
                return super().eventFilter(watched, event)
            if tip is not None:
                # The popup must follow the hovered source line, not the
                # screen's mouse position (which can push it over the model).
                self._show_source_tooltip(
                    tip, self.editor if watched in
                    (self.editor, self.editor.viewport()) else inline,
                    block)
            else:
                QToolTip.hideText()
            return True
        return super().eventFilter(watched, event)

    @property
    def ready(self):
        return self._ready

    @property
    def dirty(self):
        return self._ready and self.editor.toPlainText() != self._initial

    @property
    def pending(self):
        return self.revision != self.applied_revision

    def get_source(self):
        value = self.editor.toPlainText()
        return value.replace('\n', '\r\n') if self.line_ending == '\r\n' else value

    def apply_source_replacement(self, source, description):
        """Apply a validated structural N3 transformation as one Undo step.

        Keep the existing saved-source baseline, syntax help, live compiler,
        source filters and rename tracker consistent with an ordinary edit.
        """
        if not self._ready or self.pending or self._last_error_line is not None:
            raise ValueError("Apply or correct pending source edits before splitting.")
        if self.filtered_list.state() == QAbstractItemView.State.EditingState:
            raise ValueError("Finish the filtered-row edit before splitting.")
        previous = self.editor.toPlainText()
        if source == previous:
            raise ValueError("The split did not change the source document.")
        self._rename_timer.stop()
        self._rename_pending = None
        self._filtered_edit_active = False
        self._applying_rename = True
        cursor = QTextCursor(self.editor.document())
        try:
            cursor.beginEditBlock()
            try:
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText(source)
            finally:
                cursor.endEditBlock()
        finally:
            self._applying_rename = False
        self._rename_snapshot = source
        self._symmetry_skip_once = True
        self._edited()
        self.change_log.appendPlainText(
            f"[{QTime.currentTime().toString('HH:mm:ss')}] {description}")
        self.status.setText(f"{description}. Validating GPU preview (unsaved).")

    def scale_model(self, factor, *, divide=False):
        """Uniformly scale the canonical source as one undoable operation.

        This is an explicit model transformation, not a pointer rename. Plan
        and range-check everything first; reject pending/invalid source and
        active filtered-row edits rather than destroying unfinished work.
        """
        if not self._ready:
            raise ValueError("Open a model and prepare its editable .3D Source first.")
        if self.pending or self._last_error_line is not None:
            raise ValueError(
                "Apply or correct pending .3D source edits before scaling the model.")
        if self.filtered_list.state() == QAbstractItemView.State.EditingState:
            raise ValueError("Finish or cancel the filtered-row edit before scaling.")
        source = self.editor.toPlainText()
        result = scale_n3_source(source, factor, divide=divide)
        if result.source == source:
            raise ValueError("This scale produces no coordinate changes.")

        original_line = self.editor.textCursor().blockNumber()
        self._rename_timer.stop()
        self._rename_pending = None
        self._filtered_edit_active = False
        self._applying_rename = True
        cursor = QTextCursor(self.editor.document())
        try:
            cursor.beginEditBlock()
            try:
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText(result.source)
            finally:
                cursor.endEditBlock()
        finally:
            self._applying_rename = False

        # Avoid the auto-reference-rename engine interpreting bulk text
        # replacement as an edit to a declaration label.
        self._rename_snapshot = result.source
        self._symmetry_skip_once = True
        old_position = self.editor.document().findBlockByNumber(original_line)
        if old_position.isValid():
            self.editor.setTextCursor(QTextCursor(old_position))
        self._edited()
        self.change_log.appendPlainText(
            f"[{QTime.currentTime().toString('HH:mm:ss')}] "
            f"{result.summary()}" +
            ("; pinned coordinate-scale hint" if result.inserted_scale_hint else "")
        )
        self.status.setText(
            f"{result.summary()}. Validating preview; source not yet saved.")
        return result

    def _log_automatic_rename(self, source, old, new, spans, *,
                              action, declaration_line):
        """Describe edits already committed to the canonical .3D document."""
        entries = format_rename_event(
            source, old, new, spans, action=action,
            declaration_line=declaration_line)
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        self.change_log.appendPlainText(
            f"[{timestamp}] {entries[0]}" +
            ("\n" + "\n".join(entries[1:]) if len(entries) > 1 else ""))

    def set_source(self, text, path, *, status=None):
        # A newly loaded file must not inherit an open filtered-row editor
        # or selection from the previous model.
        self.filtered_list.reset()
        self.change_log.clear()
        self._debounce.stop()
        self._rename_timer.stop()
        self._rename_pending = None
        self._polygon_visible = None
        self._active_edit_line = None
        self.symmetry_enabled.setChecked(False)
        self._symmetry_skip_once = False
        self._setting = True
        try:
            self.line_ending = '\r\n' if '\r\n' in text else '\n'
            normalized = text.replace('\r\n', '\n')
            self.editor.setPlainText(normalized)
            self.editor.document().setModified(False)
            self._initial = normalized
            self.source_path = Path(path)
            self.revision += 1
            self.applied_revision = self.revision
            self._ready = True
            self._last_error_line = None
            self.editor.setExtraSelections([])
            self.status.setText(status or 'N3 source ready. Edit to update GPU viewport.')
            self.editor.setReadOnly(False)
        finally:
            self._setting = False
        self._rename_snapshot = normalized
        self._symmetry_baseline = normalized
        self._source_index = index_source_targets(normalized)
        self._filter_cache_revision = -1
        self._distance_dependencies_key = None
        self._distance_labels_key = None
        self._apply_filters()
        self._cursor_changed()
        self._update_syntax_help()

    def mark_saved(self):
        """Set the clean baseline only after the source was written successfully."""
        if self._ready:
            self._initial = self.editor.toPlainText()
            self.editor.document().setModified(False)

    def reset(self, status='Open the Source tab to generate editable N3.'):
        self.filtered_list.reset()
        self.change_log.clear()
        self._debounce.stop()
        self._rename_timer.stop()
        self._rename_pending = None
        self._polygon_visible = None
        self._active_edit_line = None
        self.symmetry_enabled.setChecked(False)
        self._symmetry_baseline = ""
        self._symmetry_skip_once = False
        self._setting = True
        try:
            self.editor.clear()
            self.editor.setReadOnly(True)
            self._ready = False
            self._initial = ''
            self.revision += 1
            self.applied_revision = self.revision
            self._last_error_line = None
            self.editor.setExtraSelections([])
            self.status.setText(status)
        finally:
            self._setting = False
        self._rename_snapshot = ""
        self._source_index = index_source_targets("")
        self._filter_cache_revision = -1
        self._distance_model = None
        self._distance_dependencies_key = None
        self._distance_labels_key = None
        self._apply_filters()
        self._cursor_changed()
        self._update_syntax_help()

    def _edited(self):
        if self._setting or not self._ready:
            return
        if self._applying_rename or self._applying_symmetry:
            return
        self._track_symbol_edit()
        self.revision += 1
        self._filter_cache_revision = -1
        self._distance_dependencies_key = None
        self._distance_labels_key = None
        if self.source_stack.currentIndex() == 1 and not self._filtered_edit_active:
            self._apply_filters()
        self._last_error_line = None
        self._polygon_visible = None
        self._refresh_extra_selections()
        self.status.setText('Editing… last valid GPU preview retained until compilation succeeds.')
        self._debounce.start()
        self._emit_cursor_target()
        self._update_syntax_help()

    def apply_now(self):
        if not self._ready:
            return
        self._debounce.stop()
        if not self.pending:
            return
        self.apply_symmetry_before_use()
        self._debounce.stop()
        self.status.setText('Compiling N3 and rebuilding GPU preview…')
        self.compileRequested.emit(self.revision, self.get_source())

    def mark_valid(self, revision, model):
        if revision != self.revision:
            return
        self.applied_revision = revision
        self._last_error_line = None
        self._polygon_visible = None
        self._active_edit_line = None
        self._refresh_extra_selections()
        self._symmetry_baseline = self.editor.toPlainText()
        self._symmetry_skip_once = False
        self._source_index = index_source_targets(self.editor.toPlainText())
        self._distance_dependencies_key = None
        self._distance_labels_key = None
        if self.current_distance_only.isChecked():
            self._apply_filters()
        self.status.setText(
            f'Valid N3: {len(model.vertices):,} vertices, '
            f'{len(model.polygons):,} polygons. GPU preview updated (unsaved).')
        self._emit_cursor_target()

    def mark_error(self, revision, error):
        if revision != self.revision:
            return
        self.applied_revision = revision
        self._active_edit_line = None
        line = find_error_line(self.get_source(), error)
        self._last_error_line = line
        block = self.editor.document().findBlockByNumber(line-1)
        if block.isValid():
            selected = QTextEdit.ExtraSelection()
            selected.format.setBackground(QColor(self.colors['source_error_background']))
            selected.format.setForeground(QColor(self.colors['source_highlight_text']))
            selected.format.setProperty(
                QTextCharFormat.Property.FullWidthSelection, True)
            selected.cursor = QTextCursor(block)
            self.editor.setExtraSelections([selected])
        self._polygon_visible = None
        if self.current_distance_only.isChecked():
            self._apply_filters()
        self.status.setText(f'Line {line}: {error}. Last valid GPU preview retained.')
        self._emit_cursor_target()

    def goto_error(self):
        if not self._last_error_line:
            return
        if self.source_stack.currentIndex() == 1:
            self._show_all_filters()
        block = self.editor.document().findBlockByNumber(self._last_error_line-1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()
            self.editor.setFocus()

    def goto_model_vertex(self, model, offset):
        """Jump to a compiled root vertex's authored or generated N3 label."""
        return self._goto_model_declaration(model, offset, "vertex")

    def goto_model_polygon(self, model, offset):
        """Reveal a picked POLY, scrolling its filtered row when available."""
        return self._goto_model_declaration(model, offset, "polygon")

    def _goto_model_declaration(self, model, offset, kind):
        """Navigate without modifying N3, including authored pointer names."""
        records = getattr(model, "vertices" if kind == "vertex" else "polygons",
                          {}) if model is not None else {}
        if (not self._ready or self.pending or self._last_error_line is not None
                or offset not in records):
            return False
        # Compiled authored N3 uses arbitrary labels. Generated binary N3
        # uses "_<body offset>" without a name mapping.
        candidate_labels = {f"_{offset}"}
        candidate_labels.update(
            name for name, body_offset in
            getattr(model, "n3_label_offsets", {}).items()
            if body_offset == offset)
        target = next((
            entry for entry in self._source_index.targets
            if entry.kind == kind and
            (kind == "polygon" or entry.label in candidate_labels) and
            target_offset(model, kind, entry.label) == offset), None)
        if target is None:
            return False
        block = self.editor.document().findBlockByNumber(target.first_line)
        if not block.isValid():
            return False

        filtered_row = None
        if kind == "polygon" and self.source_stack.currentWidget() is self.filtered_page:
            # Keep the filtered .3D Viewer when its row is available. If a
            # search/type/LOD filter hides the picked POLY, reveal POLYs rather
            # than silently navigating to an invisible row.
            def row_for_target():
                return next((
                    row for row, entry in enumerate(self.filtered_model.entries)
                    if entry.first_line <= target.first_line <= entry.last_line),
                    None)
            filtered_row = row_for_target()
            if filtered_row is None:
                self.filter_search.clear()
                self._set_selected_filters({"POLY"}, clear_distance=True)
                filtered_row = row_for_target()
        else:
            # Vertex clicks retain the existing behavior of showing the full
            # source document, even when a statement filter was active.
            self.source_stack.setCurrentWidget(self.editor)

        if filtered_row is not None:
            index = self.filtered_model.index(filtered_row)
            self.filtered_list.setCurrentIndex(index)
            self.filtered_list.scrollTo(
                index, QAbstractItemView.ScrollHint.PositionAtCenter)
        elif self.source_stack.currentWidget() is self.filtered_page:
            self.source_stack.setCurrentWidget(self.editor)

        cursor = QTextCursor(block)
        label_start = block.text().find(target.label)
        if label_start >= 0:
            cursor.setPosition(block.position() + label_start)
            cursor.setPosition(
                block.position() + label_start + len(target.label),
                QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        if filtered_row is not None:
            self.filtered_list.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._emit_cursor_target()
        return True

    def current_target(self):
        """Return a declaration only when its source matches the compiled model."""
        if not self._ready or self.pending or self._last_error_line is not None:
            return None
        return self._source_index.at_line(self.editor.textCursor().blockNumber())

    def current_bsp_points(self, model):
        """Return the selected BSP tuple's compiled XYZ in authored order."""
        if not self._ready or self.pending or self._last_error_line is not None:
            return None
        return bsp_plane_points(
            self._source_index, model, self.editor.textCursor().blockNumber())

    def set_polygon_visibility(self, visible):
        """Highlight the selected polygon or vertex across all source lines.

        Polygons use green for visible and salmon for hidden. A selected
        vertex always uses green; it has no BSP polygon visibility state.
        """
        visible = bool(visible) if visible is not None else None
        if self._polygon_visible == visible:
            return
        self._polygon_visible = visible
        self._refresh_extra_selections()

    def _refresh_extra_selections(self):
        lines = []
        if self._last_error_line is not None:
            block = self.editor.document().findBlockByNumber(self._last_error_line - 1)
            if block.isValid():
                item = QTextEdit.ExtraSelection()
                item.format.setBackground(QColor(self.colors['source_error_background']))
                item.format.setForeground(QColor(self.colors['source_highlight_text']))
                item.format.setProperty(
                    QTextCharFormat.Property.FullWidthSelection, True)
                item.cursor = QTextCursor(block)
                lines.append(item)
        if self._polygon_visible is not None and self.current_target() is not None:
            target = self._source_index.target_at_line(
                self.editor.textCursor().blockNumber())
            if target is not None and target.kind in ("polygon", "vertex"):
                color = self.colors['source_visible_background'
                                    if target.kind == "vertex" or
                                    self._polygon_visible
                                    else 'source_hidden_background']
                for line in range(target.first_line, target.last_line + 1):
                    block = self.editor.document().findBlockByNumber(line)
                    if not block.isValid():
                        continue
                    item = QTextEdit.ExtraSelection()
                    item.format.setBackground(QColor(color))
                    item.format.setForeground(QColor(self.colors['source_highlight_text']))
                    item.format.setProperty(
                        QTextCharFormat.Property.FullWidthSelection, True)
                    item.cursor = QTextCursor(block)
                    lines.append(item)
        self.editor.setExtraSelections(lines)
        self.filtered_model.set_inspection(
            self.editor.textCursor().blockNumber(), self._polygon_visible)

    def _emit_cursor_target(self):
        if self._setting:
            return
        target = self.current_target()
        if target != self._last_cursor_target:
            self._last_cursor_target = target
            self._polygon_visible = None
            self._refresh_extra_selections()
            self.cursorTargetChanged.emit(target)

    def _filter_menu_opening(self):
        self._ensure_filter_entries()
        for category, checkbox in self._filter_checks.items():
            checkbox.setText(f"{category} ({self._filter_counts[category]:,})")

    def _ensure_filter_entries(self):
        if self._filter_cache_revision == self.revision:
            return
        self._filter_entries = index_source_entries(self.editor.toPlainText())
        self._filter_counts = dict.fromkeys(CATEGORIES, 0)
        for entry in self._filter_entries:
            self._filter_counts[entry.category] += 1
        self._filter_cache_revision = self.revision

    def _set_selected_filters(self, selected, *, clear_distance=False):
        self._filter_sync = True
        try:
            for category, box in self._filter_checks.items():
                box.setChecked(category in selected)
            if clear_distance:
                self.current_distance_only.setChecked(False)
        finally:
            self._filter_sync = False
        self._apply_filters()

    def _show_all_filters(self):
        self.filter_search.clear()
        self._set_selected_filters(set(CATEGORIES), clear_distance=True)

    def _hide_all_filters(self):
        self._set_selected_filters(set())

    def _only_filter(self, category):
        self._set_selected_filters({category})

    def _filters_changed(self, *_):
        if not self._filter_sync:
            self._apply_filters()

    def set_distance_filter_context(self, model, distance, camera):
        """Update the LOD filter from the committed renderer model and camera."""
        camera = tuple(camera) if camera is not None else (0.0, 0.0, 0.0)
        # Manual and all-LOD choices do not depend on camera position.
        # Avoid rebuilding thousands of filter rows during orbit/pan.
        if distance != "auto":
            camera = (0.0, 0.0, 0.0)
        if (model is self._distance_model and
                distance == self._distance_mode and camera == self._distance_eye):
            return
        changed = model is not self._distance_model
        self._distance_model = model
        self._distance_mode = distance
        self._distance_eye = camera
        self._distance_labels_key = None
        if changed:
            self._distance_dependencies_key = None
        if self.current_distance_only.isChecked():
            self._apply_filters()

    def _active_labels_at_distance(self):
        model = self._distance_model
        if model is None:
            return None
        # Deriving source-space plane vertex references is independent of
        # camera/distance; cache it through consecutive slider movements.
        dependency_key = (id(model), self.revision)
        if self._distance_dependencies_key != dependency_key:
            self._ensure_filter_entries()
            self._distance_dependencies = plane_vertex_dependencies(
                self.editor.toPlainText(), model, self._filter_entries)
            self._distance_dependencies_key = dependency_key
        key = (dependency_key, self._distance_mode, self._distance_eye)
        if key != self._distance_labels_key:
            self._distance_labels = active_source_labels(
                model, self._distance_mode, self._distance_eye,
                self._distance_dependencies)
            self._distance_labels_key = key
        return self._distance_labels

    def _apply_filters(self, *_):
        if self._filter_sync or self._filtered_edit_active:
            return
        if self.filtered_list.state() == QAbstractItemView.State.EditingState:
            # Do not discard a still-open inline editor on a camera update.
            # The delegate's closeEditor event reapplies the current filter.
            return
        chosen = {c for c, checkbox in self._filter_checks.items()
                  if checkbox.isChecked()}
        query = self.filter_search.text().strip().casefold()
        count = len(chosen)
        active_only = self.current_distance_only.isChecked()
        suffix = " · Active LOD" if active_only else ""
        self.filter_button.setText(
            ("Filter statements (all)" if count == len(CATEGORIES) else
             f"Filter statements ({count}/{len(CATEGORIES)})") + suffix)
        if count == len(CATEGORIES) and not query and not active_only:
            self.source_stack.setCurrentWidget(self.editor)
            self.filter_status.setText("All source lines shown")
            self._update_syntax_help()
            return
        self._ensure_filter_entries()
        active_names = self._active_labels_at_distance() if active_only else None
        # While a source edit awaits compilation, retain its original row
        # even if its renamed label is not in the last validated model.
        edited_line = self._active_edit_line if self.pending else None
        matching = [
            entry for entry in self._filter_entries
            if (entry.category in chosen or
                (entry.category == "MATERIAL" and "POLY" in chosen and
                 (self._source_index.at_line(entry.first_line) or
                  (None, None))[0] == "polygon")) and
            (not query or query in entry.preview.casefold()) and
            (not active_only or active_names is None or
             (entry.category != "Comments (%)" and
              entry_is_active(entry, active_names)) or
             (edited_line is not None and
              entry.first_line <= edited_line <= entry.last_line))
        ]
        previous_line = (self._filter_return_line if
                         self._filter_return_line is not None else
                         self.editor.textCursor().blockNumber())
        self._filter_return_line = None
        self.filtered_model.set_entries(matching)
        self.source_stack.setCurrentWidget(self.filtered_page)
        note = (" · waiting for model" if active_only and active_names is None
                else " · last valid model" if active_only and self.pending
                else "")
        self.filter_status.setText(
            f"{len(matching):,}/{len(self._filter_entries):,} statements{note}")
        if matching:
            # Preserve the just-edited row (or select the nearest remaining
            # row if its text/category no longer satisfies the active filter).
            row = next((i for i, entry in enumerate(matching)
                        if entry.first_line <= previous_line <= entry.last_line),
                       None)
            if row is None:
                row = next((i for i, entry in enumerate(matching)
                            if entry.first_line >= previous_line), None)
            if row is not None:
                self.filtered_list.setCurrentIndex(self.filtered_model.index(row))
        else:
            self.filtered_list.clearSelection()
        self._update_syntax_help()

    def _filtered_statement_text(self, entry):
        document = self.editor.document()
        first = document.findBlockByNumber(entry.first_line)
        last = document.findBlockByNumber(entry.last_line)
        if not first.isValid() or not last.isValid():
            return ""
        cursor = QTextCursor(document)
        cursor.setPosition(first.position())
        cursor.setPosition(last.position() + len(last.text()),
                           QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace("\u2029", "\n")

    def _replace_filtered_statement(self, entry, text):
        """Replace only a bounded visible declaration in the real source.

        Preserve hidden comments/definitions even when several categories
        are excluded. The original QTextDocument retains undo and is the
        only source for compilation, renaming, saving and export.
        """
        if not self._ready or self._filter_cache_revision != self.revision:
            return False
        original = self._filtered_statement_text(entry)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text == original:
            return True
        document = self.editor.document()
        first = document.findBlockByNumber(entry.first_line)
        last = document.findBlockByNumber(entry.last_line)
        if not first.isValid() or not last.isValid():
            return False
        self._filter_return_line = entry.first_line
        self._active_edit_line = entry.first_line
        self._filtered_edit_active = True
        try:
            # Position the canonical caret for automatic pointer rename and
            # source-target inspection before applying the change.
            self.editor.setTextCursor(QTextCursor(first))
            cursor = QTextCursor(document)
            cursor.beginEditBlock()
            cursor.setPosition(first.position())
            cursor.setPosition(last.position() + len(last.text()),
                               QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(text)
            cursor.endEditBlock()
        finally:
            self._filtered_edit_active = False
        # A QTextCursor replacement can emit intermediate textChanged signals
        # (deleting the old multiline statement before inserting the new).
        # Track a declaration-label rename from complete before/after text,
        # not those intermediate snapshots, so references in filtered-out
        # LIST/FACE/SWITCH statements are updated as normal.
        old_label = edited_declaration_label(original, text, 0)
        if old_label is not None and self.auto_rename.isChecked():
            self._rename_pending = (entry.first_line, old_label)
            self._rename_timer.start()
        self._rename_snapshot = self.editor.toPlainText()
        # Rebuild after the delegate has closed; a synchronous model reset
        # inside setModelData would destroy its active editing widget.
        QTimer.singleShot(0, self._apply_filters)
        return True

    def _inspect_filtered_entry(self, index, *_):
        if not index.isValid():
            return
        entry = self.filtered_model.entries[index.row()]
        block = self.editor.document().findBlockByNumber(entry.first_line)
        if block.isValid():
            self.editor.setTextCursor(QTextCursor(block))
            self._cursor_changed()
            self._update_syntax_help()

    def _edit_filtered_entry(self, index=None):
        if index is None or not hasattr(index, "isValid"):
            index = self.filtered_list.currentIndex()
        line = None
        if index.isValid() and index.row() < len(self.filtered_model.entries):
            line = self.filtered_model.entries[index.row()].first_line
        self._show_all_filters()
        if line is not None:
            block = self.editor.document().findBlockByNumber(line)
            if block.isValid():
                self.editor.setTextCursor(QTextCursor(block))
                self.editor.centerCursor()
        self.editor.setFocus()

    def _selected_pointer_line(self):
        """Resolve a visible filtered row or any line in a source declaration.

        For multiline statements, F2 targets the header label even when the
        cursor is on a continuation row. A comment or header is not renameable.
        """
        if self.source_stack.currentWidget() is self.filtered_page:
            index = self.filtered_list.currentIndex()
            if not index.isValid() or index.row() >= len(self.filtered_model.entries):
                return None
            return self.filtered_model.entries[index.row()].first_line
        self._ensure_filter_entries()
        line = self.editor.textCursor().blockNumber()
        starts = [entry.first_line for entry in self._filter_entries]
        row = bisect_right(starts, line) - 1
        if row < 0 or line > self._filter_entries[row].last_line:
            return None
        return self._filter_entries[row].first_line

    def _apply_pointer_rename(self, line, new_name):
        """Atomically rename just one label and optional exact references."""
        source = self.editor.toPlainText()
        old, edits = plan_pointer_rename(
            source, line, new_name,
            update_references=self.auto_rename.isChecked())
        if not edits:
            return 0

        self._rename_timer.stop()
        self._rename_pending = None
        self._filter_return_line = line
        self._active_edit_line = line
        # The rename planner's spans use original Python code-point offsets;
        # exclude only the declaration token from reference-level history.
        rows = source.splitlines(keepends=True)
        name_match = DECLARATION.match(rows[line])
        declaration_start = (sum(len(row) for row in rows[:line]) +
                             name_match.start("name"))
        reference_edits = [(start, end) for start, end, _ in edits
                           if start != declaration_start]
        cursor = QTextCursor(self.editor.document())
        self._applying_rename = True
        try:
            cursor.beginEditBlock()
            try:
                # Descending offsets prevent replacement text from shifting
                # the remaining original-document edits. Qt uses UTF-16
                # cursor positions; Python string offsets are code points.
                for start, end, replacement in edits:
                    cursor.setPosition(qt_utf16_offset(source, start))
                    cursor.setPosition(
                        qt_utf16_offset(source, end),
                        QTextCursor.MoveMode.KeepAnchor)
                    cursor.insertText(replacement)
            finally:
                cursor.endEditBlock()
        finally:
            self._applying_rename = False
        self._rename_snapshot = self.editor.toPlainText()
        self._edited()
        updated_references = len(reference_edits)
        self._log_automatic_rename(
            source, old, new_name, reference_edits,
            action="F2 pointer rename", declaration_line=line)
        self.status.setText(
            f'Renamed pointer {old} → {new_name} '
            f'({updated_references} reference(s) updated).'
            + ('' if self.auto_rename.isChecked()
               else ' Auto-rename references is off.'))
        return updated_references

    def rename_selected_pointer(self):
        """F2: prompt for the selected declaration label, not its contents."""
        if not self._ready:
            return
        if (self.source_stack.currentWidget() is self.filtered_page and
                self.filtered_list.state() ==
                QAbstractItemView.State.EditingState):
            self.status.setText(
                'Finish editing the current statement before pressing F2.')
            return
        line = self._selected_pointer_line()
        old = (declaration_label(self.editor.toPlainText(), line)
               if line is not None else None)
        if old is None:
            self.status.setText('Select a named N3 declaration to rename with F2.')
            return
        new, accepted = QInputDialog.getText(
            self, 'Rename N3 pointer', f'New name for {old}:',
            QLineEdit.EchoMode.Normal, old)
        if not accepted or new == old:
            return
        try:
            self._apply_pointer_rename(line, new)
        except ValueError as exc:
            QMessageBox.warning(self, 'Cannot rename N3 pointer', str(exc))

    def _auto_rename_toggled(self, enabled):
        if not enabled:
            self._rename_timer.stop()
            self._rename_pending = None

    def _track_symbol_edit(self):
        current = self.editor.toPlainText()
        previous = self._rename_snapshot
        self._rename_snapshot = current
        if not self.auto_rename.isChecked():
            return
        line = self.editor.textCursor().blockNumber()
        old = edited_declaration_label(previous, current, line)
        if old is not None:
            if self._rename_pending is None or self._rename_pending[0] != line:
                self._rename_pending = (line, old)
        pending = self._rename_pending
        if pending is not None:
            label = declaration_label(current, pending[0])
            if label and label != pending[1]:
                self._rename_timer.start()
            elif label == pending[1]:
                self._rename_timer.stop()
                self._rename_pending = None

    def _commit_pending_rename(self):
        pending = self._rename_pending
        self._rename_pending = None
        if not self.auto_rename.isChecked() or pending is None or not self._ready:
            return
        line, original = pending
        source = self.editor.toPlainText()
        updated = declaration_label(source, line)
        if not updated or updated == original:
            return
        replacements = reference_spans(source, original, updated)
        if not replacements:
            return
        # Join the user's declaration edit and the dependent references in
        # one Qt undo command when possible. Replace from right to left so
        # the earlier spans never shift as later references change length.
        cursor = QTextCursor(self.editor.document())
        self._applying_rename = True
        try:
            cursor.joinPreviousEditBlock()
            for start, end in reversed(replacements):
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cursor.insertText(updated)
            cursor.endEditBlock()
        finally:
            self._applying_rename = False
        self._rename_snapshot = self.editor.toPlainText()
        self._edited()
        self._log_automatic_rename(
            source, original, updated, replacements,
            action="Auto-rename references", declaration_line=line)
        self.status.setText(
            f'Renamed {original} → {updated} in {len(replacements)} reference(s); '
            'validating source…')

    def _cursor_changed(self):
        cursor = self.editor.textCursor()
        self.position.setText(
            f'Line {cursor.blockNumber()+1}, column {cursor.positionInBlock()+1}')
        self._emit_cursor_target()
        self.filtered_model.set_inspection(
            cursor.blockNumber(), self._polygon_visible)
        self._update_syntax_help()
