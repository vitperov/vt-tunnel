"""Tests of the connection check: the ssh run, its result, and the GUI.

A fake ``ssh`` (a shell script) is put first on PATH, so the real
subprocess code runs, just against a scripted "server".
"""

import shlex
import time

import pytest

from conftest import VALID_VALUES, App
from vt_tunnel_gui.models import ssh_check, ssh_keys
from vt_tunnel_gui.models.ssh_check import MARKER, Outcome, run_check

USER = VALID_VALUES["REMOTE_USER"]
SERVER = VALID_VALUES["REMOTE_SERVER"]
PORT = VALID_VALUES["REMOTE_SERVER_SSH_PORT"]
EXPECTED_COMMAND = (
    f"ssh -o BatchMode=yes -o ConnectTimeout=10 -p 22 {USER}@{SERVER} "
    f"'echo {MARKER}'"
)


def server_ok() -> str:
    return f"echo {MARKER}"


class TestCommand:
    def test_command_line(self):
        argv = ssh_check.ssh_command(USER, SERVER, PORT)
        assert shlex.join(argv) == EXPECTED_COMMAND

    def test_no_password_prompts(self):
        # The point of the check: key only, like the daemon.
        assert "BatchMode=yes" in ssh_check.ssh_command(USER, SERVER, PORT)

    def test_ssh_gets_these_arguments(self, fake_ssh):
        log = fake_ssh(server_ok())
        run_check(USER, SERVER, PORT)
        assert log.read_text().splitlines() == [
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-p", "22",
            f"{USER}@{SERVER}",
            f"echo {MARKER}",
        ]

    def test_result_has_copyable_command(self, fake_ssh):
        fake_ssh(server_ok())
        assert run_check(USER, SERVER, PORT).command == EXPECTED_COMMAND


class TestOutcome:
    def test_ok(self, fake_ssh):
        fake_ssh(server_ok())
        result = run_check(USER, SERVER, PORT)
        assert result.outcome is Outcome.OK
        assert f"{USER}@{SERVER}" in result.message
        assert result.output == ""

    def test_ok_despite_login_noise(self, fake_ssh):
        # e.g. a chatty .bashrc on the server, warnings from ssh
        fake_ssh(
            "echo 'Welcome!'; echo 'Warning: Permanently added' >&2; "
            + server_ok()
        )
        result = run_check(USER, SERVER, PORT)
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
        result = run_check(USER, SERVER, PORT)
        assert result.outcome is Outcome.FAILED
        assert result.output == error
        assert "255" in result.message

    def test_ssh_error_without_message(self, fake_ssh):
        fake_ssh("exit 255")
        result = run_check(USER, SERVER, PORT)
        assert result.outcome is Outcome.FAILED
        assert result.output == ssh_check.NO_OUTPUT

    def test_logged_in_but_command_failed(self, fake_ssh):
        fake_ssh("echo 'This account is restricted' >&2; exit 1")
        result = run_check(USER, SERVER, PORT)
        assert result.outcome is Outcome.COMMAND_FAILED
        assert "exit code 1" in result.message
        assert result.output == "This account is restricted"

    def test_exit_0_without_marker_is_not_ok(self, fake_ssh):
        fake_ssh("echo something-else")
        result = run_check(USER, SERVER, PORT)
        assert result.outcome is Outcome.COMMAND_FAILED
        assert result.output == "something-else"

    def test_marker_must_be_a_whole_word(self, fake_ssh):
        fake_ssh(f"echo not-{MARKER}-really")
        assert run_check(USER, SERVER, PORT).outcome is Outcome.COMMAND_FAILED

    def test_ssh_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))  # no ssh there
        result = run_check(USER, SERVER, PORT)
        assert result.outcome is Outcome.FAILED
        assert "not found" in result.message
        assert result.command == EXPECTED_COMMAND

    def test_undecodable_output(self, fake_ssh):
        fake_ssh(r"printf 'bad \xff byte\n' >&2; exit 255")
        result = run_check(USER, SERVER, PORT)
        assert result.output == "bad \ufffd byte"


