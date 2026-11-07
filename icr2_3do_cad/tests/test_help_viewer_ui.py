"""Qt smoke tests for the native, offline Contents/Index/Search Help window."""
import os
import sys
import unittest
from pathlib import Path


HAS_DISPLAY = bool(
    os.environ.get("DISPLAY")
    or os.environ.get("WAYLAND_DISPLAY")
    or sys.platform in ("win32", "darwin")
)
MANUAL = Path(__file__).resolve().parents[1] / "USER_MANUAL.html"


@unittest.skipUnless(HAS_DISPLAY, "Requires desktop Qt or xvfb-run")
class NativeHelpWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtWidgets import QApplication
            from help_viewer import HelpWindow
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"Qt requirements unavailable: {error}")
        cls.QUrl = QUrl
        cls.HelpWindow = HelpWindow
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = self.HelpWindow(MANUAL)

    def tearDown(self):
        self.window.close()

    def test_native_controls_contents_index_and_history(self):
        self.assertEqual(self.window.navigation.count(), 3)
        self.assertEqual(
            [self.window.navigation.tabText(i) for i in range(3)],
            ["Contents", "Index", "Search"],
        )
        self.assertGreaterEqual(self.window.contents_list.count(), 15)
        self.assertEqual(self.window.history, ["welcome"])
        self.assertFalse(self.window.back_button.isEnabled())
        self.window.show_topic("editing")
        self.assertEqual(self.window.history, ["welcome", "editing"])
        self.assertTrue(self.window.back_button.isEnabled())
        self.window.go_back()
        self.assertEqual(
            self.window.history[self.window.history_position], "welcome"
        )
        self.assertTrue(self.window.forward_button.isEnabled())
        self.window.go_forward()
        self.assertEqual(
            self.window.history[self.window.history_position], "editing"
        )
        self.window.go_home()
        self.assertEqual(
            self.window.history[self.window.history_position], "welcome"
        )
        self.assertGreater(self.window.index_list.topLevelItemCount(), 5)

    def test_internal_links_work_and_external_links_are_ignored(self):
        self.window._link_clicked(self.QUrl("#files"))
        self.assertEqual(
            self.window.history[self.window.history_position], "files"
        )
        history = list(self.window.history)
        self.window._link_clicked(self.QUrl("https://example.com/manual"))
        self.assertEqual(self.window.history, history)
        self.window._link_clicked(self.QUrl("#contents"))
        self.assertEqual(self.window.navigation.currentIndex(), 0)

    def test_live_full_text_search_finds_topics_and_navigates(self):
        self.window.focus_search()
        self.assertEqual(self.window.navigation.currentIndex(), 2)
        self.window.search_edit.setText("polygon")
        self.assertGreater(self.window.search_results.count(), 0)
        result = self.window.search_results.item(0)
        target = result.data(self._user_role())
        self.window._search_selected(result)
        self.assertEqual(
            self.window.history[self.window.history_position], target
        )
        self.window.search_edit.setText("no-such-unlikely-string-zz999")
        self.assertEqual(self.window.search_results.count(), 0)
        self.window.search_edit.clear()
        self.assertEqual(self.window.result_count.text(), "Enter a search term.")

    @staticmethod
    def _user_role():
        from PySide6.QtCore import Qt
        return Qt.ItemDataRole.UserRole


if __name__ == "__main__":
    unittest.main()
