import sys

from PyQt6.QtWidgets import QApplication

from vt_tunnel_gui.controller import Controller
from vt_tunnel_gui.models.model import Model
from vt_tunnel_gui.views.view import MainWindow


def main() -> int:
    """Composition root: build the model, view and controller, then run."""
    app = QApplication(sys.argv)
    model = Model()
    view = MainWindow()
    controller = Controller(model, view)
    controller.show()
    return app.exec()
