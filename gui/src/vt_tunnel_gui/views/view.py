"""Main window: a form with one input per config key plus Update/Reset.

The view is passive: it knows how to show and collect values, but does
not validate them or decide what the buttons do — it only emits signals
that the controller handles.
"""

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.config_schema import CfgField

# Values of the boolean ENABLED key as written in the cfg file.
BOOL_TRUE = "true"
BOOL_FALSE = "false"

STATUS_TIMEOUT_MS = 5000


class MainWindow(QMainWindow):
    """Config editor window.

    Values are exchanged as ``dict[str, str]`` keyed by config key, holding
    the raw strings as they appear in the cfg file.
    """

    update_requested = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("vt-tunnel")

        self._checkboxes: dict[str, QCheckBox] = {}
        self._line_edits: dict[str, QLineEdit] = {}

        form = QFormLayout()
        for field in config_schema.FIELDS:
            form.addRow(field.key, self._create_input(field))

        buttons = QDialogButtonBox()
        self.update_button = buttons.addButton(
            "Update", QDialogButtonBox.ButtonRole.ApplyRole
        )
        self.reset_button = buttons.addButton(
            "Reset", QDialogButtonBox.ButtonRole.ResetRole
        )
        self.update_button.clicked.connect(self.update_requested)
        self.reset_button.clicked.connect(self.reset_requested)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

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
            value = values.get(key, "")
            checkbox.setChecked(value.strip().lower() == BOOL_TRUE)
        for key, line_edit in self._line_edits.items():
            line_edit.setText(values.get(key, ""))

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
        self.statusBar().showMessage(text, STATUS_TIMEOUT_MS)
