"""Main window: the list of connections.

Each row shows a connection's enabled state (checkbox) and name; the row
after the last connection holds the "+" (add) button. Clicking a row asks
the controller to open that connection; the view does not decide what
happens.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
)

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.views.connection_view import is_true

UNNAMED = "(unnamed)"


class MainWindow(QMainWindow):
    """Lists the connections.

    Emits ``connection_activated(row)`` when a connection row is clicked
    and ``add_requested()`` when "+" is pressed.
    """

    connection_activated = pyqtSignal(int)
    add_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("vt-tunnel")
        self.resize(360, 240)

        self._connection_count = 0
        self.add_button: QPushButton | None = None

        self.connection_list = QListWidget()
        # Single click (or Enter / double click) opens the connection.
        self.connection_list.itemClicked.connect(self._on_item_activated)
        self.connection_list.itemActivated.connect(self._on_item_activated)
        self.setCentralWidget(self.connection_list)

        self.set_connections([])

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        row = self.connection_list.row(item)
        if row < self._connection_count:
            self.connection_activated.emit(row)
        else:
            self.add_requested.emit()  # the "+" row, e.g. via keyboard

    def set_connections(self, connections: list[dict[str, str]]) -> None:
        """Show one row per connection (a dict of its config values),
        followed by the "+" row."""
        self.connection_list.clear()
        self._connection_count = len(connections)
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
        self._add_plus_row()

    def _add_plus_row(self) -> None:
        button = QPushButton("+")
        button.setToolTip("Add connection")
        button.clicked.connect(self.add_requested)
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable
        item.setSizeHint(button.sizeHint())
        self.connection_list.addItem(item)
        self.connection_list.setItemWidget(item, button)
        self.add_button = button
