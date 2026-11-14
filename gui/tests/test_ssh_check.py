"""Tests for the ssh login check and the suggestion record."""

import inspect
import time

from vt_tunnel_gui.models import ssh_check


def _give_key(fake_home):
    """Put a private key where the discovery's defaults look."""
    key = fake_home / ".ssh" / "id_ed25519"
    key.write_text("")
    return key


def _ok_body():
    return f"echo {ssh_check.MARKER}"


class TestCommand:
    """The command the check runs."""

    def test_command_line_shape(self, fake_ssh, fake_home):
        """The login is one ssh call with BatchMode, timeout and port."""
        _give_key(fake_home)
        fake_ssh.set_login_body(_ok_body())

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert fake_ssh.login_argv == [
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-p",
            "22",
            "user@srv.example.org",
            "echo",
            ssh_check.MARKER,
        ]
        assert result.command == (
            "ssh -o BatchMode=yes -o ConnectTimeout=10 -p 22 "
            "user@srv.example.org echo " + ssh_check.MARKER
        )

    def test_no_password_prompts(self, fake_ssh, fake_home):
        """BatchMode is on the command line: ssh can never prompt."""
        _give_key(fake_home)
        fake_ssh.set_login_body(_ok_body())

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert "BatchMode=yes" in fake_ssh.login_argv
        assert result.outcome == ssh_check.OK

    def test_ssh_receives_exactly_these_arguments(self, fake_ssh, fake_home):
        """No extra arguments beyond the fixed shape."""
        _give_key(fake_home)
        fake_ssh.set_login_body(_ok_body())

        ssh_check.check_login("user", "srv.example.org", "22")

        assert len(fake_ssh.login_argv) == 9

    def test_result_has_a_copyable_command(self, fake_ssh, fake_home):
        """The result carries the full command line for pasting."""
        _give_key(fake_home)
        fake_ssh.set_login_body(_ok_body())

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.command.startswith("ssh ")
        assert "srv.example.org" in result.command


