"""The check-result dialog: one modal window for both check kinds.

After a check finishes, its result is shown here modally: a severity
icon beside a bold headline, the summary message, the check's verbatim
program output (height-fitted, scrolled to the bottom), an optional
note line, the suggestions with copyable commands, the check's own
command, and a Close button. The dialog renders whatever the result
carries and runs nothing itself — Copy only touches the clipboard.
Every check constructs a fresh dialog; the only way to refresh a
result is to run the check again.
"""

import dataclasses

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QFontDatabase,
    QFontMetrics,
    QTextCursor,
    QTextLayout,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
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
from vt_tunnel_gui.models import ssh_check

# Severity levels the dialog can render.
INFO = "info"
WARNING = "warning"
CRITICAL = "critical"

# The standard icon per level.
_LEVEL_ICONS = {
    INFO: QStyle.StandardPixmap.SP_MessageBoxInformation,
    WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
    CRITICAL: QStyle.StandardPixmap.SP_MessageBoxCritical,
}

# ssh outcome → severity level and headline.
_SSH_OUTCOMES = {
    ssh_check.OK: (INFO, "The ssh login works"),
    ssh_check.COMMAND_FAILED: (WARNING, "The test command failed"),
    ssh_check.FAILED: (CRITICAL, "The ssh login failed"),
    ssh_check.NO_KEY: (WARNING, "No SSH key found"),
}

# daemon status → severity level and headline.
_DAEMON_STATUSES = {
    daemon_check.WORKING: (INFO, "The daemon is running"),
    daemon_check.NOT_INSTALLED: (WARNING, "The daemon is not installed"),
    daemon_check.NOT_ENABLED: (WARNING, "The daemon is not enabled"),
    daemon_check.FAILED: (CRITICAL, "The daemon failed"),
    daemon_check.UNKNOWN: (CRITICAL, "Can't check the daemon"),
}

# Output-box labels: the login check, the daemon log, and the daemon
# check that could not ask systemd at all.
_SSH_OUTPUT_LABEL = "ssh output:"
_DAEMON_OUTPUT_LABEL = "Recent output (last 20 log lines):"
_UNKNOWN_OUTPUT_LABEL = "Error:"

# Labels under which the check's own command is shown.
_SSH_COMMAND_LABEL = "The check's command (to try it in a terminal):"
_DAEMON_COMMAND_LABEL = "To look yourself, in a terminal:"

# Sizing: the widest content may stretch the dialog, within bounds.
_MIN_WIDTH = 480
_MAX_WIDTH = 900

# The output box shows this many wrapped lines at most, then scrolls.
_MAX_OUTPUT_LINES = 12

# The header icon's edge, in pixels.
_ICON_SIZE = 32

# Dialog layout geometry.
_MARGIN = 16
_SPACING = 10

# The gap between one suggestion and the next.
_SUGGESTION_GAP = 10

# The gap between a command's line edit and its Copy button.
_COMMAND_SPACING = 6


@dataclasses.dataclass(frozen=True)
class CheckPresentation:
    """Everything the dialog renders, already mapped from a result.

    ``level`` is one of the module's level constants; ``output`` is
    verbatim program output shown only when non-empty; ``note`` is an
    optional plain line between the output and the suggestions;
    ``command`` is the check's own command, always shown under
    ``command_label``; ``suggestions`` is a tuple of Suggestion
    records.
    """

    level: str
    headline: str
    message: str
    output: str = ""
    output_label: str = ""
    note: str = ""
    command: str = ""
    command_label: str = ""
    suggestions: tuple = ()


def ssh_presentation(result, note=""):
    """Map one ssh check result to the dialog's presentation."""
    level, headline = _SSH_OUTCOMES[result.outcome]
    return CheckPresentation(
        level=level,
        headline=headline,
        message=result.message,
        output=result.output,
        output_label=_SSH_OUTPUT_LABEL,
        note=note,
        command=result.command,
        command_label=_SSH_COMMAND_LABEL,
        suggestions=result.suggestions,
    )


