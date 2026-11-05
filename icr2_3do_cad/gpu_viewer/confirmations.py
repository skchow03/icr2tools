"""Unambiguous, cancel-by-default confirmations for destructive viewer actions.

Qt's QMessageBox.question uses Yes/No by default; the meaning of "Yes"
depends on the dialog text. Use explicit action labels instead, and make
Cancel the keyboard default and Esc/window-close outcome.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def confirm_destructive_action(parent, title, message, action_label):
    """Return True only after the user clicks the named destructive action.

    Enter defaults to Cancel. Escape, clicking the window close button and
    programmatic rejection are all conservative: no source data is lost.
    """
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setWindowTitle(title)
    dialog.setText(message)
    action_button = dialog.addButton(
        action_label, QMessageBox.ButtonRole.DestructiveRole)
    cancel_button = dialog.addButton(QMessageBox.StandardButton.Cancel)
    dialog.setDefaultButton(cancel_button)
    dialog.setEscapeButton(cancel_button)
    dialog.exec()
    return dialog.clickedButton() is action_button
