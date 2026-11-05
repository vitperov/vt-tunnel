from PyQt6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Empty main window for vt-tunnel-gui."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("vt-tunnel")
