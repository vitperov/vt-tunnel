"""Tests of the daemon check and of the main window's connection rows.

Fake ``systemctl`` and ``journalctl`` (shell scripts) are put first on
PATH, so the real subprocess code runs against a scripted systemd.
"""

import shlex
import stat
import time

import pytest

from conftest import VALID_VALUES, App
from vt_tunnel_gui.models import daemon_check
from vt_tunnel_gui.models.daemon_check import SERVICE, Status, run_check

# What `systemctl show` prints for an installed, enabled, running unit.
RUNNING = {
    "LoadState": "loaded",
    "LoadError": "",
    "ActiveState": "active",
    "SubState": "running",
    "UnitFileState": "enabled",
    "Result": "success",
    "ExecMainStatus": "0",
    "NRestarts": "0",
    "ActiveEnterTimestamp": "Thu 2025-11-06 12:00:00 UTC",
}
NOT_FOUND = RUNNING | {
    "LoadState": "not-found",
    "ActiveState": "inactive",
    "SubState": "dead",
    "UnitFileState": "",
    "ActiveEnterTimestamp": "",
}
JOURNAL = (
    "Nov 06 12:00:01 host sudo[101]: root : PWD=/ ; USER=root ; COMMAND=...\n"
    "Nov 06 12:00:02 host bash[104]: vasya@vasya.com: Permission denied "
    "(publickey).\n"
    "Nov 06 12:00:02 host systemd[1]: vt-tunnel.service: Main process "
    "exited, code=exited, status=1/FAILURE"
)
ENABLE = f"sudo systemctl enable {SERVICE}"
START = f"sudo systemctl start {SERVICE}"
RESTART = f"sudo systemctl restart {SERVICE}"
UNMASK = f"sudo systemctl unmask {SERVICE}"


def commands(result) -> list[str]:
    """The suggested commands; "" for advice without a command."""
    return [x.command for x in result.suggestions]


PERMISSION_HINT = (
    "Hint: You are currently not seeing messages from other users and the "
    "system.\n      Users in groups 'adm', 'systemd-journal' can see all "
    "messages."
)


