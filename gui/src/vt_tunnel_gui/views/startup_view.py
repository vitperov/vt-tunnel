"""Startup dialogs: the two parentless helpers the directory gate shows.

The gate runs before any main window exists, so its dialogs are
parentless module-level helpers: a critical-error dialog telling the
user startup cannot proceed, and a yes/no question offering to create
a missing directory (defaulting to Yes). Each is shown and dismissed
the moment the user answers; a fatal answer makes the app exit before
anything else is built.
"""

from PyQt6.QtWidgets import QMessageBox

_TITLE = "vt-tunnel"


def show_critical(message):
    """A parentless critical dialog: startup cannot proceed."""
    QMessageBox.critical(None, _TITLE, message)


def ask_create(message):
    """A parentless yes/no question, defaulting to Yes; True = yes."""
    answer = QMessageBox.question(
        None,
        _TITLE,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return answer == QMessageBox.StandardButton.Yes
