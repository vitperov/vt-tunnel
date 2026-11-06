"""Modal window with the result of a connection check.

Shows whether the login worked, ssh's exact output (its error message on
failure) and the command that was run, so the user can copy it and
retry it in a terminal.
"""

from PyQt6.QtGui import QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from vt_tunnel_gui.models.ssh_check import CheckResult, Outcome

WINDOW_TITLE = "Connection check"
HEADLINES = {
    Outcome.OK: "Connection OK",
    Outcome.COMMAND_FAILED: "Logged in, but the test command failed",
    Outcome.FAILED: "Connection failed",
}
ICONS = {
    Outcome.OK: QStyle.StandardPixmap.SP_MessageBoxInformation,
    Outcome.COMMAND_FAILED: QStyle.StandardPixmap.SP_MessageBoxWarning,
    Outcome.FAILED: QStyle.StandardPixmap.SP_MessageBoxCritical,
}
MIN_WIDTH = 480
MAX_WIDTH = 900  # wider commands scroll in their field
ICON_SIZE = 32
OUTPUT_MAX_LINES = 12  # taller output scrolls


class CheckResultView(QDialog):
    def __init__(
        self,
        result: CheckResult,
        note: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.setModal(True)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        icon = QLabel()
        icon.setPixmap(
            self.style().standardIcon(ICONS[result.outcome]).pixmap(ICON_SIZE)
        )
        self.headline = QLabel(f"<b>{HEADLINES[result.outcome]}</b>")
        self.message = QLabel(result.message)
        self.message.setWordWrap(True)
        text = QVBoxLayout()
        text.addWidget(self.headline)
        text.addWidget(self.message)
        header = QHBoxLayout()
        header.addWidget(icon)
        header.addLayout(text, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(header)

        # ssh's message, verbatim: it's what tells the user what to fix.
        self.output: QPlainTextEdit | None = None
        if result.output:
            self.output = QPlainTextEdit(result.output)
            self.output.setReadOnly(True)
            self.output.setFont(mono)
            self.output.setLineWrapMode(
                QPlainTextEdit.LineWrapMode.WidgetWidth
            )
            lines = min(result.output.count("\n") + 1, OUTPUT_MAX_LINES)
            self.output.setFixedHeight(
                self.output.fontMetrics().lineSpacing() * (lines + 1)
                + 2 * self.output.frameWidth()
                + 8  # document margins
            )
            layout.addWidget(QLabel("ssh output:"))
            layout.addWidget(self.output)

        self.note: QLabel | None = None
        if note:
            self.note = QLabel(note)
            self.note.setWordWrap(True)
            layout.addWidget(self.note)

        self.command = QLineEdit(result.command)
        self.command.setReadOnly(True)
        self.command.setFont(mono)
        self.command.setCursorPosition(0)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy the command to the clipboard")
        self.copy_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self._copy_command)
        command_row = QHBoxLayout()
        command_row.addWidget(self.command, stretch=1)
        command_row.addWidget(self.copy_button)
        layout.addWidget(QLabel("Command (to try it in a terminal):"))
        layout.addLayout(command_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Wide enough to show the whole command: it's meant to be read.
        command_width = (
            self.command.fontMetrics().horizontalAdvance(result.command)
            + self.copy_button.sizeHint().width()
            + 4 * layout.contentsMargins().left()
        )
        width = max(MIN_WIDTH, min(command_width, MAX_WIDTH))
        self.resize(width, self.heightForWidth(width)
                    if self.hasHeightForWidth() else self.sizeHint().height())

    def _copy_command(self) -> None:
        QGuiApplication.clipboard().setText(self.command.text())
