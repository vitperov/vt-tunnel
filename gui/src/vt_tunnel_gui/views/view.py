"""The main window: the connections list and the add button.

A passive emitter: it renders the connection list the controller pushes
into it and emits row-indexed requests upward — activate (row click or
Edit), check the daemon (Check daemon), add a connection. It holds no
model state; rows are identified by index against the last-loaded list.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vt_tunnel_gui import config_schema

_WINDOW_TITLE = "vt-tunnel"
_INITIAL_SIZE = (620, 320)
_MARGIN = 12
_ROW_SPACING = 4
_EMPTY_TEXT = "No connections yet."
_UNNAMED_TEXT = "(unnamed)"
_CHECK_BUTTON_TEXT = "Check daemon"
_CHECKING_TEXT = "Checking…"
_EDIT_BUTTON_TEXT = "Edit"
_ADD_BUTTON_TEXT = "Add connection"
_CHECK_TOOLTIP = (
    "Ask systemd for the state of this connection's daemon service."
)
_EDIT_TOOLTIP = "Open this connection for editing."
_CHECKBOX_TOOLTIP = (
    "Display only: the daemon does not actually use ENABLED yet — "
    "the daemon check shows the real systemd state."
)


class ElidedLabel(QLabel):
    """A plain-text label that elides to its width, with a full-text tooltip.

    The label shrinks with the row (its width hint is ignored, so the
    row never grows to fit it); when the text no longer fits it is
    truncated with an ellipsis and the full text moves into the
    tooltip.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.setMinimumWidth(0)
        self._full_text = text
        self.setText(text)
        self._update_elide()

    def set_full_text(self, text):
        """Replace the text and re-elide it to the current width."""
        self._full_text = text
        self._update_elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self):
        """Re-elide the full text to the current width."""
        metrics = self.fontMetrics()
        elided = metrics.elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            max(self.width() - 2, 0),
        )
        self.setToolTip(self._full_text if elided != self._full_text else "")
        if self.text() != elided:
            self.setText(elided)


def _summary(values):
    """The greyed summary line for one connection's values, or None.

    Of the form ``user@server:port · local L → remote R``: the ssh port
    is shown only when it differs from the schema default, and a
    question mark stands in for every missing piece. The line is shown
    only when there is something to show — the ssh port alone (default
    or missing) never justifies it.
    """
    user = values.get("REMOTE_USER", "")
    server = values.get("REMOTE_SERVER", "")
    local = values.get("LOCAL_PORT", "")
    remote = values.get("REMOTE_PORT", "")
    if not (user or server or local or remote):
        return None
    login = f"{user or '?'}@{server or '?'}"
    port = values.get("REMOTE_SERVER_SSH_PORT", "")
    if port != config_schema.DEFAULTS["REMOTE_SERVER_SSH_PORT"]:
        login += f":{port or '?'}"
    return f"{login} · local {local or '?'} → remote {remote or '?'}"


