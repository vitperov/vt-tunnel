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


# What `ssh -G` prints for identity files without IdentityFile in the
# config (OpenSSH 9; other lines left out).
DEFAULT_G_OUTPUT = "".join(
    f"identityfile {name}\n" for name in ssh_check.DEFAULT_IDENTITY_FILES
)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A fresh home directory with an empty ~/.ssh (no keys)."""
    path = tmp_path / "home"
    (path / ".ssh").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def key(home) -> Path:
    """A private key at ~/.ssh/id_ed25519."""
    path = home / ".ssh" / "id_ed25519"
    path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    (home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAA x\n")
    return path


def _script(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_ssh(tmp_path, home, monkeypatch):
    """Install ``ssh`` running the given bash ``body`` for a login; it logs
    the login's argv (one per line) to the returned file.

    ``ssh -G`` (the key lookup) prints ``g_output`` and exits with
    ``g_exit``; ``ssh-add -l`` exits with ``agent_exit`` (2: no agent).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "ssh-argv"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    def install(
        body: str,
        g_output: str = DEFAULT_G_OUTPUT,
        g_exit: int = 0,
        agent_exit: int = 2,
    ) -> Path:
        _script(
            bin_dir / "ssh",
            'if [ "$1" = -G ]; then\n'
            f"  printf %s {shlex.quote(g_output)}; exit {g_exit}\n"
            "fi\n"
            f"printf '%s\\n' \"$@\" > {shlex.quote(str(log))}\n"
            f"{body}",
        )
        _script(bin_dir / "ssh-add", f"exit {agent_exit}")
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


def commands(result) -> list[str]:
    return [x.command for x in result.suggestions]


COPY_ID = f"ssh-copy-id {USER}@{SERVER}"


class TestKeyLookup:
    def test_no_key_skips_the_login(self, fake_ssh):
        log = fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER)
        assert result.outcome is Outcome.NO_KEY
        assert not log.exists()  # ssh was never asked to log in
        assert "~/.ssh/id_ed25519" in result.message
        assert result.command == EXPECTED_COMMAND

    def test_no_key_suggests_keygen_then_copy_id(self, fake_ssh):
        fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER)
        assert commands(result) == [ssh_check.KEYGEN_COMMAND, COPY_ID]
        assert "passphrase empty" in result.suggestions[0].text

    def test_key_file_found(self, fake_ssh, key):
        log = fake_ssh(server_ok())
        result = ssh_check.check(USER, SERVER)
        assert result.outcome is Outcome.OK
        assert log.exists()
        assert result.suggestions == ()

    def test_public_key_alone_is_no_key(self, fake_ssh, home):
        (home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAA\n")
        fake_ssh(server_ok())
        assert ssh_check.check(USER, SERVER).outcome is Outcome.NO_KEY

    def test_key_in_agent_is_enough(self, fake_ssh):
        log = fake_ssh(server_ok(), agent_exit=0)
        assert ssh_check.check(USER, SERVER).outcome is Outcome.OK
        assert log.exists()

    @pytest.mark.parametrize("agent_exit", [1, 2])  # no keys / no agent
    def test_agent_without_keys(self, fake_ssh, agent_exit):
        fake_ssh(server_ok(), agent_exit=agent_exit)
        assert ssh_check.check(USER, SERVER).outcome is Outcome.NO_KEY

    def test_identity_file_from_ssh_config(self, fake_ssh, home):
        # `IdentityFile ~/.ssh/tunnel` in ~/.ssh/config: ssh -G lists it
        (home / ".ssh" / "tunnel").write_text("key")
        fake_ssh(server_ok(), g_output="identityfile ~/.ssh/tunnel\n")
        keys = ssh_check.find_keys(USER, SERVER)
        assert keys.files == (home / ".ssh" / "tunnel",)

    def test_only_the_configured_identity_file_counts(self, fake_ssh, key):
        # IdentityFile set: the default id_ed25519 is not what ssh uses
        fake_ssh(server_ok(), g_output="identityfile ~/.ssh/tunnel\n")
        assert ssh_check.check(USER, SERVER).outcome is Outcome.NO_KEY

    def test_tokens_in_identity_file(self, fake_ssh, home):
        (home / ".ssh" / f"id_{USER}_{SERVER}").write_text("key")
        fake_ssh(server_ok(), g_output="identityfile %d/.ssh/id_%r_%h\n")
        assert ssh_check.find_keys(USER, SERVER).files == (
            home / ".ssh" / f"id_{USER}_{SERVER}",
        )

    def test_ssh_config_error_falls_back_to_defaults(self, fake_ssh, key):
        fake_ssh(server_ok(), g_output="", g_exit=255)
        keys = ssh_check.find_keys(USER, SERVER)
        assert keys.files == (key,)

    def test_ssh_missing_reports_ssh_not_key(self, tmp_path, monkeypatch,
                                             home):
        monkeypatch.setenv("PATH", str(tmp_path))  # no ssh at all
        result = ssh_check.check(USER, SERVER)
        assert result.outcome is Outcome.FAILED
        assert "not found" in result.message
        assert commands(result) == ["sudo apt install openssh-client"]


class TestSuggestions:
    def run(self, fake_ssh, stderr, code=255):
        fake_ssh(f"echo {shlex.quote(stderr)} >&2; exit {code}")
        return ssh_check.check(USER, SERVER)

    def test_permission_denied_suggests_copy_id(self, fake_ssh, key):
        result = self.run(
            fake_ssh, f"{USER}@{SERVER}: Permission denied (publickey)."
        )
        assert commands(result) == [COPY_ID]
        assert "doesn't accept your key" in result.suggestions[0].text

    def test_unknown_host_key(self, fake_ssh, key):
        result = self.run(fake_ssh, "Host key verification failed.")
        assert commands(result) == [f"ssh {USER}@{SERVER}"]
        assert "fingerprint" in result.suggestions[0].text

    def test_changed_host_key_warns(self, fake_ssh, key):
        result = self.run(
            fake_ssh,
            "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@\n"
            "Host key verification failed.",
        )
        assert commands(result) == [
            f"ssh-keygen -R {SERVER}", f"ssh {USER}@{SERVER}"
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
        result = ssh_check.check(USER, SERVER, timeout=0.5)
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
def editor(qapp, cfg_path, monkeypatch, key):
    """An App with the editor open on a new connection filled with valid
    values (and the user has a key); check results are recorded instead of
    shown modally."""
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
