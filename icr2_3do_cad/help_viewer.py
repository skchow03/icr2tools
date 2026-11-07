"""Fast, native Qt Help viewer for the ICR2 3DO CAD editor.

Classic WinHelp navigation (Contents / Index / Search, Back / Forward / Home)
using ordinary PySide6 widgets. No browser process, WebEngine, JavaScript,
HTTP requests, or second QApplication is involved.
"""
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTabWidget, QTextBrowser, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from help_content import read_manual


class HelpWindow(QDialog):
    """Reusable, nonmodal help window owned by the CAD main window."""

    def __init__(self, manual_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ICR2 3DO CAD Help")
        self.setMinimumSize(680, 420)
        self.resize(1040, 700)

        self.topics, self.index_entries = read_manual(Path(manual_path))
        self.topic_by_id = {topic.topic_id: topic for topic in self.topics}
        self.topic_order = [topic.topic_id for topic in self.topics]
        self.history = []
        self.history_position = -1

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(7, 7, 7, 7)
        main_layout.setSpacing(6)

        toolbar = QHBoxLayout()
        self.back_button = QPushButton("◀  &Back")
        self.forward_button = QPushButton("&Forward  ▶")
        self.home_button = QPushButton("&Home")
        self.search_button = QPushButton("&Search")
        self.print_button = QPushButton("&Print…")
        self.close_button = QPushButton("&Close")
        for button in (
            self.back_button, self.forward_button, self.home_button,
            self.search_button, self.print_button,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.close_button)
        main_layout.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.navigation = QTabWidget(self.splitter)
        self.navigation.setDocumentMode(False)

        self.contents_list = QListWidget(self.navigation)
        self.contents_list.setAlternatingRowColors(True)
        for topic in self.topics:
            item = QListWidgetItem(topic.title)
            item.setData(Qt.ItemDataRole.UserRole, topic.topic_id)
            self.contents_list.addItem(item)
        self.navigation.addTab(self.contents_list, "Contents")

        self.index_list = QTreeWidget(self.navigation)
        self.index_list.setHeaderHidden(True)
        self.index_list.setUniformRowHeights(True)
        groups = {}
        for initial, title, target in self.index_entries:
            if initial not in groups:
                groups[initial] = QTreeWidgetItem([initial])
                self.index_list.addTopLevelItem(groups[initial])
            entry = QTreeWidgetItem([title])
            entry.setData(0, Qt.ItemDataRole.UserRole, target)
            groups[initial].addChild(entry)
        self.index_list.expandAll()
        self.navigation.addTab(self.index_list, "Index")

        search_panel = QWidget(self.navigation)
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(5, 5, 5, 5)
        search_layout.addWidget(QLabel("Search for words in the Help topics:"))
        self.search_edit = QLineEdit(search_panel)
        self.search_edit.setPlaceholderText("Type a word or phrase")
        self.search_edit.setClearButtonEnabled(True)
        search_layout.addWidget(self.search_edit)
        self.search_results = QListWidget(search_panel)
        search_layout.addWidget(self.search_results)
        self.result_count = QLabel("Enter a search term.")
        search_layout.addWidget(self.result_count)
        self.navigation.addTab(search_panel, "Search")

        self.browser = QTextBrowser(self.splitter)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setReadOnly(True)
        self.browser.document().setDefaultStyleSheet(
            "body { font-family: 'Segoe UI', Tahoma, Arial; font-size: 10pt; }"
            "h1 { color: #000080; font-size: 19pt; }"
            "h2 { color: #000080; font-size: 16pt; }"
            "h3 { color: #202050; font-size: 12pt; }"
            "a { color: #000080; text-decoration: underline; }"
            "table { border-collapse: collapse; }"
            "th { background-color: #dddddd; font-weight: bold; }"
            "td, th { padding: 5px; }"
            ".note { background-color: #ffffdf; }"
            ".warning { background-color: #fff0e4; }"
            "pre, code { font-family: Consolas, 'Courier New', monospace; }"
        )
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([275, 765])
        main_layout.addWidget(self.splitter, 1)

        self.status = QLabel("")
        self.status.setMinimumHeight(19)
        main_layout.addWidget(self.status)

        self.contents_list.currentRowChanged.connect(self._contents_selected)
        self.index_list.itemSelectionChanged.connect(self._index_selected)
        self.search_edit.textChanged.connect(self._update_search)
        self.search_edit.returnPressed.connect(self._first_search_result)
        self.search_results.itemActivated.connect(self._search_selected)
        self.search_results.itemClicked.connect(self._search_selected)
        self.browser.anchorClicked.connect(self._link_clicked)

        self.back_button.clicked.connect(self.go_back)
        self.forward_button.clicked.connect(self.go_forward)
        self.home_button.clicked.connect(self.go_home)
        self.search_button.clicked.connect(self.focus_search)
        self.print_button.clicked.connect(self.print_topic)
        self.close_button.clicked.connect(self.close)

        self._shortcuts = []
        for key, handler in (
            ("Alt+Left", self.go_back),
            ("Alt+Right", self.go_forward),
            ("Ctrl+F", self.focus_search),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

        geometry = QSettings("ICR2Tools", "3DOCAD").value("help_window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.show_topic("welcome")

    def show_topic(self, topic_id, *, add_history=True, highlight=""):
        """Show a topic and optionally record a step in the browser-like history."""
        if topic_id not in self.topic_by_id:
            return False
        if add_history and (
            self.history_position < 0
            or self.history[self.history_position] != topic_id
        ):
            self.history = self.history[: self.history_position + 1]
            self.history.append(topic_id)
            self.history_position = len(self.history) - 1
        topic = self.topic_by_id[topic_id]
        self.browser.setHtml(topic.html)
        self.browser.moveCursor(QTextCursor.MoveOperation.Start)
        if highlight:
            self.browser.find(highlight)
        self.contents_list.blockSignals(True)
        self.contents_list.setCurrentRow(self.topic_order.index(topic_id))
        self.contents_list.blockSignals(False)
        self.status.setText(
            f"{topic.title}    •    Topic {self.topic_order.index(topic_id) + 1}"
            f" of {len(self.topic_order)}    •    Offline Help"
        )
        self.back_button.setEnabled(self.history_position > 0)
        self.forward_button.setEnabled(
            self.history_position + 1 < len(self.history)
        )
        return True

    def go_back(self):
        if self.history_position > 0:
            self.history_position -= 1
            self.show_topic(self.history[self.history_position], add_history=False)

    def go_forward(self):
        if self.history_position + 1 < len(self.history):
            self.history_position += 1
            self.show_topic(self.history[self.history_position], add_history=False)

    def go_home(self):
        self.show_topic("welcome")

    def focus_search(self):
        self.navigation.setCurrentIndex(2)
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _contents_selected(self, row):
        if row >= 0:
            item = self.contents_list.item(row)
            if item is not None:
                self.show_topic(item.data(Qt.ItemDataRole.UserRole))

    def _index_selected(self):
        for item in self.index_list.selectedItems():
            target = item.data(0, Qt.ItemDataRole.UserRole)
            if target:
                self.show_topic(target)
                return

    def _update_search(self, query):
        """Search all help topics locally as the user types."""
        self.search_results.clear()
        words = query.casefold().split()
        if not words:
            self.result_count.setText("Enter a search term.")
            return
        count = 0
        for topic in self.topics:
            lowered = topic.text.casefold()
            if not all(word in lowered for word in words):
                continue
            hit = lowered.find(words[0])
            start = max(0, hit - 42)
            end = min(len(topic.text), hit + 92)
            excerpt = topic.text[start:end]
            if start:
                excerpt = "…" + excerpt
            if end < len(topic.text):
                excerpt += "…"
            item = QListWidgetItem(f"{topic.title}\n{excerpt}")
            item.setData(Qt.ItemDataRole.UserRole, topic.topic_id)
            item.setToolTip(topic.title)
            self.search_results.addItem(item)
            count += 1
        self.result_count.setText(f"{count} topic{'s' if count != 1 else ''} found.")

    def _first_search_result(self):
        if self.search_results.count():
            self._search_selected(self.search_results.item(0))

    def _search_selected(self, item):
        if item is not None:
            self.show_topic(
                item.data(Qt.ItemDataRole.UserRole),
                highlight=self.search_edit.text().split()[0]
                if self.search_edit.text().strip() else "",
            )

    def _link_clicked(self, url):
        """Follow only internal anchors; never open a URL in an external browser."""
        if url.scheme() or url.host():
            return
        target = url.fragment()
        if target == "contents":
            self.navigation.setCurrentIndex(0)
            self.contents_list.setFocus()
        elif target in self.topic_by_id:
            self.show_topic(target)

    def print_topic(self):
        """Print the visible topic through the operating system's print dialog."""
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.browser.print_(printer)

    def closeEvent(self, event):
        QSettings("ICR2Tools", "3DOCAD").setValue(
            "help_window_geometry", self.saveGeometry()
        )
        super().closeEvent(event)
