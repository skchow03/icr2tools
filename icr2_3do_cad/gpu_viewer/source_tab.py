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
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
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

    def reset(self, status='Open the Source tab to generate editable N3.'):
        self._debounce.stop()
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

    def _edited(self):
        if self._setting or not self._ready:
            return
        self.revision += 1
        self._last_error_line = None
        self.editor.setExtraSelections([])
        self.status.setText('Editing… last valid GPU preview retained until compilation succeeds.')
        self._debounce.start()

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
        self.editor.setExtraSelections([])
        self.status.setText(
            f'Valid N3: {len(model.vertices):,} vertices, '
            f'{len(model.polygons):,} polygons. GPU preview updated (unsaved).')

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
        self.status.setText(f'Line {line}: {error}. Last valid GPU preview retained.')

    def goto_error(self):
        if not self._last_error_line:
            return
        block = self.editor.document().findBlockByNumber(self._last_error_line-1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()
            self.editor.setFocus()

    def _cursor_changed(self):
        cursor = self.editor.textCursor()
        self.position.setText(f'Line {cursor.blockNumber()+1}, column {cursor.positionInBlock()+1}')
