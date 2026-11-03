"""Stub main window for vt-tunnel-gui."""

import sys

from PyQt6.QtWidgets import QApplication, QMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("vt-tunnel")
    window.show()
    return app.exec()
