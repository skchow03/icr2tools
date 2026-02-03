from __future__ import annotations

import logging

from PyQt5 import QtCore, QtWidgets


class LogMessageEmitter(QtCore.QObject):
    message_emitted = QtCore.pyqtSignal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogMessageEmitter) -> None:
        super().__init__()
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self._emitter.message_emitted.emit(message)


class LogViewerWindow(QtWidgets.QDialog):
    """Displays logging output in a scrollable window."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SG Viewer Logs")
        self.resize(760, 420)

        self._text = QtWidgets.QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)

        self._clear_button = QtWidgets.QPushButton("Clear")
        self._clear_button.clicked.connect(self._text.clear)
        self._copy_button = QtWidgets.QPushButton("Copy All")
        self._copy_button.clicked.connect(self._copy_all)
        self._close_button = QtWidgets.QPushButton("Close")
        self._close_button.clicked.connect(self.close)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._clear_button)
        button_row.addWidget(self._copy_button)
        button_row.addWidget(self._close_button)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._text)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self._emitter = LogMessageEmitter()
        self._emitter.message_emitted.connect(self._append_message)
        self._handler = QtLogHandler(self._emitter)
        self._handler.setLevel(logging.DEBUG)
        self._handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        self._handler_installed = False

    def attach_to_logger(self, logger: logging.Logger) -> None:
        if self._handler_installed:
            return
        logger.addHandler(self._handler)
        self._handler_installed = True

    def detach_from_logger(self, logger: logging.Logger) -> None:
        if not self._handler_installed:
            return
        logger.removeHandler(self._handler)
        self._handler_installed = False

    def closeEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802
        self.detach_from_logger(logging.getLogger())
        super().closeEvent(event)

    def _append_message(self, message: str) -> None:
        self._text.appendPlainText(message)
        self._text.moveCursor(QtWidgets.QTextCursor.End)

    def _copy_all(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self._text.toPlainText())