def daemon_presentation(result, note=""):
    """Map one daemon check result to the dialog's presentation."""
    level, headline = _DAEMON_STATUSES[result.status]
    if result.status == daemon_check.UNKNOWN:
        output_label = _UNKNOWN_OUTPUT_LABEL
    else:
        output_label = _DAEMON_OUTPUT_LABEL
    return CheckPresentation(
        level=level,
        headline=headline,
        message=result.message,
        output=result.log,
        output_label=output_label,
        note=note,
        command=result.command,
        command_label=_DAEMON_COMMAND_LABEL,
        suggestions=result.suggestions,
    )


def show_ssh_result(result, note="", parent=None):
    """Show one ssh check result in a fresh modal dialog."""
    _show(ssh_presentation(result, note), parent)


def show_daemon_result(result, note="", parent=None):
    """Show one daemon check result in a fresh modal dialog."""
    _show(daemon_presentation(result, note), parent)


def _show(presentation, parent):
    """Build the dialog for one presentation and run it modally."""
    dialog = CheckResultDialog(presentation, parent)
    dialog.exec()


def _mono_font():
    """The system's standard fixed-width font."""
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def _longest_mono_line(text):
    """The widest line of one text, in the mono font's metrics."""
    metrics = QFontMetrics(_mono_font())
    lines = text.splitlines() or [""]
    return max(metrics.horizontalAdvance(line) for line in lines)


def _wrapped_line_count(line, font, width):
    """How many display lines one source line wraps into at ``width``.

    Measured with the same wrap mode the output box uses: word
    boundaries where they fit, force-broken over-wide tokens where
    they don't. An empty line is one line.
    """
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout = QTextLayout(line, font)
    layout.setTextOption(option)
    layout.beginLayout()
    count = 0
    while True:
        layout_line = layout.createLine()
        if not layout_line.isValid():
            break
        layout_line.setLineWidth(width)
        count += 1
    layout.endLayout()
    return max(1, count)


class CopyableCommand(QWidget):
    """One pasteable command: a read-only line edit plus a Copy button.

    The line edit is monospaced and its cursor is parked at position 0,
    so a long command appears from its start instead of scrolled to the
    end. Copy writes the command to the clipboard — nothing else.
    """

    def __init__(self, command, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit(command)
        self.edit.setReadOnly(True)
        self.edit.setFont(_mono_font())
        self.edit.setCursorPosition(0)
        layout.addWidget(self.edit, stretch=1)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self._copy)
        layout.addWidget(self.copy_button)

    def _copy(self):
        """Put the command on the clipboard."""
        QApplication.clipboard().setText(self.edit.text())