class TestOutcome:
    """How the raw ssh run maps to outcomes."""

    def test_ok(self, fake_ssh, fake_home):
        """Exit 0 with the marker: logged in, empty output."""
        _give_key(fake_home)
        fake_ssh.set_login_body(_ok_body())

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.OK
        assert result.message == (
            "Logged in to user@srv.example.org with an SSH key, "
            "no password needed."
        )
        assert result.output == ""
        assert result.suggestions == ()

    def test_ok_despite_login_noise(self, fake_ssh, fake_home):
        """A banner on stderr does not spoil the login; it is kept."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo Welcome banner >&2\n" + _ok_body()
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.OK
        assert result.output == "Welcome banner\n"

    def test_ssh_error_shown_verbatim(self, fake_ssh, fake_home):
        """Exit 255: ssh's own stderr is the output, unchanged."""
        _give_key(fake_home)
        fake_ssh.set_login_body("echo some ssh error >&2\nexit 255\n")

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.FAILED
        assert result.message == (
            "ssh could not log in to user@srv.example.org (exit code 255)."
        )
        assert result.output == "some ssh error\n"

    def test_error_without_message(self, fake_ssh, fake_home):
        """Exit 255 with empty stderr: the placeholder is shown."""
        _give_key(fake_home)
        fake_ssh.set_login_body("exit 255\n")

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.FAILED
        assert result.output == "(ssh printed no message)"

    def test_logged_in_but_command_failed(self, fake_ssh, fake_home):
        """A nonzero exit after login: command-failed, no suggestions."""
        _give_key(fake_home)
        fake_ssh.set_login_body("echo remote says no >&2\nexit 3\n")

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.COMMAND_FAILED
        assert "test command failed" in result.message
        assert "remote says no" in result.output
        assert result.suggestions == ()

    def test_exit_0_without_marker_is_not_ok(self, fake_ssh, fake_home):
        """Exit 0 but no marker in stdout: not a successful login."""
        _give_key(fake_home)
        fake_ssh.set_login_body("echo something else\n")

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome != ssh_check.OK
        assert result.outcome == ssh_check.COMMAND_FAILED

    def test_marker_must_be_a_whole_word(self, fake_ssh, fake_home):
        """A longer token containing the marker does not count."""
        _give_key(fake_home)
        fake_ssh.set_login_body(f"echo XX{ssh_check.MARKER}XX\n")

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome != ssh_check.OK

    def test_ssh_not_installed(self, fake_ssh, fake_home):
        """A missing ssh binary is reported, not raised."""
        fake_ssh.ssh_path.unlink()

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.FAILED
        assert result.message == (
            "'ssh' was not found. Is the OpenSSH client installed?"
        )

    def test_undecodable_output(self, fake_ssh, fake_home):
        """Bytes that are not UTF-8 never break the check."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "printf '\\xff\\xfe broken\\n' >&2\n" + _ok_body()
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.OK
        assert "broken" in result.output


class TestTimeout:
    """A hanging login is stopped, not waited on."""

    def test_hanging_ssh_is_stopped(self, fake_ssh, fake_home):
        """A stuck ssh is killed; the check reports no answer."""
        _give_key(fake_home)
        fake_ssh.set_login_body("/bin/sleep 30\n")

        result = ssh_check.check_login("user", "srv.example.org", "22", timeout=1)

        assert result.outcome == ssh_check.FAILED
        assert result.message == (
            "No answer from srv.example.org (port 22) within 1 seconds."
        )

    def test_child_holding_the_pipes_is_stopped(self, fake_ssh, fake_home):
        """A background child keeping the pipes open is killed too."""
        _give_key(fake_home)
        fake_ssh.set_login_body("/bin/sleep 30 &\n")

        started = time.monotonic()
        result = ssh_check.check_login("user", "srv.example.org", "22", timeout=1)
        elapsed = time.monotonic() - started

        assert result.outcome == ssh_check.FAILED
        assert result.message.startswith("No answer from")
        # The group kill must end the pipe-holding child: the check
        # returns promptly instead of waiting out the sleeper.
        assert elapsed < 10

    def test_default_timeout_is_10_seconds(self):
        """The default timeout is 10 seconds, on the signature too."""
        assert ssh_check.DEFAULT_TIMEOUT == 10
        default = inspect.signature(ssh_check.check_login).parameters["timeout"].default
        assert default == 10

    def test_ssh_cannot_wait_for_input(self, fake_ssh, fake_home):
        """stdin is cut off: a login that would read input fails fast."""
        _give_key(fake_home)
        fake_ssh.set_login_body("read line\n")

        result = ssh_check.check_login("user", "srv.example.org", "22", timeout=5)

        assert result.outcome == ssh_check.COMMAND_FAILED
        assert "No answer from" not in result.message


class TestKeyFirst:
    """The key discovery gates the login attempt."""

    def test_no_key_skips_the_login(self, fake_ssh, fake_home):
        """With no key and no agent keys, ssh never logs in."""
        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.NO_KEY
        assert not any("echo" in arg for arg in fake_ssh.login_argv)

    def test_no_key_suggests_keygen_then_copy_id(self, fake_ssh, fake_home):
        """The no-key result suggests creating a key, then copying it."""
        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.NO_KEY
        assert len(result.suggestions) == 2
        keygen, copy_id = result.suggestions
        assert "empty passphrase" in keygen.text
        assert "unattended" in keygen.text
        assert keygen.command == 'ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519'
        assert copy_id.command == "ssh-copy-id -p 22 user@srv.example.org"

    def test_no_key_message_lists_searched_paths(self, fake_ssh, fake_home):
        """The no-key message lists the searched paths, tilde-shortened."""
        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert "~/." in result.message
        assert "id_ed25519" in result.message

    def test_with_a_key_it_logs_in(self, fake_ssh, fake_home):
        """With a key file present, the login attempt happens."""
        _give_key(fake_home)
        fake_ssh.set_login_body(_ok_body())

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.OK
        assert "echo" in fake_ssh.login_argv

    def test_a_key_in_the_agent_is_enough(self, fake_ssh, fake_home):
        """Agent keys alone justify the login attempt."""
        fake_ssh.set_add_exit(0)
        fake_ssh.set_login_body(_ok_body())

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.OK

    def test_ssh_missing_reports_ssh_not_the_key(self, fake_ssh, fake_home):
        """With ssh gone the discovery can't answer; the login reports why."""
        fake_ssh.ssh_path.unlink()

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.FAILED
        assert "'ssh' was not found" in result.message


