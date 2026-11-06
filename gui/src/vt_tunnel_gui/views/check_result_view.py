"""Modal window with the result of a check (SSH login, daemon state).

Shows a verdict, the exact output of the checked program (its error
message on failure) and a command, so the user can copy it and look
for himself in a terminal.
"""

from enum import Enum

from PyQt6.QtCore import Qt
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

from vt_tunnel_gui.models import daemon_check
from vt_tunnel_gui.models.daemon_check import DaemonResult, Status
from vt_tunnel_gui.models.ssh_check import CheckResult, Outcome

MIN_WIDTH = 480
MAX_WIDTH = 900  # wider commands scroll in their field
ICON_SIZE = 32
OUTPUT_MAX_LINES = 12  # taller output scrolls


class Level(Enum):
    OK = QStyle.StandardPixmap.SP_MessageBoxInformation
    WARNING = QStyle.StandardPixmap.SP_MessageBoxWarning
    ERROR = QStyle.StandardPixmap.SP_MessageBoxCritical


class CheckResultView(QDialog):
    def __init__(
        self,
        title: str,
        level: Level,
        headline: str,
        message: str,
        output: str,
        output_label: str,
        command: str,
        command_label: str,
        note: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.level = level
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        icon = QLabel()
        icon.setPixmap(
            self.style().standardIcon(level.value).pixmap(ICON_SIZE)
        )
        self.headline = QLabel(f"<b>{headline}</b>")
        # Plain text: the message may quote program output.
        self.message = QLabel(message)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        text = QVBoxLayout()
        text.addWidget(self.headline)
        text.addWidget(self.message)
        header = QHBoxLayout()
        header.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        header.addLayout(text, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(header)

        # The program's messages, verbatim: they tell the user what to fix.
        self.output: QPlainTextEdit | None = None
        if output:
            self.output = QPlainTextEdit(output)
            self.output.setReadOnly(True)
            self.output.setFont(mono)
            self.output.setLineWrapMode(
                QPlainTextEdit.LineWrapMode.WidgetWidth
            )
            layout.addWidget(QLabel(output_label))
            layout.addWidget(self.output)

        self.note: QLabel | None = None
        if note:
            self.note = QLabel(note)
            self.note.setTextFormat(Qt.TextFormat.PlainText)
            self.note.setWordWrap(True)
            layout.addWidget(self.note)

        self.command = QLineEdit(command)
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
        layout.addWidget(QLabel(command_label))
        layout.addLayout(command_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Wide enough to show the whole command and output lines: they
        # are meant to be read.
        margin = layout.contentsMargins().left()
        wanted = (
            self.command.fontMetrics().horizontalAdvance(command)
            + self.copy_button.sizeHint().width()
            + 4 * margin
        )
        if self.output is not None:
            longest = max(
                self.output.fontMetrics().horizontalAdvance(line)
                for line in output.split("\n")
            )
            scrollbar = self.style().pixelMetric(
                QStyle.PixelMetric.PM_ScrollBarExtent
            )
            wanted = max(wanted, longest + scrollbar + 2 * margin + 24)
        width = max(MIN_WIDTH, min(wanted, MAX_WIDTH))
        if self.output is not None:
            self._fit_output(output, width - 2 * margin)
            # Logs end with the newest lines, where the error usually is.
            scroll = self.output.verticalScrollBar()
            scroll.setValue(scroll.maximum())
        self.resize(width, self.heightForWidth(width)
                    if self.hasHeightForWidth() else self.sizeHint().height())

    def _fit_output(self, output: str, width: int) -> None:
        """Make the output box tall enough for ``output`` wrapped at
        ``width`` pixels, up to OUTPUT_MAX_LINES (then it scrolls)."""
        assert self.output is not None
        metrics = self.output.fontMetrics()
        margins = 2 * self.output.frameWidth() + 8  # + document margins
        usable = max(1, width - margins - 4)
        lines = sum(
            max(1, -(-metrics.horizontalAdvance(line) // usable))
            for line in output.split("\n")
        )
        lines = min(lines, OUTPUT_MAX_LINES)
        self.output.setFixedHeight(metrics.lineSpacing() * lines + margins
                                   + metrics.lineSpacing() // 2)

    def _copy_command(self) -> None:
        QGuiApplication.clipboard().setText(self.command.text())


# ------------------------------------------------------------ SSH login

SSH_TITLE = "Connection check"
SSH_VERDICTS = {
    Outcome.OK: (Level.OK, "Connection OK"),
    Outcome.COMMAND_FAILED: (
        Level.WARNING, "Logged in, but the test command failed"
    ),
    Outcome.FAILED: (Level.ERROR, "Connection failed"),
}


def ssh_result_view(
    result: CheckResult,
    note: str | None = None,
    parent: QWidget | None = None,
) -> CheckResultView:
    level, headline = SSH_VERDICTS[result.outcome]
    return CheckResultView(
        SSH_TITLE, level, headline, result.message,
        result.output, "ssh output:",
        result.command, "Command (to try it in a terminal):",
        note, parent,
    )


# ------------------------------------------------------------ daemon

DAEMON_TITLE = "Daemon check"
DAEMON_VERDICTS = {
    Status.WORKING: (Level.OK, "Working"),
    Status.NOT_ENABLED: (Level.WARNING, "Not enabled"),
    Status.NOT_INSTALLED: (Level.ERROR, "Not installed"),
    Status.FAILED: (Level.ERROR, "Failed"),
    Status.UNKNOWN: (Level.WARNING, "Can't check"),
}


def daemon_result_view(
    result: DaemonResult,
    note: str | None = None,
    parent: QWidget | None = None,
) -> CheckResultView:
    level, headline = DAEMON_VERDICTS[result.status]
    return CheckResultView(
        DAEMON_TITLE, level, f"{result.service}: {headline}",
        result.message,
        result.log, f"Recent output (last {daemon_check.LOG_LINES} "
        "log lines):" if result.status is not Status.UNKNOWN else "Error:",
        result.command, "Command (to look in a terminal):",
        note, parent,
    )