@pytest.fixture
def fake_systemd(tmp_path, monkeypatch):
    """Install fake systemctl/journalctl; returns ``install(props, ...)``.

    Each fake logs its argv (one per line) to ``tmp_path/<name>-argv``.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    def script(name: str, body: str) -> None:
        log = shlex.quote(str(tmp_path / f"{name}-argv"))
        path = bin_dir / name
        path.write_text(
            f"#!/bin/bash\nprintf '%s\\n' \"$@\" > {log}\n{body}\n"
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def install(
        props=None,
        show_body=None,
        journal=JOURNAL,
        journal_stderr="",
        journal_body=None,
    ):
        if show_body is None:
            text = "".join(f"{k}={v}\n" for k, v in (props or {}).items())
            show_body = f"printf %s {shlex.quote(text)}"
        script("systemctl", show_body)
        if journal_body is None:
            journal_body = (
                f"printf '%s\\n' {shlex.quote(journal)}\n"
                f"printf '%s\\n' {shlex.quote(journal_stderr)} >&2"
            )
        script("journalctl", journal_body)
        return tmp_path

    return install


def argv(tmp_path, name):
    path = tmp_path / f"{name}-argv"
    return path.read_text().splitlines() if path.exists() else None


# --------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------


class TestStates:
    def test_not_installed(self, fake_systemd):
        logs = fake_systemd(NOT_FOUND)
        result = run_check(SERVICE)
        assert result.status is Status.NOT_INSTALLED
        assert "not installed" in result.message
        assert result.log == ""
        assert argv(logs, "journalctl") is None  # nothing to read

    def test_working(self, fake_systemd):
        fake_systemd(RUNNING)
        result = run_check(SERVICE)
        assert result.status is Status.WORKING
        assert RUNNING["ActiveEnterTimestamp"] in result.message
        assert "not enabled" not in result.message
        # autossh keeps running while it retries: the log stays visible
        assert result.log == JOURNAL

    def test_working_but_not_enabled(self, fake_systemd):
        fake_systemd(RUNNING | {"UnitFileState": "disabled"})
        result = run_check(SERVICE)
        assert result.status is Status.WORKING
        assert "won't start at boot" in result.message

    @pytest.mark.parametrize(
        "file_state", ["disabled", "linked", "indirect", ""]
    )
    def test_not_enabled(self, fake_systemd, file_state):
        fake_systemd(
            RUNNING | {"ActiveState": "inactive", "SubState": "dead",
                       "UnitFileState": file_state}
        )
        result = run_check(SERVICE)
        assert result.status is Status.NOT_ENABLED
        assert commands(result) == [ENABLE, START]
        assert "sudo" not in result.message  # the commands are separate

    def test_masked(self, fake_systemd):
        fake_systemd(
            RUNNING | {"LoadState": "masked", "ActiveState": "inactive",
                       "SubState": "dead", "UnitFileState": "masked"}
        )
        result = run_check(SERVICE)
        assert result.status is Status.NOT_ENABLED
        assert "masked" in result.message
        assert commands(result) == [UNMASK, ENABLE, START]

    def test_failed_shows_exact_daemon_output(self, fake_systemd):
        fake_systemd(
            RUNNING | {"ActiveState": "failed", "SubState": "failed",
                       "Result": "exit-code", "ExecMainStatus": "1"}
        )
        result = run_check(SERVICE)
        assert result.status is Status.FAILED
        assert "exit code 1" in result.message
        assert result.log == JOURNAL

    def test_failed_by_signal(self, fake_systemd):
        fake_systemd(
            RUNNING | {"ActiveState": "failed", "SubState": "failed",
                       "Result": "signal", "ExecMainStatus": "9"}
        )
        assert "(signal)" in run_check(SERVICE).message

    def test_failed_and_not_enabled_is_failed(self, fake_systemd):
        # The error is more useful than "not enabled".
        fake_systemd(
            RUNNING | {"ActiveState": "failed", "SubState": "failed",
                       "UnitFileState": "disabled", "Result": "exit-code",
                       "ExecMainStatus": "1"}
        )
        result = run_check(SERVICE)
        assert result.status is Status.FAILED
        assert "won't start at boot" in result.message

    def test_restart_loop(self, fake_systemd):
        fake_systemd(
            RUNNING | {"ActiveState": "activating",
                       "SubState": "auto-restart", "NRestarts": "7"}
        )
        result = run_check(SERVICE)
        assert result.status is Status.FAILED
        assert "restarts so far: 7" in result.message
        assert result.log == JOURNAL

    def test_enabled_but_stopped(self, fake_systemd):
        fake_systemd(RUNNING | {"ActiveState": "inactive",
                                "SubState": "dead"})
        result = run_check(SERVICE)
        assert result.status is Status.FAILED
        assert "inactive/dead" in result.message

    def test_bad_unit_file(self, fake_systemd):
        error = ('org.freedesktop.systemd1.BadUnitSetting "Unit '
                 'vt-tunnel.service has a bad unit file setting."')
        fake_systemd(RUNNING | {"LoadState": "bad-setting",
                                "LoadError": error,
                                "ActiveState": "inactive"})
        result = run_check(SERVICE)
        assert result.status is Status.FAILED
        assert error in result.message


class TestLog:
    def test_journal_arguments(self, fake_systemd):
        logs = fake_systemd(RUNNING)
        run_check(SERVICE)
        assert argv(logs, "journalctl") == [
            "--unit", SERVICE, "--lines", "20", "--no-pager"
        ]

    def test_no_permission_hint_is_shown(self, fake_systemd):
        fake_systemd(
            RUNNING | {"ActiveState": "failed", "Result": "exit-code",
                       "ExecMainStatus": "1"},
            journal="-- No entries --",
            journal_stderr=PERMISSION_HINT,
        )
        log = run_check(SERVICE).log
        assert "-- No entries --" in log
        assert PERMISSION_HINT in log

    def test_empty_log(self, fake_systemd):
        fake_systemd(RUNNING, journal="")
        assert run_check(SERVICE).log == daemon_check.NO_LOG

    def test_journalctl_missing(self, fake_systemd, tmp_path, monkeypatch):
        fake_systemd(RUNNING)
        (tmp_path / "bin" / "journalctl").unlink()
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))  # no real one
        result = run_check(SERVICE)
        assert result.status is Status.WORKING  # the state is still known
        assert "journalctl" in result.log
        assert "not found" in result.log


class TestCannotCheck:
    def test_systemctl_arguments(self, fake_systemd):
        logs = fake_systemd(RUNNING)
        run_check(SERVICE)
        assert argv(logs, "systemctl") == [
            "show", SERVICE,
            "--property=" + ",".join(daemon_check.PROPERTIES),
        ]

    def test_no_systemd(self, fake_systemd):
        message = ("System has not been booted with systemd as init system "
                   "(PID 1). Can't operate.")
        fake_systemd(show_body=f"echo {shlex.quote(message)} >&2; exit 1")
        result = run_check(SERVICE)
        assert result.status is Status.UNKNOWN
        assert result.log == message

    def test_systemctl_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))
        result = run_check(SERVICE)
        assert result.status is Status.UNKNOWN
        assert "not found" in result.log

    def test_systemctl_hangs(self, fake_systemd):
        fake_systemd(show_body="exec sleep 30")
        start = time.monotonic()
        result = run_check(SERVICE, timeout=0.5)
        assert time.monotonic() - start < 5
        assert result.status is Status.UNKNOWN
        assert "0.5 seconds" in result.log

    def test_command_to_look_yourself(self, fake_systemd):
        fake_systemd(RUNNING)
        assert run_check(SERVICE).command == f"systemctl status {SERVICE}"


class TestParse:
    def test_values_may_contain_equals(self):
        assert daemon_check.parse_properties("LoadError=a=b\nX=\n") == {
            "LoadError": "a=b", "X": ""
        }

    def test_ignores_junk(self):
        assert daemon_check.parse_properties("junk\n\nA=1") == {"A": "1"}


class TestOneServiceForAll:
    """Temporary: one service, running only connection 1, for all."""

    @pytest.mark.parametrize("number", [1, 2, 7])
    def test_same_service(self, number):
        assert daemon_check.service_for(number) == SERVICE

    def test_no_note_for_first(self):
        assert daemon_check.coverage_note(1) is None

    def test_note_for_others(self):
        note = daemon_check.coverage_note(2)
        assert "first connection" in note
        assert "connection 2" in note


# --------------------------------------------------------------------------
# Main window rows
# --------------------------------------------------------------------------

OTHER = VALID_VALUES | {"NAME": "office", "ENABLED": "false",
                        "REMOTE_SERVER": "office.example.com",
                        "LOCAL_PORT": "8080", "REMOTE_PORT": "5002"}


@pytest.fixture
def window(qapp):
    from vt_tunnel_gui.views.view import MainWindow

    view = MainWindow()
    view.set_connections([dict(VALID_VALUES) | {"ENABLED": "true"},
                          dict(OTHER)])
    view.show()
    yield view
    view.close()


def record(signal):
    calls = []
    signal.connect(lambda *args: calls.append(args))
    return calls


class TestMainWindow:
    def test_one_row_per_connection(self, window):
        assert [r.name_label.text() for r in window.rows] == [
            "home", "office"
        ]

    def test_summary(self, window):
        assert window.rows[1].summary_label.text() == (
            "vasya@office.example.com \u00b7 local 8080 \u2192 remote 5002"
        )

    def test_summary_of_incomplete_connection(self):
        from vt_tunnel_gui.views.view import summary

        assert summary({}) == ""
        assert summary({"REMOTE_SERVER": "s"}) == "s"
        assert summary({"LOCAL_PORT": "22"}) == "local 22 \u2192 remote ?"

    def test_enabled_indicator_is_display_only(self, window):
        from PyQt6.QtCore import Qt

        first, second = window.rows
        assert first.enabled_box.isChecked()
        assert not second.enabled_box.isChecked()
        assert first.enabled_box.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

    def test_name_is_plain_text(self, qapp):
        from PyQt6.QtCore import Qt
        from vt_tunnel_gui.views.view import MainWindow

        view = MainWindow()
        view.set_connections([{"NAME": "<b>x</b>"}])
        label = view.rows[0].name_label
        assert label.textFormat() == Qt.TextFormat.PlainText

    def test_unnamed(self, qapp):
        from vt_tunnel_gui.views.view import UNNAMED, MainWindow

        view = MainWindow()
        view.set_connections([{}])
        assert view.rows[0].name_label.text() == UNNAMED

    def test_check_button_emits_its_row(self, window):
        calls = record(window.daemon_check_requested)
        window.rows[1].check_button.click()
        window.rows[0].check_button.click()
        assert calls == [(1,), (0,)]

    def test_edit_button_emits_its_row(self, window):
        calls = record(window.connection_activated)
        window.rows[1].edit_button.click()
        assert calls == [(1,)]

    def test_clicking_the_row_text_edits(self, window):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest

        calls = record(window.connection_activated)
        QTest.mouseClick(window.rows[1].name_label, Qt.MouseButton.LeftButton)
        assert calls == [(1,)]

    def test_add_button(self, window):
        calls = record(window.add_requested)
        window.add_button.click()
        assert calls == [()]

    def test_empty_list(self, qapp):
        from vt_tunnel_gui.views.view import EMPTY_TEXT, MainWindow

        view = MainWindow()
        view.show()
        assert view.rows == []
        assert view.empty_label.isVisible()
        assert view.empty_label.text() == EMPTY_TEXT
        view.set_connections([dict(VALID_VALUES)])
        assert not view.empty_label.isVisible()
        view.set_connections([])
        assert view.empty_label.isVisible()
        view.close()

    def test_reload_replaces_rows(self, window, qapp):
        window.set_connections([dict(OTHER)])
        qapp.processEvents()
        assert [r.name_label.text() for r in window.rows] == ["office"]
        layout = window._rows_layout
        assert layout.count() == 1

    def test_clicking_the_row_background_edits(self, window):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest

        calls = record(window.connection_activated)
        QTest.mouseClick(window.rows[0], Qt.MouseButton.LeftButton,
                         pos=QPoint(2, 2))
        assert calls == [(0,)]

    def test_right_click_does_not_edit(self, window):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest

        calls = record(window.connection_activated)
        QTest.mouseClick(window.rows[0], Qt.MouseButton.RightButton)
        assert calls == []

    def test_margin_to_window_border(self, window):
        from vt_tunnel_gui.views.view import WINDOW_MARGIN

        margins = window.centralWidget().layout().contentsMargins()
        assert (margins.left(), margins.top(), margins.right(),
                margins.bottom()) == (WINDOW_MARGIN,) * 4


# --------------------------------------------------------------------------
# Controller: Check daemon button -> result window
# --------------------------------------------------------------------------


@pytest.fixture
def app(qapp, cfg_path, monkeypatch):
    """An App with two saved connections; daemon results are recorded
    instead of shown modally."""
    from conftest import cfg_text

    cfg_path.write_text(cfg_text(VALID_VALUES, OTHER))
    application = App(cfg_path)
    application.controller.show()
    application.results = []
    monkeypatch.setattr(
        application.main_view,
        "show_daemon_result",
        lambda result, note=None: application.results.append(
            (result, note)
        ),
    )
    yield application
    application.close()


class TestDaemonCheckButton:
    def test_first_connection(self, app, fake_systemd):
        fake_systemd(RUNNING)
        app.main_view.rows[0].check_button.click()
        [(result, note)] = app.results
        assert result.status is Status.WORKING
        assert result.service == SERVICE
        assert note is None

    def test_other_connection_checks_same_service_with_note(
        self, app, fake_systemd
    ):
        logs = fake_systemd(RUNNING)
        app.main_view.rows[1].check_button.click()
        [(result, note)] = app.results
        assert argv(logs, "systemctl")[1] == SERVICE
        assert "connection 2" in note

    def test_failure_shown(self, app, fake_systemd):
        fake_systemd(RUNNING | {"ActiveState": "failed",
                                "Result": "exit-code",
                                "ExecMainStatus": "1"})
        app.main_view.rows[0].check_button.click()
        [(result, _)] = app.results
        assert result.status is Status.FAILED
        assert result.log == JOURNAL

    def test_button_and_cursor_restored(self, app, fake_systemd):
        from PyQt6.QtGui import QGuiApplication
        from vt_tunnel_gui.views.view import CHECK_DAEMON_TEXT

        fake_systemd(RUNNING)
        app.main_view.rows[0].check_button.click()
        assert QGuiApplication.overrideCursor() is None
        assert app.main_view.rows[0].check_button.text() == CHECK_DAEMON_TEXT

    def test_restored_on_crash(self, app, monkeypatch):
        from PyQt6.QtGui import QGuiApplication

        def crash(service):
            raise RuntimeError("boom")

        monkeypatch.setattr(daemon_check, "run_check", crash)
        with pytest.raises(RuntimeError):
            app.controller.on_daemon_check(0)
        assert QGuiApplication.overrideCursor() is None

    def test_does_not_touch_the_editor(self, app, fake_systemd):
        fake_systemd(RUNNING)
        app.main_view.rows[0].check_button.click()
        assert not app.connection_view.isVisible()


# --------------------------------------------------------------------------
# Result window
# --------------------------------------------------------------------------


class TestDaemonResultView:
    @pytest.mark.parametrize(
        "status, headline, level",
        [
            (Status.WORKING, "Working", "OK"),
            (Status.NOT_ENABLED, "Not enabled", "WARNING"),
            (Status.NOT_INSTALLED, "Not installed", "ERROR"),
            (Status.FAILED, "Failed", "ERROR"),
            (Status.UNKNOWN, "Can't check", "WARNING"),
        ],
    )
    def test_verdicts(self, qapp, status, headline, level):
        from vt_tunnel_gui.views.check_result_view import daemon_result_view

        result = daemon_check.DaemonResult(
            status, SERVICE, "msg", JOURNAL, f"systemctl status {SERVICE}"
        )
        view = daemon_result_view(result, "note")
        assert view.headline.text() == f"<b>{SERVICE}: {headline}</b>"
        assert view.level.name == level
        assert view.output.toPlainText() == JOURNAL
        assert view.note.text() == "note"
        assert view.command.text() == f"systemctl status {SERVICE}"
        assert view.isModal()

    def test_log_opens_at_the_newest_lines(self, qapp):
        from vt_tunnel_gui.views.check_result_view import daemon_result_view

        log = "\n".join(f"line {i}" for i in range(1, 41))
        view = daemon_result_view(
            daemon_check.DaemonResult(Status.FAILED, SERVICE, "m", log, "c")
        )
        view.show()
        qapp.processEvents()
        scroll = view.output.verticalScrollBar()
        assert scroll.maximum() > 0
        assert scroll.value() == scroll.maximum()
        view.close()

    def test_wide_log_widens_the_window(self, qapp):
        from vt_tunnel_gui.views.check_result_view import (
            MIN_WIDTH,
            daemon_result_view,
        )

        def width(log):
            return daemon_result_view(daemon_check.DaemonResult(
                Status.FAILED, SERVICE, "m", log, "c"
            )).width()

        assert width("short") == MIN_WIDTH
        assert width(JOURNAL) > MIN_WIDTH


class TestRowLayout:
    @pytest.mark.parametrize("width", [620, 420])
    def test_rows_fit_the_list(self, window, qapp, width):
        window.resize(width, 320)
        qapp.processEvents()
        viewport = window.connection_list.viewport()
        assert not window.connection_list.horizontalScrollBar().isVisible()
        for row in window.rows:
            for button in (row.check_button, row.edit_button):
                right = button.mapTo(viewport, button.rect().topRight()).x()
                assert right <= viewport.width()

    def test_long_name_is_elided_with_tooltip(self, qapp):
        from vt_tunnel_gui.views.view import MainWindow

        name = "a-very-long-connection-name-" * 10
        view = MainWindow()
        view.set_connections([{"NAME": name}])
        view.show()
        qapp.processEvents()
        label = view.rows[0].name_label
        assert label.width() < label.fontMetrics().horizontalAdvance(name)
        label.repaint()
        assert label.toolTip() == name
        assert not view.connection_list.horizontalScrollBar().isVisible()
        view.close()


class TestSuggestions:
    def test_not_installed_has_none(self, fake_systemd):
        fake_systemd(NOT_FOUND)
        assert run_check(SERVICE).suggestions == ()

    def test_working_and_enabled_needs_nothing(self, fake_systemd):
        fake_systemd(RUNNING)
        assert run_check(SERVICE).suggestions == ()

    def test_working_but_not_enabled(self, fake_systemd):
        fake_systemd(RUNNING | {"UnitFileState": "disabled"})
        assert commands(run_check(SERVICE)) == [ENABLE]

    def test_failed_points_to_the_ssh_check_then_restart(self, fake_systemd):
        fake_systemd(RUNNING | {"ActiveState": "failed",
                                "Result": "exit-code",
                                "ExecMainStatus": "1"})
        result = run_check(SERVICE)
        assert commands(result) == ["", RESTART]
        advice = result.suggestions[0].text
        assert "without a password" in advice
        assert "Check connection" in advice and "Edit" in advice

    def test_failed_and_not_enabled(self, fake_systemd):
        fake_systemd(RUNNING | {"ActiveState": "failed",
                                "UnitFileState": "disabled",
                                "Result": "exit-code"})
        assert commands(run_check(SERVICE)) == ["", RESTART, ENABLE]

    def test_restart_loop_points_to_the_ssh_check(self, fake_systemd):
        fake_systemd(RUNNING | {"ActiveState": "activating",
                                "SubState": "auto-restart"})
        result = run_check(SERVICE)
        assert commands(result) == [""]
        assert result.suggestions[0].text == daemon_check.CHECK_SSH_ADVICE

    def test_enabled_but_stopped_suggests_start(self, fake_systemd):
        fake_systemd(RUNNING | {"ActiveState": "inactive",
                                "SubState": "dead"})
        assert commands(run_check(SERVICE)) == [START]

    def test_bad_unit_file_suggests_daemon_reload(self, fake_systemd):
        fake_systemd(RUNNING | {"LoadState": "bad-setting",
                                "ActiveState": "inactive"})
        assert commands(run_check(SERVICE)) == [
            "sudo systemctl daemon-reload"
        ]

    def test_cannot_check_has_none(self, fake_systemd):
        fake_systemd(show_body="exit 1")
        assert run_check(SERVICE).suggestions == ()

    def test_shown_in_the_result_window(self, qapp, fake_systemd):
        from vt_tunnel_gui.views.check_result_view import daemon_result_view

        fake_systemd(RUNNING | {"ActiveState": "inactive",
                                "SubState": "dead",
                                "UnitFileState": "disabled"})
        view = daemon_result_view(run_check(SERVICE))
        assert [f.line.text() for f in view.suggestion_commands] == [
            ENABLE, START
        ]
