"""Qt N3 source pane mirroring CPU SourceEditor semantics.

The editor owns text and revision numbers but never touches the OpenGL
context. The Window debounces/schedules worker compilation, discards stale
results and keeps the last valid mesh on compilation failure.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from gpu_viewer.source_inspection import index_source_targets
from gpu_viewer.source_rename import (
    edited_declaration_label, declaration_label, reference_spans,
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
        colors = dict(comment='#6da285', string='#dfb17f',
                      keyword='#91b8f4', label='#e7d38e')
        self.formats = {}
        for name, color in colors.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self.formats[name] = fmt

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


class SourcePane(QWidget):
    compileRequested = Signal(int, str)
    saveRequested = Signal()
    exportRequested = Signal()
    cursorTargetChanged = Signal(object)  # None or (kind, authored_label)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.highlighter = N3Highlighter(self.editor.document())
        self.editor.textChanged.connect(self._edited)
        self.editor.cursorPositionChanged.connect(self._cursor_changed)
        layout.addWidget(self.editor, 1)
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

    def set_source(self, text, path, *, status=None):
        self._debounce.stop()
        self._rename_timer.stop()
        self._rename_pending = None
        self._polygon_visible = None
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
        self._source_index = index_source_targets(normalized)
        self._cursor_changed()

    def reset(self, status='Open the Source tab to generate editable N3.'):
        self._debounce.stop()
        self._rename_timer.stop()
        self._rename_pending = None
        self._polygon_visible = None
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
        self._cursor_changed()

    def _edited(self):
        if self._setting or not self._ready:
            return
        if self._applying_rename:
            return
        self._track_symbol_edit()
        self.revision += 1
        self._last_error_line = None
        self._polygon_visible = None
        self._refresh_extra_selections()
        self.status.setText('Editing… last valid GPU preview retained until compilation succeeds.')
        self._debounce.start()
        self._emit_cursor_target()

    def apply_now(self):
        if not self._ready:
            return
        self._debounce.stop()
        if not self.pending:
            return
        self.status.setText('Compiling N3 and rebuilding GPU preview…')
        self.compileRequested.emit(self.revision, self.get_source())

    def mark_valid(self, revision, model):
        if revision != self.revision:
            return
        self.applied_revision = revision
        self._last_error_line = None
        self._polygon_visible = None
        self._refresh_extra_selections()
        self._source_index = index_source_targets(self.editor.toPlainText())
        self.status.setText(
            f'Valid N3: {len(model.vertices):,} vertices, '
            f'{len(model.polygons):,} polygons. GPU preview updated (unsaved).')
        self._emit_cursor_target()

    def mark_error(self, revision, error):
        if revision != self.revision:
            return
        self.applied_revision = revision
        line = find_error_line(self.get_source(), error)
        self._last_error_line = line
        block = self.editor.document().findBlockByNumber(line-1)
        if block.isValid():
            selected = QTextEdit.ExtraSelection()
            selected.format.setBackground(QColor('#5b2632'))
            selected.format.setProperty(
                QTextCharFormat.Property.FullWidthSelection, True)
            selected.cursor = QTextCursor(block)
            self.editor.setExtraSelections([selected])
        self._polygon_visible = None
        self.status.setText(f'Line {line}: {error}. Last valid GPU preview retained.')
        self._emit_cursor_target()

    def goto_error(self):
        if not self._last_error_line:
            return
        block = self.editor.document().findBlockByNumber(self._last_error_line-1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()
            self.editor.setFocus()

    def current_target(self):
        """Return a declaration only when its source matches the compiled model."""
        if not self._ready or self.pending or self._last_error_line is not None:
            return None
        return self._source_index.at_line(self.editor.textCursor().blockNumber())

    def set_polygon_visibility(self, visible):
        """Color the selected POLY declaration green/salmon, including continuations."""
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
                item.format.setBackground(QColor('#5b2632'))
                item.format.setProperty(
                    QTextCharFormat.Property.FullWidthSelection, True)
                item.cursor = QTextCursor(block)
                lines.append(item)
        if self._polygon_visible is not None and self.current_target() is not None:
            target = self._source_index.target_at_line(
                self.editor.textCursor().blockNumber())
            if target is not None and target.kind == "polygon":
                color = '#b5e3bb' if self._polygon_visible else '#f1ada1'
                for line in range(target.first_line, target.last_line + 1):
                    block = self.editor.document().findBlockByNumber(line)
                    if not block.isValid():
                        continue
                    item = QTextEdit.ExtraSelection()
                    item.format.setBackground(QColor(color))
                    item.format.setForeground(QColor('#17221d'))
                    item.format.setProperty(
                        QTextCharFormat.Property.FullWidthSelection, True)
                    item.cursor = QTextCursor(block)
                    lines.append(item)
        self.editor.setExtraSelections(lines)

    def _emit_cursor_target(self):
        if self._setting:
            return
        target = self.current_target()
        if target != self._last_cursor_target:
            self._last_cursor_target = target
            self._polygon_visible = None
            self._refresh_extra_selections()
            self.cursorTargetChanged.emit(target)

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
        self.status.setText(
            f'Renamed {original} → {updated} in {len(replacements)} reference(s); '
            'validating source…')

    def _cursor_changed(self):
        cursor = self.editor.textCursor()
        self.position.setText(
            f'Line {cursor.blockNumber()+1}, column {cursor.positionInBlock()+1}')
        self._emit_cursor_target()