class TestTimeout:
    def test_hanging_ssh_is_stopped(self, fake_ssh):
        fake_ssh("echo 'partial message' >&2; sleep 30")
        start = time.monotonic()
        result = run_check(USER, SERVER, PORT, timeout=0.5)
        assert time.monotonic() - start < 5
        assert result.outcome is Outcome.FAILED
        assert "0.5 seconds" in result.message
        assert result.output == "partial message"

    def test_child_holding_the_pipes_is_stopped_too(self, fake_ssh):
        # Like a ProxyCommand: a child that inherits ssh's stdout/stderr.
        fake_ssh("sleep 30 & wait")
        start = time.monotonic()
        result = run_check(USER, SERVER, PORT, timeout=0.5)
        assert time.monotonic() - start < 5
        assert result.outcome is Outcome.FAILED

    def test_default_timeout_is_10_seconds(self):
        assert ssh_check.CHECK_TIMEOUT_S == 10

    def test_ssh_cannot_wait_for_input(self, fake_ssh):
        # stdin is /dev/null: a read ends at once instead of hanging.
        fake_ssh(f"cat; {server_ok()}")
        assert run_check(USER, SERVER, PORT, timeout=5).outcome is Outcome.OK


def commands(result) -> list[str]:
    return [x.command for x in result.suggestions]


COPY_ID = f"ssh-copy-id -p 22 {USER}@{SERVER}"


class TestKeyFirst:
    """The check looks for a key (ssh_keys) before it tries to log in."""

    def test_no_key_skips_the_login(self, fake_ssh):
        log = fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER, PORT)
        assert result.outcome is Outcome.NO_KEY
        assert not log.exists()  # ssh was never asked to log in
        assert "~/.ssh/id_ed25519" in result.message
        assert result.command == EXPECTED_COMMAND

    def test_no_key_suggests_keygen_then_copy_id(self, fake_ssh):
        fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER, PORT)
        assert commands(result) == [ssh_keys.KEYGEN_COMMAND, COPY_ID]
        assert "passphrase empty" in result.suggestions[0].text

    def test_with_a_key_it_logs_in(self, fake_ssh, key):
        log = fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER, PORT)
        assert result.outcome is Outcome.OK
        assert log.exists()
        assert result.suggestions == ()

    def test_key_in_agent_is_enough(self, fake_ssh):
        log = fake_ssh(server_ok(), agent_exit=0)
        assert ssh_check.check(USER, SERVER, PORT).outcome is Outcome.OK
        assert log.exists()

    def test_ssh_missing_reports_ssh_not_key(self, tmp_path, monkeypatch,
                                             home):
        monkeypatch.setenv("PATH", str(tmp_path))  # no ssh at all
        result = ssh_check.check(USER, SERVER, PORT)
        assert result.outcome is Outcome.FAILED
        assert "not found" in result.message
        assert commands(result) == ["sudo apt install openssh-client"]