class TestSuggestions:
    """FAILED outcomes carry suggestions judged by ssh's message."""

    def test_permission_denied_suggests_copy_id(self, fake_ssh, fake_home):
        """Permission denied: put the key on the server."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'user@srv.example.org: Permission denied (publickey).' >&2\n"
            "exit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.FAILED
        assert len(result.suggestions) == 1
        assert "doesn't accept your key" in result.suggestions[0].text
        assert result.suggestions[0].command == (
            "ssh-copy-id -p 22 user@srv.example.org"
        )

    def test_unknown_host_key_suggests_first_login(self, fake_ssh, fake_home):
        """Unknown host key: log in once by hand to accept it."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'Host key verification failed.' >&2\nexit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert len(result.suggestions) == 1
        assert "host key" in result.suggestions[0].text
        assert result.suggestions[0].command == "ssh -p 22 user@srv.example.org"

    def test_changed_host_key_warns(self, fake_ssh, fake_home):
        """A changed host key warns, names the removal command, then login."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo '@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@' >&2\n"
            "echo 'REMOTE HOST IDENTIFICATION HAS CHANGED' >&2\n"
            "echo 'Host key verification failed.' >&2\n"
            "exit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert len(result.suggestions) == 2
        warning, first_login = result.suggestions
        assert "reinstall" in warning.text
        assert "intercept" in warning.text
        assert warning.command == "ssh-keygen -R srv.example.org"
        assert first_login.command == "ssh -p 22 user@srv.example.org"

    def test_unknown_host_name(self, fake_ssh, fake_home):
        """An unresolvable name: advice only, no command."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'ssh: Could not resolve hostname srv.example.org:"
            " Name or service not known' >&2\nexit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert len(result.suggestions) == 1
        assert "REMOTE_SERVER" in result.suggestions[0].text
        assert result.suggestions[0].command is None

    def test_unreachable(self, fake_ssh, fake_home):
        """Connection refused: the server can't be reached."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'ssh: connect to host srv.example.org port 22:"
            " Connection refused' >&2\nexit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert len(result.suggestions) == 1
        assert "can't be reached" in result.suggestions[0].text
        assert result.suggestions[0].command is None

    def test_timeout_suggests_unreachable(self, fake_ssh, fake_home):
        """The no-answer timeout gets the unreachable advice."""
        _give_key(fake_home)
        fake_ssh.set_login_body("/bin/sleep 30\n")

        result = ssh_check.check_login("user", "srv.example.org", "22", timeout=1)

        assert len(result.suggestions) == 1
        assert "can't be reached" in result.suggestions[0].text

    def test_other_error_suggests_copy_id(self, fake_ssh, fake_home):
        """An unmatched failure falls back to the copy-id suggestion."""
        _give_key(fake_home)
        fake_ssh.set_login_body("echo 'some ssh error' >&2\nexit 255\n")

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert len(result.suggestions) == 1
        assert "isn't on the server yet" in result.suggestions[0].text
        assert result.suggestions[0].command == (
            "ssh-copy-id -p 22 user@srv.example.org"
        )

    def test_command_failed_has_no_suggestions(self, fake_ssh, fake_home):
        """Command-failed is logged in: no suggestions apply."""
        _give_key(fake_home)
        fake_ssh.set_login_body("echo 'Permission denied' >&2\nexit 3\n")

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.outcome == ssh_check.COMMAND_FAILED
        assert result.suggestions == ()


class TestCustomPort:
    """The ssh port reaches every command and message."""

    def test_login_uses_the_port(self, fake_ssh, fake_home):
        """The login command carries -p <port>."""
        _give_key(fake_home)
        fake_ssh.set_login_body(_ok_body())

        result = ssh_check.check_login("user", "srv.example.org", "2222")

        assert fake_ssh.login_argv[fake_ssh.login_argv.index("-p") + 1] == "2222"
        assert result.outcome == ssh_check.OK

    def test_copy_id_uses_the_port(self, fake_ssh, fake_home):
        """The copy-id suggestion's command carries -p <port>."""
        _give_key(fake_home)
        fake_ssh.set_login_body("echo 'Permission denied' >&2\nexit 255\n")

        result = ssh_check.check_login("user", "srv.example.org", "2222")

        assert result.suggestions[0].command == (
            "ssh-copy-id -p 2222 user@srv.example.org"
        )

    def test_no_key_suggestion_uses_the_port(self, fake_ssh, fake_home):
        """The no-key copy-id suggestion carries -p <port>."""
        result = ssh_check.check_login("user", "srv.example.org", "2222")

        assert result.suggestions[1].command == (
            "ssh-copy-id -p 2222 user@srv.example.org"
        )

    def test_first_login_uses_the_port(self, fake_ssh, fake_home):
        """The first-login suggestion's command carries -p <port>."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'Host key verification failed.' >&2\nexit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "2222")

        assert result.suggestions[0].command == (
            "ssh -p 2222 user@srv.example.org"
        )

    def test_changed_host_key_names_host_and_port(self, fake_ssh, fake_home):
        """Off port 22 the known-hosts name is [server]:port."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'REMOTE HOST IDENTIFICATION HAS CHANGED' >&2\nexit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "2222")

        assert result.suggestions[0].command == (
            "ssh-keygen -R [srv.example.org]:2222"
        )

    def test_unreachable_names_the_port(self, fake_ssh, fake_home):
        """The unreachable advice names server and port."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'ssh: connect to host srv.example.org port 2222:"
            " No route to host' >&2\nexit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "2222")

        assert "2222" in result.suggestions[0].text
        assert "srv.example.org" in result.suggestions[0].text

    def test_timeout_message_names_the_port(self, fake_ssh, fake_home):
        """The no-answer message names the port."""
        _give_key(fake_home)
        fake_ssh.set_login_body("/bin/sleep 30\n")

        result = ssh_check.check_login("user", "srv.example.org", "2222", timeout=1)

        assert "port 2222" in result.message

    def test_known_hosts_name_form(self, fake_ssh, fake_home):
        """Port 22 keeps the bare server name in the removal command."""
        _give_key(fake_home)
        fake_ssh.set_login_body(
            "echo 'REMOTE HOST IDENTIFICATION HAS CHANGED' >&2\nexit 255\n"
        )

        result = ssh_check.check_login("user", "srv.example.org", "22")

        assert result.suggestions[0].command == "ssh-keygen -R srv.example.org"


# --- The check-result dialog, ssh side ---------------------------------

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from vt_tunnel_gui.models.advice import Suggestion
from vt_tunnel_gui.views import check_result_view


def _ssh_result(**overrides):
    """One ssh check result with the standard fields, overridden."""
    values = {
        "outcome": ssh_check.OK,
        "message": "Logged in to user@srv.example.org with an SSH key, "
        "no password needed.",
        "output": "",
        "command": "ssh -o BatchMode=yes -o ConnectTimeout=10 -p 22 "
        "user@srv.example.org echo " + ssh_check.MARKER,
        "suggestions": (),
    }
    values.update(overrides)
    return ssh_check.SshCheckResult(**values)


def _ssh_dialog(result, note="", qapp=None):
    """The result dialog for one ssh result, built but not shown."""
    presentation = check_result_view.ssh_presentation(result, note)
    return check_result_view.CheckResultDialog(presentation)


class TestSshResultDialog:
    """The result dialog rendering an ssh check result."""

    @pytest.mark.parametrize(
        "outcome",
        [
            ssh_check.OK,
            ssh_check.COMMAND_FAILED,
            ssh_check.FAILED,
            ssh_check.NO_KEY,
        ],
    )
    def test_every_outcome_renders(self, qapp, outcome):
        """Every ssh outcome maps to a rendered dialog."""
        result = _ssh_result(outcome=outcome)

        dialog = _ssh_dialog(result)

        assert dialog.headline_label.text()
        assert dialog.message_label.text() == result.message

    def test_ok_and_failure_headlines_differ(self, qapp):
        """A working login and a failed login do not share a headline."""
        ok = _ssh_dialog(_ssh_result(outcome=ssh_check.OK))
        failed = _ssh_dialog(_ssh_result(outcome=ssh_check.FAILED))

        assert (
            ok.headline_label.text() != failed.headline_label.text()
        )

    def test_output_shown_verbatim(self, qapp):
        """The ssh output reaches the box byte for byte."""
        result = _ssh_result(
            outcome=ssh_check.FAILED,
            output="user@srv.example.org: Permission denied\n",
        )

        dialog = _ssh_dialog(result)

        assert dialog.output_box.toPlainText() == result.output

    def test_no_output_box_without_output(self, qapp):
        """An output-free result shows no output box at all."""
        dialog = _ssh_dialog(_ssh_result(output=""))

        assert dialog.output_box is None

    def test_note_is_shown(self, qapp):
        """The optional note line is rendered word for word."""
        note = "The tunnel runs as user tunnel: the key must be in that user's ~/.ssh."

        dialog = _ssh_dialog(_ssh_result(), note=note)

        assert dialog.note_label.text() == note

    def test_no_note_without_note(self, qapp):
        """No note line is rendered when there is no note."""
        dialog = _ssh_dialog(_ssh_result())

        assert dialog.note_label is None

    def test_copy_puts_the_command_on_the_clipboard(self, qapp):
        """The check's own command field copies to the clipboard."""
        QApplication.clipboard().setText("sentinel")
        result = _ssh_result()

        dialog = _ssh_dialog(result)
        dialog.check_command_field.copy_button.click()

        assert QApplication.clipboard().text() == result.command

    def test_suggestions_shown_with_copyable_commands(self, qapp):
        """Suggestions render as paragraphs plus copyable command fields."""
        result = _ssh_result(
            outcome=ssh_check.NO_KEY,
            suggestions=(
                Suggestion(text="Create a key:", command="ssh-keygen -t ed25519"),
                Suggestion(text="Then check your network."),
            ),
        )

        dialog = _ssh_dialog(result)

        assert dialog.suggestions_heading.text() == "What you can do:"
        assert [label.text() for label in dialog.suggestion_labels] == [
            "Create a key:",
            "Then check your network.",
        ]
        assert len(dialog.command_fields) == 2
        assert dialog.command_fields[0].edit.text() == "ssh-keygen -t ed25519"
        # A suggestion's Copy button works like the check's own.
        QApplication.clipboard().setText("sentinel")
        dialog.command_fields[0].copy_button.click()
        assert QApplication.clipboard().text() == "ssh-keygen -t ed25519"

    def test_no_suggestions_section_without_suggestions(self, qapp):
        """A result without suggestions shows no suggestions section."""
        dialog = _ssh_dialog(_ssh_result(suggestions=()))

        assert dialog.suggestions_heading is None
        assert dialog.suggestion_labels == []
        assert dialog.command_fields == [dialog.check_command_field]

    def test_check_command_always_shown(self, qapp):
        """The check's own command is shown under its ssh label."""
        result = _ssh_result()

        dialog = _ssh_dialog(result)

        assert dialog.check_command_field.edit.text() == result.command
        labels = [
            label.text() for label in dialog.findChildren(QLabel)
        ]
        assert (
            "The check's command (to try it in a terminal):" in labels
        )

    def test_no_key_verdict(self, qapp):
        """The no-key result renders its own verdict and its advice."""
        result = _ssh_result(
            outcome=ssh_check.NO_KEY,
            message="No SSH key was found for this login.",
            suggestions=(
                Suggestion(
                    text="Create an SSH key:",
                    command='ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519',
                ),
                Suggestion(
                    text="Then put the key on the server.",
                    command="ssh-copy-id -p 22 user@srv.example.org",
                ),
            ),
        )
        failed = _ssh_dialog(_ssh_result(outcome=ssh_check.FAILED))

        dialog = _ssh_dialog(result)

        assert dialog.headline_label.text()
        assert dialog.headline_label.text() != failed.headline_label.text()
        assert dialog.message_label.text() == result.message
        assert len(dialog.suggestion_labels) == 2

    def test_minimum_width(self, qapp):
        """A small result still gets the dialog's minimum width."""
        dialog = _ssh_dialog(_ssh_result())

        assert dialog.width() >= 480

    def test_long_suggested_command_widens_the_window(self, qapp):
        """A long command stretches the dialog (within the hard cap)."""
        short = _ssh_dialog(
            _ssh_result(
                outcome=ssh_check.NO_KEY,
                suggestions=(Suggestion(text="Do:", command="true"),),
            )
        )
        long_command = "ssh-copy-id -p 22 user@" + "very-long-host-name-" * 20 + "srv.example.org"
        long = _ssh_dialog(
            _ssh_result(
                outcome=ssh_check.NO_KEY,
                suggestions=(Suggestion(text="Do:", command=long_command),),
            )
        )

        assert long.width() > short.width()
        assert long.width() <= 900
        assert long.command_fields[0].edit.text() == long_command
