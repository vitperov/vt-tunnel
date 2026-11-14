"""Tests for the daemon check: query, parse and cannot-check."""

import dataclasses
import inspect

import pytest

from vt_tunnel_gui.models import daemon_check


def _loaded_dump():
    """A property dump of a loaded, running, enabled instance."""
    return "\n".join(
        [
            "LoadState=loaded",
            "LoadError=0",
            "ActiveState=active",
            "SubState=running",
            "UnitFileState=enabled",
            "Result=success",
            "ExecMainStatus=0",
            "NRestarts=0",
            "ActiveEnterTimestamp=Tue 2026-01-13 10:00:00 UTC",
            "",
        ]
    )


class FakeSystemctl:
    """Handle over the scripted systemctl executable of fake_systemd."""

    def __init__(self, state, bin_dir):
        self._state = state
        self.bin_dir = bin_dir

    def set_show_dump(self, text):
        """Script the property dump the fake systemctl prints."""
        (self._state / "show-output").write_text(text)

    def set_show_exit(self, code):
        """Script the fake systemctl's exit code."""
        (self._state / "show-exit").write_text(f"{code}\n")

    def set_show_body(self, body):
        """Script the shell body the fake systemctl runs first."""
        (self._state / "show-body").write_text(body)

    @property
    def show_argv(self):
        """The argv (without argv[0]) of the most recent fake run."""
        return (self._state / "show-argv").read_text().splitlines()

    @property
    def systemctl_path(self):
        """Path of the fake systemctl (remove it to hide systemctl)."""
        return self.bin_dir / "systemctl"

    def set_journal_output(self, text):
        """Script the journal output the fake journalctl prints."""
        (self._state / "journal-output").write_text(text)

    def set_journal_exit(self, code):
        """Script the fake journalctl's exit code."""
        (self._state / "journal-exit").write_text(f"{code}\n")

    def set_journal_body(self, body):
        """Script the shell body the fake journalctl runs first."""
        (self._state / "journal-body").write_text(body)

    @property
    def journal_argv(self):
        """The argv (without argv[0]) of the most recent fake journalctl."""
        return (self._state / "journal-argv").read_text().splitlines()

    @property
    def journal_ran(self):
        """Whether the fake journalctl was executed at all."""
        return (self._state / "journal-argv").exists()

    @property
    def journalctl_path(self):
        """Path of the fake journalctl (remove it to hide journalctl)."""
        return self.bin_dir / "journalctl"


_SYSTEMCTL_SCRIPT = """#!/bin/sh
# Absolute paths for cat: the PATH override holds only the fake bin dir.
printf '%s\\n' "$@" > "{state}/show-argv"
if [ -f "{state}/show-body" ]; then
    . "{state}/show-body"
fi
/bin/cat "{state}/show-output"
exit "$(/bin/cat "{state}/show-exit")"
"""

_JOURNALCTL_SCRIPT = """#!/bin/sh
printf '%s\\n' "$@" > "{state}/journal-argv"
if [ -f "{state}/journal-body" ]; then
    . "{state}/journal-body"
fi
/bin/cat "{state}/journal-output"
exit "$(/bin/cat "{state}/journal-exit")"
"""


@pytest.fixture
def fake_systemd(tmp_path, monkeypatch):
    """Scripted systemctl and journalctl executables on a PATH override.

    The fake systemctl logs its argv, runs the scripted body (nothing,
    by default), prints the scripted property dump and exits with the
    scripted code (default 0). The fake journalctl does the same for
    the recent-log read. The PATH override holds only the fake bin
    directory, so no real systemctl or journalctl can answer a test.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    state = tmp_path / "fake-systemd-state"
    state.mkdir()
    (state / "show-output").write_text("")
    (state / "show-exit").write_text("0\n")
    (state / "journal-output").write_text("")
    (state / "journal-exit").write_text("0\n")
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(_SYSTEMCTL_SCRIPT.format(state=state))
    systemctl.chmod(0o755)
    journalctl = bin_dir / "journalctl"
    journalctl.write_text(_JOURNALCTL_SCRIPT.format(state=state))
    journalctl.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return FakeSystemctl(state, bin_dir)


class TestServiceName:
    """The connection name maps to the template unit's instance."""

    def test_instance_of_the_template(self):
        """service_for derives the vt-tunnel@<name>.service instance."""
        assert daemon_check.service_for("example") == (
            "vt-tunnel@example.service"
        )

    def test_check_queries_that_service(self, fake_systemd):
        """The state query names the derived service instance."""
        fake_systemd.set_show_dump(_loaded_dump())

        daemon_check.check("example")

        assert "vt-tunnel@example.service" in fake_systemd.show_argv