class TestSuggestions:
    def run(self, fake_ssh, stderr, code=255):
        fake_ssh(f"echo {shlex.quote(stderr)} >&2; exit {code}")
        return ssh_check.check(USER, SERVER, PORT)

    def test_permission_denied_suggests_copy_id(self, fake_ssh, key):
        result = self.run(
            fake_ssh, f"{USER}@{SERVER}: Permission denied (publickey)."
        )
        assert commands(result) == [COPY_ID]
        assert "doesn't accept your key" in result.suggestions[0].text

    def test_unknown_host_key(self, fake_ssh, key):
        result = self.run(fake_ssh, "Host key verification failed.")
        assert commands(result) == [f"ssh -p 22 {USER}@{SERVER}"]
        assert "fingerprint" in result.suggestions[0].text

    def test_changed_host_key_warns(self, fake_ssh, key):
        result = self.run(
            fake_ssh,
            "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@\n"
            "Host key verification failed.",
        )
        assert commands(result) == [
            f"ssh-keygen -R {SERVER}", f"ssh -p 22 {USER}@{SERVER}"
        ]
        assert "intercepting" in result.suggestions[0].text
        assert result.suggestions[1].text.startswith("Then connect once")

    def test_unknown_host_name(self, fake_ssh, key):
        result = self.run(
            fake_ssh,
            f"ssh: Could not resolve hostname {SERVER}: Name or service "
            "not known",
        )
        assert commands(result) == [""]  # advice, nothing to run
        assert "REMOTE_SERVER" in result.suggestions[0].text

    @pytest.mark.parametrize("error", [
        "Connection refused", "Connection timed out", "No route to host",
        "Network is unreachable",
    ])
    def test_unreachable(self, fake_ssh, key, error):
        result = self.run(
            fake_ssh, f"ssh: connect to host {SERVER} port 22: {error}"
        )
        assert commands(result) == [""]
        assert "can't be reached" in result.suggestions[0].text

    def test_timeout(self, fake_ssh, key):
        fake_ssh("sleep 30")
        result = ssh_check.check(USER, SERVER, PORT, timeout=0.5)
        assert "can't be reached" in result.suggestions[0].text

    def test_other_error_suggests_copy_id(self, fake_ssh, key):
        result = self.run(fake_ssh, "Something unexpected")
        assert commands(result) == [COPY_ID]

    def test_command_failed_has_no_suggestions(self, fake_ssh, key):
        result = self.run(fake_ssh, "restricted", code=1)
        assert result.outcome is Outcome.COMMAND_FAILED
        assert result.suggestions == ()


# --------------------------------------------------------------------------
# GUI: the Check button in the editor and the result window
# --------------------------------------------------------------------------


@pytest.fixture
def editor(qapp, config_dir, monkeypatch, key):
    """An App with the editor open on a new connection filled with valid
    values (and the user has a key); check results are recorded instead of
    shown modally."""
    app = App(config_dir)
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

    def test_check_does_not_save(self, editor, fake_ssh, config_dir):
        fake_ssh(server_ok())
        editor.connection_view.check_button.click()
        assert list(config_dir.iterdir()) == []

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

    def test_no_key_is_reported_without_login(self, editor, fake_ssh, key):
        key.unlink()
        log = fake_ssh(server_ok())
        editor.connection_view.check_button.click()
        [(result, _)] = editor.results
        assert result.outcome is Outcome.NO_KEY
        assert not log.exists()

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

        monkeypatch.setattr(ssh_check, "check", crash)
        with pytest.raises(RuntimeError):
            editor.controller.on_check()
        assert QGuiApplication.overrideCursor() is None


