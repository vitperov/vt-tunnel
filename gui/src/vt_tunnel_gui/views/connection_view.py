"""Connection editor window: one input per field, Save/Reset/Delete.

The view is passive: it knows how to show and collect values, but does
not validate them or decide what the buttons do — it only emits signals
that the controller handles.
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.config_schema import CfgField
from vt_tunnel_gui.models.ssh_check import CheckResult
from vt_tunnel_gui.views.check_result_view import CheckResultView

# Values of the boolean ENABLED key as written in the cfg file.
BOOL_TRUE = "true"
BOOL_FALSE = "false"

STATUS_TIMEOUT_MS = 5000

WINDOW_TITLE = "Edit connection"
NEW_WINDOW_TITLE = "New connection"
# Wide enough for the default config path in the "Saved ..." status.
INITIAL_WIDTH = 460


def is_true(value: str) -> bool:
    """Whether a boolean cfg value (e.g. ENABLED) means "on"."""
    return value.strip().lower() == BOOL_TRUE


class ConnectionView(QDialog):
    """Modal editor for the fields of one connection.

    In "new" mode (a connection not saved yet) there is nothing to delete,
    so the Delete button is hidden.

    Values are exchanged as ``dict[str, str]`` keyed by config key, holding
    the raw strings as they appear in the cfg file.
    """

    save_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    check_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.setModal(True)

        self._is_new = False
        self._name = ""
        self._checkboxes: dict[str, QCheckBox] = {}
        self._line_edits: dict[str, QLineEdit] = {}

        form = QFormLayout()
        for field in config_schema.FIELDS:
            form.addRow(field.key, self._create_input(field))

        # Button order is Delete, Reset ... Save on every platform:
        # - Save has AcceptRole, which all platform layouts put on the
        #   right, where OK is expected (the box's accepted() signal is not
        #   connected, so Save doesn't close the window);
        # - Delete is kept out of the button box: the box would put a
        #   DestructiveRole button next to (or right of) Save on some
        #   platforms. It sits on the far left instead, away from Save;
        # - Check connection sits next to it, for the same reason.
        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton(
            "Save", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.reset_button = buttons.addButton(
            "Reset", QDialogButtonBox.ButtonRole.ResetRole
        )
        self.delete_button = QPushButton("Delete")
        self.check_button = QPushButton("Check connection")
        self.check_button.setToolTip(
            "Try to log in to REMOTE_SERVER as REMOTE_USER with your SSH "
            "key, using the values in the form (saved or not)"
        )
        self.save_button.clicked.connect(self.save_requested)
        self.reset_button.clicked.connect(self.reset_requested)
        self.delete_button.clicked.connect(self.delete_requested)
        self.check_button.clicked.connect(self.check_requested)

        button_row = QHBoxLayout()
        button_row.addWidget(self.delete_button)
        button_row.addWidget(self.check_button)
        button_row.addWidget(buttons, stretch=1)

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(button_row)
        layout.addWidget(self._status_bar)

        # In a dialog, Enter clicks the default button: make that Save,
        # never Reset (which would silently discard the edits). Must be set
        # once the buttons are inside the dialog, or the dialog doesn't
        # register it and drops it as soon as the button loses focus.
        self.save_button.setDefault(True)
        self.reset_button.setAutoDefault(False)
        self.delete_button.setAutoDefault(False)
        self.check_button.setAutoDefault(False)

        self.resize(INITIAL_WIDTH, self.sizeHint().height())

    def _create_input(self, field: CfgField) -> QWidget:
        widget: QWidget
        if field is config_schema.ENABLED:
            widget = QCheckBox()
            self._checkboxes[field.key] = widget
        else:
            widget = QLineEdit()
            widget.setPlaceholderText(field.example)
            self._line_edits[field.key] = widget
        widget.setToolTip(field.description)
        return widget

    def values(self) -> dict[str, str]:
        """Return the values currently entered in the form."""
        result: dict[str, str] = {}
        for field in config_schema.FIELDS:
            if field.key in self._checkboxes:
                checked = self._checkboxes[field.key].isChecked()
                result[field.key] = BOOL_TRUE if checked else BOOL_FALSE
            else:
                result[field.key] = self._line_edits[field.key].text()
        return result

    def set_values(self, values: dict[str, str]) -> None:
        """Fill the form; keys missing from ``values`` are cleared."""
        for key, checkbox in self._checkboxes.items():
            checkbox.setChecked(is_true(values.get(key, "")))
        for key, line_edit in self._line_edits.items():
            line_edit.setText(values.get(key, ""))
        self._name = values.get(config_schema.NAME.key, "")
        self._update_title()

    def set_new(self, is_new: bool) -> None:
        """Switch between editing a saved connection and a new one."""
        self._is_new = is_new
        self.delete_button.setVisible(not is_new)
        self._update_title()

    def _update_title(self) -> None:
        if self._is_new:
            title = NEW_WINDOW_TITLE
        elif self._name:
            title = f"{WINDOW_TITLE}: {self._name}"
        else:
            title = WINDOW_TITLE
        self.setWindowTitle(title)

    def open_editor(self) -> None:
        """Show the window (or bring it to front if already shown)."""
        self._status_bar.clearMessage()
        self.show()
        self.raise_()
        self.activateWindow()

    def close_editor(self) -> None:
        self.accept()

    def confirm_delete(self, name: str, path: Path) -> bool:
        """Ask whether to delete connection ``name`` from ``path``."""
        answer = QMessageBox.question(
            self,
            "Delete connection?",
            f"Delete connection \"{name}\"?\n\n"
            f"It will be removed from {path} right away.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_create(self, path: Path) -> bool:
        """Ask whether to create the missing config file ``path``."""
        answer = QMessageBox.question(
            self,
            "Create config file?",
            f"The config file {path} does not exist.\n\nCreate it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_error(self, title: str, text: str) -> None:
        QMessageBox.critical(self, title, text)

    def show_status(self, text: str) -> None:
        self._status_bar.showMessage(text, STATUS_TIMEOUT_MS)

    def set_busy(self, busy: bool, text: str = "") -> None:
        """Show that a blocking task runs (the GUI won't repaint until it
        ends): wait cursor and ``text`` in the status bar."""
        if busy:
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._status_bar.showMessage(text)
            self._status_bar.repaint()  # now: no event loop until done
        else:
            QGuiApplication.restoreOverrideCursor()
            self._status_bar.clearMessage()

    def show_check_result(
        self, result: CheckResult, note: str | None = None
    ) -> None:
        """Show a connection check result in a modal window."""
        CheckResultView(result, note, self).exec()