class TestParse:
    """The Key=value parser of systemctl's machine-readable answer."""

    def test_plain_properties(self):
        """Every Key=value line becomes one dict entry."""
        properties = daemon_check.parse_properties(
            "LoadState=loaded\nActiveState=active\n"
        )

        assert properties == {"LoadState": "loaded", "ActiveState": "active"}

    def test_value_may_contain_equals(self):
        """Only the first = separates: the value keeps the rest."""
        properties = daemon_check.parse_properties(
            "LoadError=Some=path with=equals\n"
        )

        assert properties == {"LoadError": "Some=path with=equals"}

    def test_junk_lines_ignored(self):
        """Lines without a = are junk and never reach the dict."""
        properties = daemon_check.parse_properties(
            "this is junk\n\nLoadState=loaded\nmore junk\n"
        )

        assert properties == {"LoadState": "loaded"}

    def test_empty_key_ignored(self):
        """A line with an empty key is junk too."""
        assert daemon_check.parse_properties("=value\n") == {}

    def test_empty_text(self):
        """No lines, no properties."""
        assert daemon_check.parse_properties("") == {}


class TestQuery:
    """The machine-readable state query."""

    def test_show_arguments(self, fake_systemd):
        """One systemctl show call with the exact property list."""
        fake_systemd.set_show_dump(_loaded_dump())

        daemon_check.check("example")

        assert fake_systemd.show_argv == [
            "show",
            "vt-tunnel@example.service",
            "--property=LoadState,LoadError,ActiveState,SubState,"
            "UnitFileState,Result,ExecMainStatus,NRestarts,"
            "ActiveEnterTimestamp",
        ]

    def test_default_timeout_is_5_seconds(self):
        """The default per-command timeout is 5 seconds, on the signature."""
        assert daemon_check.DEFAULT_TIMEOUT == 5
        default = inspect.signature(daemon_check.check).parameters[
            "timeout"
        ].default
        assert default == 5


