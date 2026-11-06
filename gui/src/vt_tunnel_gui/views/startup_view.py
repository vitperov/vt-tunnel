"""Dialogs shown before the main window: the config directory check."""

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

TITLE = "vt-tunnel"


def ask_create_config_dir(path: Path) -> bool:
    """Ask whether to create the missing config directory ``path``."""
    answer = QMessageBox.question(
        None,
        TITLE,
        f"The connections directory {path} does not exist.\n\n"
        "Create it? Without it vt-tunnel-gui can't run and will exit.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return answer == QMessageBox.StandardButton.Yes


def show_startup_error(text: str) -> None:
    """Tell the user why the app can't start (it exits afterwards)."""
    QMessageBox.critical(None, TITLE, text)