class ConnectionRow(QFrame):
    """One connection's row: enabled checkbox, name + summary, buttons.

    A press-then-release with the left button fully inside the row —
    on the background or on the text, but not on the buttons — emits
    ``activated`` with the row's index, exactly like the Edit button.
    """

    activated = pyqtSignal(int)
    check_requested = pyqtSignal(int)

    def __init__(self, index, values, parent=None):
        super().__init__(parent)
        self._index = index
        self._press_inside = False
        self.setObjectName("connection-row")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#connection-row { border: 1px solid palette(mid);"
            " border-radius: 4px; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        enabled = values.get("ENABLED", "")
        self.enabled_checkbox = QCheckBox()
        self.enabled_checkbox.setChecked(enabled.strip().lower() == "true")
        self.enabled_checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.enabled_checkbox.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.enabled_checkbox.setToolTip(_CHECKBOX_TOOLTIP)
        layout.addWidget(self.enabled_checkbox)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(0)
        name = values.get("NAME", "")
        self.name_label = ElidedLabel(name or _UNNAMED_TEXT)
        font = self.name_label.font()
        font.setBold(True)
        self.name_label.setFont(font)
        text_column.addWidget(self.name_label)
        summary = _summary(values)
        self.summary_label = None
        if summary is not None:
            self.summary_label = ElidedLabel(summary)
            self.summary_label.setStyleSheet("color: gray;")
            text_column.addWidget(self.summary_label)
        layout.addLayout(text_column, stretch=1)

        self.check_button = QPushButton(_CHECK_BUTTON_TEXT)
        self.check_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.check_button.setToolTip(_CHECK_TOOLTIP)
        self.check_button.clicked.connect(self._emit_check)
        layout.addWidget(self.check_button)

        self.edit_button = QPushButton(_EDIT_BUTTON_TEXT)
        self.edit_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.edit_button.setToolTip(_EDIT_TOOLTIP)
        self.edit_button.clicked.connect(self._emit_activate)
        layout.addWidget(self.edit_button)

    def set_checking(self, busy):
        """Mark this row's check button busy (or restore it).

        While busy the button reads "Checking…" and the application
        shows a wait cursor; the button is force-repainted because the
        event loop is gone until the blocking check ends.
        """
        if busy:
            self.check_button.setText(_CHECKING_TEXT)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            self.check_button.setText(_CHECK_BUTTON_TEXT)
            QApplication.restoreOverrideCursor()
        self.check_button.repaint()

    def _emit_check(self):
        self.check_requested.emit(self._index)

    def _emit_activate(self):
        self.activated.emit(self._index)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_inside = True
        event.accept()

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._press_inside
            and self.rect().contains(event.position().toPoint())
        ):
            self.activated.emit(self._index)
        self._press_inside = False
        event.accept()


class MainWindow(QMainWindow):
    """The connections list window; a passive emitter of row requests."""

    edit_requested = pyqtSignal(int)
    check_requested = pyqtSignal(int)
    add_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_WINDOW_TITLE)
        self.resize(*_INITIAL_SIZE)
        self._rows = []

        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        outer.setSpacing(_MARGIN)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.list_scroll, stretch=1)

        self.list_panel = QWidget()
        self.list_panel.setAutoFillBackground(True)
        palette = self.list_panel.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("white"))
        self.list_panel.setPalette(palette)
        self.list_rows = QVBoxLayout(self.list_panel)
        self.list_rows.setContentsMargins(0, 0, 0, 0)
        self.list_rows.setSpacing(_ROW_SPACING)
        self.list_rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.list_scroll.setWidget(self.list_panel)

        self.empty_label = QLabel(_EMPTY_TEXT)
        self.empty_label.setEnabled(False)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_rows.addWidget(self.empty_label)
        self.list_rows.addStretch(1)

        bottom = QHBoxLayout()
        self.add_button = QPushButton(_ADD_BUTTON_TEXT)
        bottom.addWidget(self.add_button)
        bottom.addStretch(1)
        outer.addLayout(bottom)

        self.add_button.clicked.connect(self.add_requested.emit)
        self._set_empty_state(True)

    def set_connections(self, connections):
        """Replace the whole row set with one row per connection.

        The previous rows are torn down wholesale — there is no
        incremental row update. Each connection is a raw value dict.
        """
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        self._set_empty_state(not connections)
        for index, values in enumerate(connections):
            row = ConnectionRow(index, values, self.list_panel)
            row.activated.connect(self.edit_requested)
            row.check_requested.connect(self.check_requested)
            # insert before the trailing stretch filler, so the rows stay
            # top-aligned however many rebuilds run
            self.list_rows.insertWidget(self.list_rows.count() - 1, row)
            self._rows.append(row)

    def set_checking(self, row, busy=True):
        """Mark one row's check button busy (or restore it)."""
        if 0 <= row < len(self._rows):
            self._rows[row].set_checking(busy)

    def _set_empty_state(self, empty):
        self.empty_label.setVisible(empty)
