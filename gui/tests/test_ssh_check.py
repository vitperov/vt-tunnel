"""Tests of the connection check: the ssh run, its result, and the GUI.

A fake ``ssh`` (a shell script) is put first on PATH, so the real
subprocess code runs, just against a scripted "server".
"""

import getpass
import shlex
import stat
import time
from pathlib import Path

import pytest

from conftest import VALID_VALUES, App
from vt_tunnel_gui.models import ssh_check
from vt_tunnel_gui.models.ssh_check import MARKER, Outcome, run_check

USER = VALID_VALUES["REMOTE_USER"]
SERVER = VALID_VALUES["REMOTE_SERVER"]
EXPECTED_COMMAND = (
    f"ssh -o BatchMode=yes -o ConnectTimeout=10 {USER}@{SERVER} "
    f"'echo {MARKER}'"
)


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """Install ``ssh`` running the given bash ``body``; it logs its argv
    (one per line) to the returned file on every call."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "ssh-argv"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    def install(body: str) -> Path:
        script = bin_dir / "ssh"
        script.write_text(
            "#!/bin/bash\n"
            f"printf '%s\\n' \"$@\" > {shlex.quote(str(log))}\n"
            f"{body}\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return log

    return install


def server_ok() -> str:
    return f"echo {MARKER}"


class TestCommand:
    def test_command_line(self):
        argv = ssh_check.ssh_command(USER, SERVER)
        assert shlex.join(argv) == EXPECTED_COMMAND

    def test_no_password_prompts(self):
        # The point of the check: key only, like the daemon.
        assert "BatchMode=yes" in ssh_check.ssh_command(USER, SERVER)

    def test_ssh_gets_these_arguments(self, fake_ssh):
        log = fake_ssh(server_ok())
        run_check(USER, SERVER)
        assert log.read_text().splitlines() == [
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            f"{USER}@{SERVER}",
            f"echo {MARKER}",
        ]

    def test_result_has_copyable_command(self, fake_ssh):
        fake_ssh(server_ok())
        assert run_check(USER, SERVER).command == EXPECTED_COMMAND


class TestOutcome:
    def test_ok(self, fake_ssh):
        fake_ssh(server_ok())
        result = run_check(USER, SERVER)
        assert result.outcome is Outcome.OK
        assert f"{USER}@{SERVER}" in result.message
        assert result.output == ""

    def test_ok_despite_login_noise(self, fake_ssh):
        # e.g. a chatty .bashrc on the server, warnings from ssh
        fake_ssh(
            "echo 'Welcome!'; echo 'Warning: Permanently added' >&2; "
            + server_ok()
        )
        result = run_check(USER, SERVER)
        assert result.outcome is Outcome.OK
        assert result.output == "Warning: Permanently added"

    @pytest.mark.parametrize(
        "error",
        [
            f"{USER}@{SERVER}: Permission denied (publickey,password).",
            "Host key verification failed.",
            f"ssh: Could not resolve hostname {SERVER}: "
            "Name or service not known",
            f"ssh: connect to host {SERVER} port 22: Connection refused",
        ],
    )
    def test_ssh_error_is_shown_verbatim(self, fake_ssh, error):
        fake_ssh(f"echo {shlex.quote(error)} >&2; exit 255")
        result = run_check(USER, SERVER)
        assert result.outcome is Outcome.FAILED
        assert result.output == error
        assert "255" in result.message

    def test_ssh_error_without_message(self, fake_ssh):
        fake_ssh("exit 255")
        result = run_check(USER, SERVER)
        assert result.outcome is Outcome.FAILED
        assert result.output == ssh_check.NO_OUTPUT

    def test_logged_in_but_command_failed(self, fake_ssh):
        fake_ssh("echo 'This account is restricted' >&2; exit 1")
        result = run_check(USER, SERVER)
        assert result.outcome is Outcome.COMMAND_FAILED
        assert "exit code 1" in result.message
        assert result.output == "This account is restricted"

    def test_exit_0_without_marker_is_not_ok(self, fake_ssh):
        fake_ssh("echo something-else")
        result = run_check(USER, SERVER)
        assert result.outcome is Outcome.COMMAND_FAILED
        assert result.output == "something-else"

    def test_marker_must_be_a_whole_word(self, fake_ssh):
        fake_ssh(f"echo not-{MARKER}-really")
        assert run_check(USER, SERVER).outcome is Outcome.COMMAND_FAILED

    def test_ssh_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))  # no ssh there
        result = run_check(USER, SERVER)
        assert result.outcome is Outcome.FAILED
        assert "not found" in result.message
        assert result.command == EXPECTED_COMMAND

    def test_undecodable_output(self, fake_ssh):
        fake_ssh(r"printf 'bad \xff byte\n' >&2; exit 255")
        result = run_check(USER, SERVER)
        assert result.output == "bad \ufffd byte"


class TestTimeout:
    def test_hanging_ssh_is_stopped(self, fake_ssh):
        fake_ssh("echo 'partial message' >&2; sleep 30")
        start = time.monotonic()
        result = run_check(USER, SERVER, timeout=0.5)
        assert time.monotonic() - start < 5
        assert result.outcome is Outcome.FAILED
        assert "0.5 seconds" in result.message
        assert result.output == "partial message"

    def test_child_holding_the_pipes_is_stopped_too(self, fake_ssh):
        # Like a ProxyCommand: a child that inherits ssh's stdout/stderr.
        fake_ssh("sleep 30 & wait")
        start = time.monotonic()
        result = run_check(USER, SERVER, timeout=0.5)
        assert time.monotonic() - start < 5
        assert result.outcome is Outcome.FAILED

    def test_default_timeout_is_10_seconds(self):
        assert ssh_check.CHECK_TIMEOUT_S == 10

    def test_ssh_cannot_wait_for_input(self, fake_ssh):
        # stdin is /dev/null: a read ends at once instead of hanging.
        fake_ssh(f"cat; {server_ok()}")
        assert run_check(USER, SERVER, timeout=5).outcome is Outcome.OK


class TestLocalUserNote:
    def test_same_user(self):
        assert ssh_check.local_user_note(getpass.getuser()) is None

    def test_empty(self):
        assert ssh_check.local_user_note("") is None

    def test_other_user(self):
        note = ssh_check.local_user_note("tunnel-user")
        assert "tunnel-user" in note
        assert getpass.getuser() in note

    def test_unknown_current_user(self, monkeypatch):
        def fail():
            raise OSError("no user")

        monkeypatch.setattr(ssh_check.getpass, "getuser", fail)
        assert ssh_check.local_user_note("tunnel-user") is None


# --------------------------------------------------------------------------
# GUI: the Check button in the editor and the result window
# --------------------------------------------------------------------------


@pytest.fixture
def editor(qapp, cfg_path, monkeypatch):
    """An App with the editor open on a new connection filled with valid
    values; check results are recorded instead of shown modally."""
    app = App(cfg_path)
    app.controller.show()
    app.main_view.add_requested.emit()
    app.connection_view.set_values(dict(VALID_VALUES))
    app.results = []
    monkeypatch.setattr(
        app.connection_view,
        "show_check_result",
        lambda result, note=None: app.results.append((result, note)),
    )
    app.errors = []
    monkeypatch.setattr(
        app.connection_view,
        "show_error",
        lambda title, text: app.errors.append((title, text)),
    )
    yield app
    app.close()


class TestCheckButton:
    def test_button_runs_check_with_form_values(self, editor, fake_ssh):
        log = fake_ssh(server_ok())
        editor.connection_view._line_edits["REMOTE_USER"].setText("petya")
        editor.connection_view.check_button.click()
        assert f"petya@{SERVER}" in log.read_text().splitlines()
        [(result, _)] = editor.results
        assert result.outcome is Outcome.OK

    def test_check_does_not_save(self, editor, fake_ssh, cfg_path):
        fake_ssh(server_ok())
        editor.connection_view.check_button.click()
        assert not cfg_path.exists()

    def test_failure_is_reported(self, editor, fake_ssh):
        fake_ssh("echo 'Permission denied (publickey).' >&2; exit 255")
        editor.connection_view.check_button.click()
        [(result, _)] = editor.results
        assert result.outcome is Outcome.FAILED
        assert result.output == "Permission denied (publickey)."

    @pytest.mark.parametrize(
        "key, value",
        [
            ("REMOTE_USER", "-oProxyCommand=reboot"),
            ("REMOTE_USER", ""),
            ("REMOTE_SERVER", "evil.com;reboot"),
            ("REMOTE_SERVER", ""),
        ],
    )
    def test_invalid_values_never_reach_ssh(
        self, editor, fake_ssh, key, value
    ):
        log = fake_ssh(server_ok())
        editor.connection_view._line_edits[key].setText(value)
        editor.connection_view.check_button.click()
        assert not log.exists()
        assert editor.results == []
        [(title, text)] = editor.errors
        assert text.startswith(f"{key}:")

    def test_other_invalid_fields_dont_block_check(self, editor, fake_ssh):
        fake_ssh(server_ok())
        editor.connection_view._line_edits["LOCAL_PORT"].setText("nope")
        editor.connection_view.check_button.click()
        assert editor.errors == []
        assert len(editor.results) == 1

    def test_note_when_tunnel_runs_as_other_user(self, editor, fake_ssh):
        fake_ssh(server_ok())
        editor.connection_view._line_edits["RUN_DAEMON_USER"].setText(
            "tunnel-user"
        )
        editor.connection_view.check_button.click()
        [(_, note)] = editor.results
        assert "tunnel-user" in note

    def test_busy_cursor_is_restored(self, editor, fake_ssh):
        from PyQt6.QtGui import QGuiApplication

        fake_ssh(server_ok())
        editor.connection_view.check_button.click()
        assert QGuiApplication.overrideCursor() is None

    def test_busy_cursor_is_restored_on_crash(
        self, editor, fake_ssh, monkeypatch
    ):
        from PyQt6.QtGui import QGuiApplication

        def crash(*args):
            raise RuntimeError("boom")

        monkeypatch.setattr(ssh_check, "run_check", crash)
        with pytest.raises(RuntimeError):
            editor.controller.on_check()
        assert QGuiApplication.overrideCursor() is None


class TestResultView:
    @pytest.fixture
    def make_view(self, qapp):
        from vt_tunnel_gui.views.check_result_view import ssh_result_view

        views = []

        def make(outcome, output="", note=None):
            result = ssh_check.CheckResult(
                outcome, "the message", output, EXPECTED_COMMAND
            )
            view = ssh_result_view(result, note)
            views.append(view)
            return view

        yield make
        for view in views:
            view.close()

    @pytest.mark.parametrize("outcome", list(Outcome))
    def test_every_outcome(self, make_view, outcome):
        view = make_view(outcome)
        assert view.isModal()
        assert view.message.text() == "the message"
        assert view.command.text() == EXPECTED_COMMAND
        assert view.command.isReadOnly()

    def test_ok_and_failure_headlines_differ(self, make_view):
        ok = make_view(Outcome.OK).headline.text()
        failed = make_view(Outcome.FAILED).headline.text()
        assert "OK" in ok
        assert "failed" in failed

    def test_output_shown_verbatim(self, make_view):
        view = make_view(Outcome.FAILED, "Permission denied (publickey).")
        assert view.output.toPlainText() == "Permission denied (publickey)."
        assert view.output.isReadOnly()

    def test_no_output_box_without_output(self, make_view):
        assert make_view(Outcome.OK).output is None

    def test_note(self, make_view):
        assert make_view(Outcome.OK, note="the note").note.text() == (
            "the note"
        )
        assert make_view(Outcome.OK).note is None

    def test_copy_puts_command_on_clipboard(self, make_view):
        from PyQt6.QtGui import QGuiApplication

        make_view(Outcome.FAILED).copy_button.click()
        assert QGuiApplication.clipboard().text() == EXPECTED_COMMAND