class TestCannotCheck:
    """When systemd cannot be asked, the result is UNKNOWN — never a raise."""

    def test_show_arguments_on_failure(self, fake_systemd):
        """Even a failing query is the one show call with the property list."""
        fake_systemd.set_show_exit(1)
        fake_systemd.set_show_body(
            'echo "System has not been booted with systemd" >&2\n'
        )

        result = daemon_check.check("example")

        assert fake_systemd.show_argv == [
            "show",
            "vt-tunnel@example.service",
            "--property=LoadState,LoadError,ActiveState,SubState,"
            "UnitFileState,Result,ExecMainStatus,NRestarts,"
            "ActiveEnterTimestamp",
        ]
        assert result.status == daemon_check.UNKNOWN

    def test_no_systemd(self, fake_systemd):
        """A nonzero exit means the check could not ask systemd."""
        fake_systemd.set_show_exit(1)
        fake_systemd.set_show_body(
            'echo "System has not been booted with systemd" >&2\n'
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.UNKNOWN
        assert result.message == "Can't ask systemd"
        assert "System has not been booted with systemd" in result.log
        assert result.suggestions == ()

    def test_systemctl_missing(self, fake_systemd):
        """A missing systemctl binary is reported, not raised."""
        fake_systemd.systemctl_path.unlink()

        result = daemon_check.check("example")

        assert result.status == daemon_check.UNKNOWN
        assert result.message == (
            "'systemctl' was not found. Does this system use systemd?"
        )
        assert result.log == ""
        assert result.suggestions == ()

    def test_systemctl_hangs(self, fake_systemd):
        """A hanging systemctl is stopped; the check reports no answer."""
        fake_systemd.set_show_body("/bin/sleep 30\n")

        result = daemon_check.check("example", timeout=1)

        assert result.status == daemon_check.UNKNOWN
        assert result.message == "Can't ask systemd"
        assert "No answer from systemctl within 1 seconds." in result.log
        assert result.suggestions == ()

    def test_command_to_look_yourself(self, fake_systemd):
        """Even an UNKNOWN result carries the look-yourself command."""
        fake_systemd.set_show_exit(1)

        result = daemon_check.check("example")

        assert result.command == "systemctl status vt-tunnel@example.service"

    def test_no_suggestions(self, fake_systemd):
        """UNKNOWN never carries suggestions."""
        fake_systemd.set_show_exit(1)

        result = daemon_check.check("example")

        assert result.suggestions == ()


class TestResultRecord:
    """The check's result is a frozen record with the settled fields."""

    def test_frozen(self, fake_systemd):
        """The result record rejects attribute assignment."""
        fake_systemd.set_show_exit(1)

        result = daemon_check.check("example")

        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = daemon_check.UNKNOWN

    def test_fields(self, fake_systemd):
        """The record carries status, service, message, log, command, suggestions."""
        fake_systemd.set_show_exit(1)

        result = daemon_check.check("example")

        assert [field.name for field in dataclasses.fields(result)] == [
            "status",
            "service",
            "message",
            "log",
            "command",
            "suggestions",
        ]
        assert result.service == "vt-tunnel@example.service"


def _dump(**overrides):
    """A property dump of a loaded, running, enabled instance, overridden."""
    properties = {
        "LoadState": "loaded",
        "LoadError": "0",
        "ActiveState": "active",
        "SubState": "running",
        "UnitFileState": "enabled",
        "Result": "success",
        "ExecMainStatus": "0",
        "NRestarts": "0",
        "ActiveEnterTimestamp": "Tue 2026-01-13 10:00:00 UTC",
    }
    properties.update(overrides)
    return "".join(f"{key}={value}\n" for key, value in properties.items())


class TestNotInstalled:
    """LoadState not-found: systemd knows no such unit."""

    def test_state(self, fake_systemd):
        """A not-found unit is reported as not installed."""
        fake_systemd.set_show_dump(
            _dump(
                LoadState="not-found",
                ActiveState="inactive",
                SubState="dead",
                UnitFileState="",
                Result="",
            )
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.NOT_INSTALLED
        assert result.message == (
            "vt-tunnel@example.service is not installed. "
            "Install the vt-tunnel package."
        )

    def test_no_suggestions(self, fake_systemd):
        """Not-installed carries no suggestions."""
        fake_systemd.set_show_dump(_dump(LoadState="not-found"))

        result = daemon_check.check("example")

        assert result.suggestions == ()


class TestWorking:
    """ActiveState active: the service is running."""

    def test_running_since(self, fake_systemd):
        """A running, enabled service is working, with the timestamp."""
        fake_systemd.set_show_dump(_dump())

        result = daemon_check.check("example")

        assert result.status == daemon_check.WORKING
        assert result.message == (
            "vt-tunnel@example.service is running since "
            "Tue 2026-01-13 10:00:00 UTC."
        )

    def test_without_timestamp(self, fake_systemd):
        """No timestamp: the message ends with a plain period."""
        fake_systemd.set_show_dump(_dump(ActiveEnterTimestamp=""))

        result = daemon_check.check("example")

        assert result.status == daemon_check.WORKING
        assert result.message == "vt-tunnel@example.service is running."

    def test_not_enabled_hint(self, fake_systemd):
        """A running but disabled service gains the not-enabled hint."""
        fake_systemd.set_show_dump(_dump(UnitFileState="disabled"))

        result = daemon_check.check("example")

        assert result.status == daemon_check.WORKING
        assert result.message == (
            "vt-tunnel@example.service is running since "
            "Tue 2026-01-13 10:00:00 UTC. It is not enabled (disabled), "
            "so it won't start at boot."
        )

    @pytest.mark.parametrize(
        "file_state",
        [
            "enabled",
            "enabled-runtime",
            "static",
            "alias",
            "generated",
            "transient",
        ],
    )
    def test_enabled_state_set(self, fake_systemd, file_state):
        """Every boot-starting file state counts as enabled: no hint."""
        fake_systemd.set_show_dump(_dump(UnitFileState=file_state))

        result = daemon_check.check("example")

        assert result.status == daemon_check.WORKING
        assert "not enabled" not in result.message
        assert result.suggestions == ()


class TestNotEnabled:
    """Installed, but not enabled and not running."""

    @pytest.mark.parametrize("file_state", ["disabled", "linked", "indirect"])
    def test_not_running_across_file_states(self, fake_systemd, file_state):
        """Any non-boot-starting file state: installed but not enabled."""
        fake_systemd.set_show_dump(
            _dump(
                ActiveState="inactive",
                SubState="dead",
                UnitFileState=file_state,
            )
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.NOT_ENABLED
        assert result.message == (
            f"installed, but not enabled ({file_state}) and not running"
        )

    def test_suggestions(self, fake_systemd):
        """Not enabled and not running: enable, then start."""
        fake_systemd.set_show_dump(
            _dump(ActiveState="inactive", SubState="dead", UnitFileState="disabled")
        )

        result = daemon_check.check("example")

        assert [s.command for s in result.suggestions] == [
            "sudo systemctl enable vt-tunnel@example.service",
            "sudo systemctl start vt-tunnel@example.service",
        ]


class TestMasked:
    """A masked unit cannot be started or enabled."""

    @pytest.mark.parametrize("masked_state", ["masked", "masked-runtime"])
    def test_load_state_masked(self, fake_systemd, masked_state):
        """A masked load state is not-enabled with the masked message."""
        fake_systemd.set_show_dump(
            _dump(LoadState=masked_state, ActiveState="inactive", SubState="dead")
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.NOT_ENABLED
        assert result.message == (
            "vt-tunnel@example.service is masked: it can't be started "
            "or enabled until it is unmasked."
        )

    @pytest.mark.parametrize("masked_state", ["masked", "masked-runtime"])
    def test_file_state_masked(self, fake_systemd, masked_state):
        """A masked unit-file state is not-enabled too."""
        fake_systemd.set_show_dump(
            _dump(UnitFileState=masked_state, ActiveState="inactive", SubState="dead")
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.NOT_ENABLED
        assert result.message == (
            "vt-tunnel@example.service is masked: it can't be started "
            "or enabled until it is unmasked."
        )

    def test_suggestions(self, fake_systemd):
        """A masked unit: unmask, then enable, then start."""
        fake_systemd.set_show_dump(_dump(LoadState="masked"))

        result = daemon_check.check("example")

        assert [s.command for s in result.suggestions] == [
            "sudo systemctl unmask vt-tunnel@example.service",
            "sudo systemctl enable vt-tunnel@example.service",
            "sudo systemctl start vt-tunnel@example.service",
        ]


class TestSuggestions:
    """Each implemented branch carries its own suggestions."""

    def test_working_and_enabled_needs_nothing(self, fake_systemd):
        """A running, enabled service needs no advice."""
        fake_systemd.set_show_dump(_dump())

        result = daemon_check.check("example")

        assert result.suggestions == ()

    def test_working_but_not_enabled(self, fake_systemd):
        """A running but disabled service suggests enabling it."""
        fake_systemd.set_show_dump(_dump(UnitFileState="disabled"))

        result = daemon_check.check("example")

        assert len(result.suggestions) == 1
        assert "Enable" in result.suggestions[0].text
        assert result.suggestions[0].command == (
            "sudo systemctl enable vt-tunnel@example.service"
        )


_JOURNAL_LINES = (
    "Nov 14 10:00:01 host vt-tunnel@example.service[421]: autossh[421]: "
    "checking connection",
    "Nov 14 10:00:05 host vt-tunnel@example.service[421]: ssh exited 255",
)


class TestFailed:
    """ActiveState failed: the service's process failed."""

    def test_failed_shows_exact_daemon_output(self, fake_systemd):
        """A failed service is FAILED, with the journal as the log."""
        fake_systemd.set_show_dump(
            _dump(
                ActiveState="failed",
                SubState="failed",
                Result="exit-code",
                ExecMainStatus="1",
            )
        )
        journal = "\n".join(_JOURNAL_LINES) + "\n"
        fake_systemd.set_journal_output(journal)

        result = daemon_check.check("example")

        assert result.status == daemon_check.FAILED
        assert result.message == "vt-tunnel@example.service failed (exit code 1)."
        assert result.log == journal

    def test_failed_by_signal(self, fake_systemd):
        """A signal result is shown as systemd reported it."""
        fake_systemd.set_show_dump(
            _dump(
                ActiveState="failed",
                SubState="failed",
                Result="signal",
                ExecMainStatus="9",
            )
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.FAILED
        assert result.message == "vt-tunnel@example.service failed (signal)."

    def test_failed_and_not_enabled_is_failed(self, fake_systemd):
        """A failed, disabled service stays FAILED, with the hint."""
        fake_systemd.set_show_dump(
            _dump(
                ActiveState="failed",
                SubState="failed",
                Result="exit-code",
                ExecMainStatus="1",
                UnitFileState="disabled",
            )
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.FAILED
        assert result.message == (
            "vt-tunnel@example.service failed (exit code 1). "
            "It is not enabled (disabled), so it won't start at boot."
        )

    def test_restart_loop(self, fake_systemd):
        """An enabled service in auto-restart is a restart loop."""
        fake_systemd.set_show_dump(
            _dump(
                ActiveState="activating",
                SubState="auto-restart",
                Result="exit-code",
                ExecMainStatus="1",
                NRestarts="3",
            )
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.FAILED
        assert result.message == (
            "vt-tunnel@example.service keeps stopping: systemd will "
            "restart it soon (restarts so far: 3)."
        )

    def test_enabled_but_stopped(self, fake_systemd):
        """An enabled, inactive service is FAILED, not NOT_ENABLED."""
        fake_systemd.set_show_dump(
            _dump(ActiveState="inactive", SubState="dead")
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.FAILED
        assert result.message == "enabled but not running (inactive/dead)"

    def test_bad_unit_file(self, fake_systemd):
        """A unit that does not load is FAILED, with the LoadError."""
        fake_systemd.set_show_dump(
            _dump(
                LoadState="error",
                LoadError=(
                    "org.freedesktop.systemd1.LoadFailed Unit "
                    "vt-tunnel@example.service is not properly formatted."
                ),
                ActiveState="inactive",
                SubState="failed",
                UnitFileState="enabled",
                Result="",
            )
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.FAILED
        assert result.message == (
            "vt-tunnel@example.service can't be loaded: "
            "org.freedesktop.systemd1.LoadFailed Unit "
            "vt-tunnel@example.service is not properly formatted."
        )


class TestLog:
    """The recent-log read for every unit systemd knows."""

    def test_journal_arguments(self, fake_systemd):
        """One journalctl call with the unit, 20 lines, no pager."""
        fake_systemd.set_show_dump(_dump())

        daemon_check.check("example")

        assert fake_systemd.journal_argv == [
            "--unit",
            "vt-tunnel@example.service",
            "--lines",
            "20",
            "--no-pager",
        ]

    def test_no_permission_hint_is_shown(self, fake_systemd):
        """journalctl's own message survives a failed read."""
        fake_systemd.set_show_dump(_dump())
        fake_systemd.set_journal_exit(1)
        fake_systemd.set_journal_body(
            'echo "Hint: You are currently not seeing messages from '
            'other users and the system" >&2\n'
        )

        result = daemon_check.check("example")

        assert result.status == daemon_check.WORKING
        assert result.log == (
            "Hint: You are currently not seeing messages from other "
            "users and the system\n"
        )

    def test_empty_log(self, fake_systemd):
        """No journal output becomes the placeholder line."""
        fake_systemd.set_show_dump(_dump())

        result = daemon_check.check("example")

        assert result.status == daemon_check.WORKING
        assert result.log == "(no log lines)"

    def test_journalctl_missing(self, fake_systemd):
        """A missing journalctl is reported, not raised."""
        fake_systemd.set_show_dump(_dump())
        fake_systemd.journalctl_path.unlink()

        result = daemon_check.check("example")

        assert result.status == daemon_check.WORKING
        assert result.log == "Can't read the log: 'journalctl' was not found."

    def test_not_installed_reads_no_log(self, fake_systemd):
        """A not-found unit skips the journal read entirely."""
        fake_systemd.set_show_dump(_dump(LoadState="not-found"))

        daemon_check.check("example")

        assert not fake_systemd.journal_ran


class TestFailureSuggestions:
    """Each FAILED branch carries its own suggestions."""

    def test_failed_points_to_ssh_check_then_restart(self, fake_systemd):
        """A failed service: check the ssh login, then restart."""
        fake_systemd.set_show_dump(
            _dump(ActiveState="failed", SubState="failed", Result="exit-code",
                  ExecMainStatus="1")
        )

        result = daemon_check.check("example")

        assert [s.command for s in result.suggestions] == [
            None,
            "sudo systemctl restart vt-tunnel@example.service",
        ]
        assert "Check connection" in result.suggestions[0].text
        assert "Edit" in result.suggestions[0].text
        assert "Once the cause is fixed" in result.suggestions[1].text

    def test_failed_and_not_enabled_also_suggests_enable(self, fake_systemd):
        """A failed, disabled service adds the enable suggestion."""
        fake_systemd.set_show_dump(
            _dump(ActiveState="failed", SubState="failed", Result="exit-code",
                  ExecMainStatus="1", UnitFileState="disabled")
        )

        result = daemon_check.check("example")

        assert [s.command for s in result.suggestions] == [
            None,
            "sudo systemctl restart vt-tunnel@example.service",
            "sudo systemctl enable vt-tunnel@example.service",
        ]

    def test_restart_loop_points_to_ssh_check_only(self, fake_systemd):
        """A restart loop: only the ssh advice — nothing to start."""
        fake_systemd.set_show_dump(
            _dump(ActiveState="activating", SubState="auto-restart")
        )

        result = daemon_check.check("example")

        assert len(result.suggestions) == 1
        assert result.suggestions[0].command is None
        assert "Check connection" in result.suggestions[0].text

    def test_enabled_but_stopped_suggests_start(self, fake_systemd):
        """An enabled, stopped service suggests starting it."""
        fake_systemd.set_show_dump(
            _dump(ActiveState="inactive", SubState="dead")
        )

        result = daemon_check.check("example")

        assert [s.command for s in result.suggestions] == [
            "sudo systemctl start vt-tunnel@example.service",
        ]

    def test_bad_unit_file_suggests_daemon_reload(self, fake_systemd):
        """A broken unit file: reinstall, then daemon-reload."""
        fake_systemd.set_show_dump(_dump(LoadState="error"))

        result = daemon_check.check("example")

        assert [s.command for s in result.suggestions] == [
            "sudo systemctl daemon-reload",
        ]
        assert "reinstall" in result.suggestions[0].text
