"""Main window: the list of connections.

Each row shows a connection's ENABLED setting (display-only checkbox),
its name and a summary, and has "Check daemon" and "Edit" buttons; an
"Add connection" button sits below the list. Clicking a row also edits
it. The view only emits signals; the controller decides what
happens.
"""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QGuiApplication,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QPaintEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.daemon_check import DaemonResult
from vt_tunnel_gui.views.check_result_view import daemon_result_view
from vt_tunnel_gui.views.connection_view import is_true

UNNAMED = "(unnamed)"
EMPTY_TEXT = "No connections yet."
CHECK_DAEMON_TEXT = "Check daemon"
CHECKING_TEXT = "Checking..."
ENABLED_TOOLTIP = (
    "ENABLED in the config file. The daemon doesn't use it yet: "
    "\u201cCheck daemon\u201d shows whether the service is enabled in "
    "systemd."
)

WINDOW_MARGIN = 12  # between the content and the window border
ROW_SPACING = 4  # between connection rows
INITIAL_SIZE = (620, 320)


def summary(values: dict[str, str]) -> str:
    """One line identifying a connection: server and ports."""
    get = values.get
    parts = []
    user = get(config_schema.REMOTE_USER.key, "")
    server = get(config_schema.REMOTE_SERVER.key, "")
    ssh_port_field = config_schema.REMOTE_SERVER_SSH_PORT
    ssh_port = get(ssh_port_field.key, "")
    if server:
        if ssh_port and ssh_port != ssh_port_field.default:
            server = f"{server}:{ssh_port}"
        parts.append(f"{user}@{server}" if user else server)
    local = get(config_schema.LOCAL_PORT.key, "")
    remote = get(config_schema.REMOTE_PORT.key, "")
    if local or remote:
        parts.append(f"local {local or '?'} \u2192 remote {remote or '?'}")
    return " \u00b7 ".join(parts)


