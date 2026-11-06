"""System tray icon with a Show/Hide + Exit menu.

Like the other views it is passive: it emits signals and lets the
controller decide what showing, hiding and exiting mean.
"""

from importlib import resources

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

TOOLTIP = "vt-tunnel"
SHOW_TEXT = "Show"
HIDE_TEXT = "Hide"
EXIT_TEXT = "Exit"

# Shipped inside the package, so it is found both in a source checkout and
# when installed (wheel or .deb).
ICON_RESOURCE = ("resources", "tray.png")


def load_icon() -> QIcon:
    """Load the tray icon from the package resources."""
    data = resources.files("vt_tunnel_gui").joinpath(*ICON_RESOURCE)
    pixmap = QPixmap()
    if not pixmap.loadFromData(data.read_bytes()):
        raise RuntimeError(f"Can't load tray icon {'/'.join(ICON_RESOURCE)}")
    return QIcon(pixmap)


class TrayView(QSystemTrayIcon):
    """Tray icon whose menu toggles the main window and exits the app.

    Emits ``show_hide_requested()`` from the Show/Hide menu item or a
    click on the icon, and ``exit_requested()`` from Exit. The controller
    keeps the Show/Hide label in sync via :meth:`set_window_visible`.
    """

    show_hide_requested = pyqtSignal()
    exit_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(load_icon(), parent)
        self.setToolTip(TOOLTIP)

        # setContextMenu() doesn't take ownership: keep the menu alive here.
        self._menu = QMenu()
        self.show_hide_action = self._menu.addAction(SHOW_TEXT)
        self._menu.addSeparator()
        self.exit_action = self._menu.addAction(EXIT_TEXT)
        self.show_hide_action.triggered.connect(self.show_hide_requested)
        self.exit_action.triggered.connect(self.exit_requested)
        self.setContextMenu(self._menu)

        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A plain (left) click toggles too; the right click opens the menu.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_hide_requested.emit()

    def set_window_visible(self, visible: bool) -> None:
        """Label the menu item for what it will do to the main window."""
        self.show_hide_action.setText(HIDE_TEXT if visible else SHOW_TEXT)