class CheckResultDialog(QDialog):
    """The generic modal check-result dialog.

    Built from a CheckPresentation; renders exactly what it carries
    and never runs commands itself.
    """

    def __init__(self, presentation, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("vt-tunnel")
        self._presentation = presentation
        self.output_box = None
        self.headline_label = None
        self.message_label = None
        self.note_label = None
        self.suggestions_heading = None
        self.suggestion_labels = []
        self.command_fields = []
        self.check_command_field = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(_SPACING)

        self._build_header(layout)
        self._build_output(layout)
        self._build_note(layout)
        self._build_suggestions(layout)
        self._build_command(layout)
        self._build_close(layout)

        # The width is settled after building: the command rows' Copy
        # buttons are measured, and the output box's height is then
        # fitted to the wrapping at that final width.
        self._apply_width()
        if self.output_box is not None:
            self._fit_output_height()
            self._scroll_output_to_bottom()

    # --- content, top to bottom -------------------------------------

    def _build_header(self, layout):
        """The severity icon, the bold headline and the message."""
        header = QHBoxLayout()
        header.setSpacing(_SPACING)
        icon = self.style().standardIcon(_LEVEL_ICONS[self._presentation.level])
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(_ICON_SIZE, _ICON_SIZE))
        header.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        headline = QLabel(self._presentation.headline)
        font = headline.font()
        font.setBold(True)
        headline.setFont(font)
        headline.setWordWrap(True)
        self.headline_label = headline
        text_column.addWidget(headline)
        message = QLabel(self._presentation.message)
        message.setWordWrap(True)
        message.setTextFormat(Qt.TextFormat.PlainText)
        self.message_label = message
        text_column.addWidget(message)
        header.addLayout(text_column, stretch=1)

        layout.addLayout(header)

    def _build_output(self, layout):
        """The labelled output box, when the result has output."""
        presentation = self._presentation
        if not presentation.output or not presentation.output_label:
            return
        label = QLabel(presentation.output_label)
        layout.addWidget(label)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setFont(_mono_font())
        box.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        box.setPlainText(presentation.output)
        self.output_box = box
        layout.addWidget(box)

    def _build_note(self, layout):
        """The optional note line, word-wrapped plain text."""
        note = self._presentation.note
        if not note:
            return
        label = QLabel(note)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        self.note_label = label
        layout.addWidget(label)

    def _build_suggestions(self, layout):
        """The suggestions section, when the check produced any."""
        suggestions = self._presentation.suggestions
        if not suggestions:
            return
        heading = QLabel("What you can do:")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        self.suggestions_heading = heading
        layout.addWidget(heading)
        for index, suggestion in enumerate(suggestions):
            if index:
                layout.addSpacing(_SUGGESTION_GAP)
            text = QLabel(suggestion.text)
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.PlainText)
            self.suggestion_labels.append(text)
            layout.addWidget(text)
            if suggestion.command:
                field = CopyableCommand(suggestion.command)
                self.command_fields.append(field)
                layout.addWidget(field)

    def _build_command(self, layout):
        """The check's own command, always shown under its label."""
        presentation = self._presentation
        if not presentation.command:
            return
        if presentation.command_label:
            label = QLabel(presentation.command_label)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
        field = CopyableCommand(presentation.command)
        self.check_command_field = field
        self.command_fields.append(field)
        layout.addWidget(field)

    def _build_close(self, layout):
        """The Close button, right-aligned."""
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- sizing ------------------------------------------------------

    def _apply_width(self):
        """Set the dialog's width: fit the widest single row, in bounds.

        The rows stack vertically, so the width must fit the one widest
        row — the longest output line or the longest command — not their
        sum. The minimum is 480 and the hard cap is 900; a long command
        or output line widens the dialog so it can be read whole.
        """
        needed = 2 * _MARGIN
        if self.output_box is not None:
            needed = max(
                needed,
                2 * _MARGIN
                + _longest_mono_line(self._presentation.output)
                + self._output_overhead(),
            )
        for field in self.command_fields:
            needed = max(
                needed,
                2 * _MARGIN
                + _longest_mono_line(field.edit.text())
                + self._command_overhead(field),
            )
        width = min(max(needed, _MIN_WIDTH), _MAX_WIDTH)
        self.resize(int(width), self.height())

    def _output_overhead(self):
        """The output box's horizontal chrome: frame, margins, scrollbar."""
        box = self.output_box
        scrollbar = self.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent
        )
        return (
            2 * box.frameWidth()
            + 2 * int(box.document().documentMargin())
            + scrollbar
        )

    def _command_overhead(self, field):
        """One command row's chrome: line-edit frame, Copy button, gap."""
        frame = self.style().pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth)
        return (
            2 * frame
            + field.copy_button.sizeHint().width()
            + _COMMAND_SPACING
        )

    def _fit_output_height(self):
        """Fit the output box to its wrapped line count, 12 lines max.

        Beyond 12 wrapped lines the box keeps the 12-line height and
        scrolls instead. The count is measured the way the box itself
        wraps (word boundaries where they fit, force-broken tokens
        where they don't), at the width the text will actually have.
        """
        box = self.output_box
        font = box.font()
        metrics = QFontMetrics(font)
        line_height = metrics.height()
        usable = self._output_usable_width()
        wrapped = 0
        for line in self._presentation.output.splitlines() or [""]:
            wrapped += _wrapped_line_count(line, font, usable)
        lines = min(wrapped, _MAX_OUTPUT_LINES)
        frame = 2 * box.frameWidth()
        box.setFixedHeight(lines * line_height + frame + 4)

    def _output_usable_width(self):
        """The width the output text has inside the box, at final size."""
        return self.width() - 2 * _MARGIN - self._output_overhead()

    def _scroll_output_to_bottom(self):
        """Scroll the output box to its last line.

        The text cursor moves to the end (which also scrolls), and the
        scrollbar is pinned to its maximum directly — the cursor scroll
        alone can land one line short when the layout changes afterwards.
        """
        box = self.output_box
        cursor = box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        box.setTextCursor(cursor)
        scrollbar = box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def showEvent(self, event):
        """Re-assert the bottom scroll once the layout is final."""
        super().showEvent(event)
        if self.output_box is not None:
            self._scroll_output_to_bottom()