class TestResultView:
    @pytest.fixture
    def make_view(self, qapp):
        from vt_tunnel_gui.views.check_result_view import ssh_result_view

        views = []

        def make(outcome, output="", note=None, suggestions=()):
            result = ssh_check.CheckResult(
                outcome, "the message", output, EXPECTED_COMMAND,
                tuple(suggestions),
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

    def test_suggestions_shown_with_copyable_commands(self, make_view):
        from PyQt6.QtGui import QGuiApplication
        from vt_tunnel_gui.models.advice import Suggestion

        view = make_view(Outcome.NO_KEY, suggestions=[
            Suggestion("Create a key.", "ssh-keygen -t ed25519"),
            Suggestion("Just advice."),
            Suggestion("Copy it.", COPY_ID),
        ])
        assert [x.text() for x in view.suggestion_labels] == [
            "Create a key.", "Just advice.", "Copy it."
        ]
        assert [f.line.text() for f in view.suggestion_commands] == [
            "ssh-keygen -t ed25519", COPY_ID
        ]
        view.suggestion_commands[1].copy_button.click()
        assert QGuiApplication.clipboard().text() == COPY_ID
        assert view.command.text() == EXPECTED_COMMAND  # still there

    def test_no_suggestions_section_without_suggestions(self, make_view):
        view = make_view(Outcome.OK)
        assert view.suggestion_labels == []
        assert view.suggestion_commands == []

    def test_no_key_verdict(self, make_view):
        view = make_view(Outcome.NO_KEY)
        assert "No SSH key" in view.headline.text()
        assert view.level.name == "ERROR"

    def test_long_suggested_command_widens_window(self, make_view):
        from vt_tunnel_gui.models.advice import Suggestion

        long = "ssh-copy-id " + "x" * 90 + "@example.com"
        plain = make_view(Outcome.FAILED).width()
        wide = make_view(
            Outcome.FAILED, suggestions=[Suggestion("t", long)]
        ).width()
        assert wide > plain


# --------------------------------------------------------------------------
# A non-standard SSH port (REMOTE_SERVER_SSH_PORT)
# --------------------------------------------------------------------------


class TestCustomPort:
    def run(self, fake_ssh, stderr, port="2222"):
        fake_ssh(f"echo {shlex.quote(stderr)} >&2; exit 255")
        return ssh_check.check(USER, SERVER, port)

    def test_login_uses_the_port(self, fake_ssh, key):
        log = fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER, "2222")
        assert result.outcome is Outcome.OK
        argv = log.read_text().splitlines()
        assert argv[argv.index("-p") + 1] == "2222"
        assert argv.index("-p") < argv.index(f"{USER}@{SERVER}")
        assert "-p 2222" in result.command

    def test_copy_id_uses_the_port(self, fake_ssh, key):
        result = self.run(fake_ssh, "Permission denied (publickey).")
        assert commands(result) == [f"ssh-copy-id -p 2222 {USER}@{SERVER}"]

    def test_no_key_suggestion_uses_the_port(self, fake_ssh):
        fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER, "2222")
        assert commands(result)[1] == f"ssh-copy-id -p 2222 {USER}@{SERVER}"

    def test_first_login_uses_the_port(self, fake_ssh, key):
        result = self.run(fake_ssh, "Host key verification failed.")
        assert commands(result) == [f"ssh -p 2222 {USER}@{SERVER}"]

    def test_changed_host_key_names_host_and_port(self, fake_ssh, key):
        # known_hosts stores non-22 hosts as [host]:port
        result = self.run(
            fake_ssh,
            "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\n"
            "Host key verification failed.",
        )
        assert commands(result)[0] == f"ssh-keygen -R '[{SERVER}]:2222'"

    def test_unreachable_names_the_port(self, fake_ssh, key):
        result = self.run(
            fake_ssh, f"ssh: connect to host {SERVER} port 2222: "
                      "Connection refused",
        )
        assert "port 2222" in result.suggestions[0].text
        assert "REMOTE_SERVER_SSH_PORT" in result.suggestions[0].text

    def test_timeout_message_names_the_port(self, fake_ssh, key):
        fake_ssh("sleep 30")
        result = ssh_check.check(USER, SERVER, "2222", timeout=0.5)
        assert "port 2222" in result.message

    @pytest.mark.parametrize("port, name", [
        ("22", SERVER), ("2222", f"[{SERVER}]:2222"),
    ])
    def test_known_hosts_name(self, port, name):
        assert ssh_check.known_hosts_name(SERVER, port) == name


class TestPortInTheEditor:
    def test_custom_port_from_the_form(self, editor, fake_ssh):
        log = fake_ssh(server_ok())
        edits = editor.connection_view._line_edits
        port_edit = edits["REMOTE_SERVER_SSH_PORT"]
        port_edit.setText("2222")
        editor.connection_view.check_button.click()
        argv = log.read_text().splitlines()
        assert argv[argv.index("-p") + 1] == "2222"

    @pytest.mark.parametrize("value", [
        "", "22 -oProxyCommand=reboot", "-oProxyCommand=reboot", "0",
        "65536",
    ])
    def test_invalid_port_never_reaches_ssh(self, editor, fake_ssh, value):
        log = fake_ssh(server_ok())
        edits = editor.connection_view._line_edits
        port_edit = edits["REMOTE_SERVER_SSH_PORT"]
        port_edit.setText(value)
        editor.connection_view.check_button.click()
        assert not log.exists()
        [(_, text)] = editor.errors
        assert text.startswith("REMOTE_SERVER_SSH_PORT:")
