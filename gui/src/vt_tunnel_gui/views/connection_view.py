"""The connection editor dialog: a schema-generated form.

A modal dialog parented to the main window, strictly passive: it shows
and collects values and emits requests upward — save, reset, delete,
check the connection. It never validates, never touches files and never
closes itself (only the controller closes it, after a delete); the
user's window close simply dismisses it. One instance per application.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
)

from vt_tunnel_gui import config_schema

_NEW_TITLE = "New connection"
_EDIT_TITLE = "Edit connection"

# The dialog opens 460 wide; the height follows the size hint.
_INITIAL_WIDTH = 460

# How long a transient status message stays visible.
_STATUS_TIMEOUT_MS = 5000

_DELETE_TEXT = "Delete"
_CHECK_TEXT = "Check connection"


class ConnectionEditor(QDialog):
    """The modal schema-driven editor for one connection.

    The form is generated once from the config schema: one labelled row
    per field in schema order, ENABLED as a checkbox, every other field
    a line edit with the schema's example as its placeholder and its
    description as the tooltip. Values cross the boundary only as plain
    dicts of raw strings exactly as they would appear in the file.
    """

    save_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    check_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self._new_mode = True

        layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()
        layout.addLayout(self.form_layout)
        self._build_form()
        self._build_buttons(layout)
        self._build_status_bar(layout)

        self.resize(_INITIAL_WIDTH, self.sizeHint().height())
        self._update_title()

    # --- construction -------------------------------------------------

    def _build_form(self):
        """One labelled row per schema field, in schema order."""
        self.field_labels = {}
        self.field_edits = {}
        self.enabled_checkbox = None
        for field in config_schema.FIELDS:
            label = QLabel(field.key)
            self.field_labels[field.key] = label
            if field.key == "ENABLED":
                self.enabled_checkbox = QCheckBox()
                self.enabled_checkbox.setToolTip(field.description)
                self.form_layout.addRow(label, self.enabled_checkbox)
            else:
                edit = QLineEdit()
                edit.setPlaceholderText(field.example)
                edit.setToolTip(field.description)
                self.field_edits[field.key] = edit
                self.form_layout.addRow(label, edit)
        self.field_edits["NAME"].textChanged.connect(self._update_title)

    def _build_buttons(self, layout):
        """Delete far left, Check next to it, Save + Reset right-aligned.

        Save is the default button (Enter); Reset, Delete and Check
        explicitly opt out of auto-default, so Enter can never
        silently discard edits.
        """
        row = QHBoxLayout()

        self.delete_button = QPushButton(_DELETE_TEXT)
        self.delete_button.setAutoDefault(False)
        self.delete_button.clicked.connect(self.delete_requested)
        row.addWidget(self.delete_button)

        self.check_button = QPushButton(_CHECK_TEXT)
        self.check_button.setAutoDefault(False)
        self.check_button.clicked.connect(self.check_requested)
        row.addWidget(self.check_button)

        row.addStretch()

        box = QDialogButtonBox()
        self.save_button = box.addButton(
            QDialogButtonBox.StandardButton.Save
        )
        self.save_button.setAutoDefault(True)
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save_requested)
        self.reset_button = box.addButton(
            QDialogButtonBox.StandardButton.Reset
        )
        self.reset_button.setAutoDefault(False)
        self.reset_button.clicked.connect(self.reset_requested)
        row.addWidget(box)

        layout.addLayout(row)

        # The dialog starts in new mode: Delete stays hidden until the
        # controller fills the form for an existing connection.
        self.delete_button.hide()

    def _build_status_bar(self, layout):
        """A plain status bar at the bottom, without the size grip."""
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        layout.addWidget(self.status_bar)

    # --- values exchange ----------------------------------------------

    def values(self):
        """The form's contents as raw strings, one entry per schema key."""
        result = {}
        for field in config_schema.FIELDS:
            if field.key == "ENABLED":
                result[field.key] = (
                    "true" if self.enabled_checkbox.isChecked() else "false"
                )
            else:
                result[field.key] = self.field_edits[field.key].text()
        return result

    def set_values(self, values):
        """Refill every input from a raw-string dict (missing keys empty)."""
        for field in config_schema.FIELDS:
            if field.key == "ENABLED":
                raw = values.get(field.key, "")
                self.enabled_checkbox.setChecked(
                    raw.strip().lower() == "true"
                )
            else:
                self.field_edits[field.key].setText(values.get(field.key, ""))
        self._update_title()

    # --- modes ---------------------------------------------------------

    def edit_new(self, values):
        """Fill the form for a connection that has no file yet."""
        self._new_mode = True
        self.set_values(values)
        self.delete_button.hide()

    def edit_connection(self, values):
        """Fill the form for an existing connection."""
        self._new_mode = False
        self.set_values(values)
        self.delete_button.show()

    def _update_title(self):
        """The window title per mode: new, edit, or edit with the name."""
        if self._new_mode:
            self.setWindowTitle(_NEW_TITLE)
            return
        name = self.field_edits["NAME"].text()
        if name:
            self.setWindowTitle(f"{_EDIT_TITLE}: {name}")
        else:
            self.setWindowTitle(_EDIT_TITLE)

    # --- feedback, on controller request -------------------------------

    def show_saved(self, path):
        """A transient status message naming the saved file."""
        self.status_bar.showMessage(f"Saved {path}", _STATUS_TIMEOUT_MS)

    def show_invalid(self, errors):
        """The validation errors, joined by newlines, in a critical box."""
        QMessageBox.critical(
            self, "Invalid values", "\n".join(errors)
        )

    def show_save_failed(self, path, error):
        """The failed write, with the path and the OS error."""
        QMessageBox.critical(
            self, "Save failed", f"Could not save {path}:\n{error}"
        )

    def confirm_delete(self, name, path):
        """Ask before deleting; No is the default. The caller deletes."""
        answer = QMessageBox.question(
            self,
            "Delete connection",
            f'Delete connection "{name}"? '
            f"Its file {path} will be deleted right away.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    # --- busy state for the blocking ssh check -------------------------

    def set_busy(self, timeout_seconds):
        """Wait cursor plus a status message naming the timeout.

        The message carries no duration: the event loop is about to
        freeze, so the message stays until set_idle() clears it.
        """
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status_bar.showMessage(
            f"Checking the connection (timeout: {timeout_seconds} s)…"
        )
        self.repaint()

    def set_idle(self):
        """Leave the busy state: cursor back, status message cleared."""
        QApplication.restoreOverrideCursor()
        self.status_bar.clearMessage()

    # --- opening ---------------------------------------------------------

    def open_editor(self):
        """Show, raise and activate — one instance, brought to front.

        Safe on an already-open editor: show() no-ops, raise and
        activate bring it to front instead of stacking a second one.
        """
        self.show()
        self.raise_()
        self.activateWindow()
