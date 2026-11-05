"""Main window: the list of connections.

Each row shows the connection's enabled state (checkbox) and name.
Clicking a row asks the controller to open it for editing; the view does
not decide what happens.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
)

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.views.connection_view import is_true

UNNAMED = "(unnamed)"


class MainWindow(QMainWindow):
    """Lists the connections; emits ``connection_activated(row)``."""

    connection_activated = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("vt-tunnel")
        self.resize(360, 240)

        self.connection_list = QListWidget()
        # Single click (or Enter / double click) opens the connection.
        self.connection_list.itemClicked.connect(self._emit_activated)
        self.connection_list.itemActivated.connect(self._emit_activated)
        self.setCentralWidget(self.connection_list)

    def _emit_activated(self, item: QListWidgetItem) -> None:
        self.connection_activated.emit(self.connection_list.row(item))

    def set_connections(self, connections: list[dict[str, str]]) -> None:
        """Show one row per connection (a dict of its config values)."""
        self.connection_list.clear()
        for values in connections:
            name = values.get(config_schema.NAME.key, "")
            item = QListWidgetItem(name or UNNAMED)
            # Checkbox shows ENABLED; it is display-only (not user-checkable)
            # — editing happens in the connection window.
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            enabled = is_true(values.get(config_schema.ENABLED.key, ""))
            item.setCheckState(
                Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
            )
            item.setToolTip("Click to edit")
            self.connection_list.addItem(item)