class ElidedLabel(QLabel):
    """Plain-text label that shrinks with its row, ending in "..." when
    the text doesn't fit (the full text is then in the tooltip)."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent) -> None:
        metrics = self.fontMetrics()
        elided = metrics.elidedText(
            self.text(), Qt.TextElideMode.ElideRight, self.width()
        )
        self.setToolTip(self.text() if elided != self.text() else "")
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(
            self.rect(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )


class ConnectionRow(QFrame):
    """One connection in the list: indicator, name, summary, buttons.

    Emits ``clicked()`` when clicked outside its buttons.
    """

    clicked = pyqtSignal()

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        name = values.get(config_schema.NAME.key, "")

        # Display only: clicks go through to the row (which edits).
        self.enabled_box = QCheckBox()
        self.enabled_box.setChecked(
            is_true(values.get(config_schema.ENABLED.key, ""))
        )
        self.enabled_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.enabled_box.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.enabled_box.setToolTip(ENABLED_TOOLTIP)

        self.name_label = ElidedLabel(name or UNNAMED)
        font = self.name_label.font()
        font.setBold(True)
        self.name_label.setFont(font)
        self.summary_label = ElidedLabel(summary(values))
        palette = self.summary_label.palette()  # greyed: secondary info
        palette.setColor(
            QPalette.ColorRole.WindowText,
            palette.color(QPalette.ColorRole.PlaceholderText),
        )
        self.summary_label.setPalette(palette)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(self.name_label)
        if self.summary_label.text():
            text.addWidget(self.summary_label)

        self.check_button = QPushButton(CHECK_DAEMON_TEXT)
        self.check_button.setToolTip(
            "Check the vt-tunnel service of this connection: installed, "
            "enabled, working or failed"
        )
        self.edit_button = QPushButton("Edit")
        self.edit_button.setToolTip("Edit this connection")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.addWidget(self.enabled_box)
        layout.addLayout(text, stretch=1)
        layout.addWidget(self.check_button)
        layout.addWidget(self.edit_button)
        self.setToolTip("Click to edit")
        for button in (self.check_button, self.edit_button):
            button.setCursor(Qt.CursorShape.ArrowCursor)

    # Labels and the display-only checkbox don't take mouse events: they
    # reach the row. Buttons take theirs.

    def mousePressEvent(self, event: QMouseEvent) -> None:
        event.accept()  # so that the release comes here too

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()


class MainWindow(QMainWindow):
    """Lists the connections.

    Emits ``connection_activated(row)`` when a connection is to be edited
    (its row or Edit button clicked), ``daemon_check_requested(row)`` from
    its "Check daemon" button, ``add_requested()`` from "Add connection",
    and ``visibility_changed(bool)`` when the window is shown or hidden
    (closing it hides it). Minimizing and restoring don't count: the window
    stays visible.
    """

    connection_activated = pyqtSignal(int)
    daemon_check_requested = pyqtSignal(int)
    add_requested = pyqtSignal()
    visibility_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("vt-tunnel")
        self.resize(*INITIAL_SIZE)

        self.rows: list[ConnectionRow] = []

        # The rows, top-aligned in a scrollable, list-like area.
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(
            ROW_SPACING, ROW_SPACING, ROW_SPACING, ROW_SPACING
        )
        self._rows_layout.setSpacing(ROW_SPACING)
        rows_box = QWidget()
        rows_box.setBackgroundRole(QPalette.ColorRole.Base)
        rows_box.setAutoFillBackground(True)
        outer = QVBoxLayout(rows_box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._rows_layout)
        outer.addStretch(1)
        self.connection_list = QScrollArea()
        self.connection_list.setWidget(rows_box)
        self.connection_list.setWidgetResizable(True)  # rows: list width
        self.connection_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.empty_label = QLabel(EMPTY_TEXT)
        self.empty_label.setEnabled(False)  # greyed
        self.empty_label.setContentsMargins(8, 6, 8, 6)

        self.add_button = QPushButton("Add connection")
        self.add_button.setToolTip("Add a new connection")
        self.add_button.clicked.connect(self.add_requested)
        bottom = QHBoxLayout()
        bottom.addWidget(self.add_button)
        bottom.addStretch(1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(
            WINDOW_MARGIN, WINDOW_MARGIN, WINDOW_MARGIN, WINDOW_MARGIN
        )
        layout.addWidget(self.connection_list, stretch=1)
        layout.addLayout(bottom)
        self.setCentralWidget(central)

        self.set_connections([])

    def bring_to_front(self) -> None:
        """Show the window, un-minimized and on top."""
        if self.isMinimized():
            self.setWindowState(
                self.windowState() & ~Qt.WindowState.WindowMinimized
            )
        self.show()
        self.raise_()
        self.activateWindow()

    # Spontaneous show/hide events come from the window system (e.g. on
    # minimize/restore); only our own show()/hide()/close() change
    # visibility.

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not event.spontaneous():
            self.visibility_changed.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        if not event.spontaneous():
            self.visibility_changed.emit(False)

    def set_connections(self, connections: list[dict[str, str]]) -> None:
        """Show one row per connection (a dict of its config values)."""
        while self._rows_layout.count():
            widget = self._rows_layout.takeAt(0).widget()
            if widget is not self.empty_label:
                widget.deleteLater()
        self.rows = []
        if not connections:
            self._rows_layout.addWidget(self.empty_label)
            self.empty_label.show()
            return
        self.empty_label.hide()
        for row, values in enumerate(connections):
            widget = ConnectionRow(values)
            widget.clicked.connect(
                lambda r=row: self.connection_activated.emit(r)
            )
            widget.edit_button.clicked.connect(
                lambda _=False, r=row: self.connection_activated.emit(r)
            )
            widget.check_button.clicked.connect(
                lambda _=False, r=row: self.daemon_check_requested.emit(r)
            )
            self._rows_layout.addWidget(widget)
            self.rows.append(widget)

    def set_busy(self, row: int, busy: bool) -> None:
        """Show that the daemon check of ``row`` runs (the GUI won't
        repaint until it ends)."""
        button = self.rows[row].check_button
        if busy:
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            button.setText(CHECKING_TEXT)
            button.repaint()  # now: no event loop until done
        else:
            QGuiApplication.restoreOverrideCursor()
            button.setText(CHECK_DAEMON_TEXT)

    def show_daemon_result(
        self, result: DaemonResult, note: str | None = None
    ) -> None:
        """Show a daemon check result in a modal window."""
        daemon_result_view(result, note, self).exec()
