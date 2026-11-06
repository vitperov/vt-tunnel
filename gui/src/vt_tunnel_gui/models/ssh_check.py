"""Connection check: can we log in to the server with an SSH key alone?

Runs ``ssh`` once, the way the tunnel will use it: no password or
passphrase prompts (``BatchMode``), so a login that would need one fails
with ssh's own error message instead of waiting for input. On the server
it runs a command with a known output, to tell "logged in" apart from
"ssh printed nothing".

The port is not passed: like the daemon, ssh uses its default port or
``~/.ssh/config`` (the cfg has no SSH port key, see ``doc/config.md``).

The check blocks for up to :data:`CHECK_TIMEOUT_S` seconds.
"""

import getpass
import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from enum import Enum

CHECK_TIMEOUT_S = 10

SSH = "ssh"
MARKER = "vt-tunnel-check-ok"
REMOTE_COMMAND = f"echo {MARKER}"

# ssh exits with 255 on its own errors (connection, host key, login);
# otherwise with the exit status of the remote command.
SSH_ERROR_EXIT = 255

NO_OUTPUT = "(ssh printed no message)"


class Outcome(Enum):
    OK = "ok"
    # Logged in with the key, but the test command didn't print the marker
    # (e.g. the key is restricted to tunnelling on the server).
    COMMAND_FAILED = "command_failed"
    FAILED = "failed"


@dataclass(frozen=True)
class CheckResult:
    outcome: Outcome
    message: str  # one-line summary for the user
    output: str  # what ssh printed, verbatim (may be empty)
    command: str  # the command line, ready to paste into a terminal


def ssh_command(
    user: str, server: str, timeout: int = CHECK_TIMEOUT_S
) -> list[str]:
    """The ssh argv. ``user`` and ``server`` must be validated already."""
    return [
        SSH,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout}",
        f"{user}@{server}",
        REMOTE_COMMAND,
    ]


def run_check(
    user: str, server: str, timeout: float = CHECK_TIMEOUT_S
) -> CheckResult:
    """Try to log in to ``user@server`` and run the test command.

    ``user`` and ``server`` must be validated identifiers: they go to ssh
    as is, and one starting with ``-`` would be taken for an option.
    """
    argv = ssh_command(user, server)
    command = shlex.join(argv)
    target = f"{user}@{server}"
    try:
        # Own session: no controlling terminal to prompt on, and on timeout
        # the whole process group is killed — including e.g. a
        # ProxyCommand child that would keep the pipes open.
        with subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
                return CheckResult(
                    Outcome.FAILED,
                    f"No answer from {server} within {timeout:g} seconds.",
                    _join(stderr, stdout),
                    command,
                )
    except FileNotFoundError:
        return CheckResult(
            Outcome.FAILED,
            f"'{SSH}' was not found. Is the OpenSSH client installed?",
            "",
            command,
        )
    except OSError as err:
        return CheckResult(
            Outcome.FAILED,
            f"Can't run '{SSH}': {err.strerror or err}",
            "",
            command,
        )

    code = process.returncode
    if code == 0 and MARKER in stdout.split():
        return CheckResult(
            Outcome.OK,
            f"Logged in to {target} with an SSH key, no password needed.",
            stderr.strip(),
            command,
        )
    if code == SSH_ERROR_EXIT:
        return CheckResult(
            Outcome.FAILED,
            f"ssh could not log in to {target} (exit code {code}).",
            stderr.strip() or NO_OUTPUT,
            command,
        )
    return CheckResult(
        Outcome.COMMAND_FAILED,
        f"Logged in to {target} with an SSH key, but the test command "
        f"'{REMOTE_COMMAND}' didn't work (exit code {code}). The server "
        "may allow this key only limited use, e.g. tunnelling.",
        _join(stderr, stdout) or NO_OUTPUT,
        command,
    )


def local_user_note(run_daemon_user: str) -> str | None:
    """Warn if the tunnel won't run as the user whose keys were checked."""
    try:
        me = getpass.getuser()
    except (OSError, KeyError):  # no user name known: nothing to compare
        return None
    if not run_daemon_user or run_daemon_user == me:
        return None
    return (
        f"The check used your SSH keys ({me}), but the tunnel runs as "
        f"{run_daemon_user}, with {run_daemon_user}'s keys. To check "
        f"those, run the command below as {run_daemon_user} "
        f"(e.g. with sudo -u {run_daemon_user})."
    )


def _join(*parts: str) -> str:
    return "\n".join(p.strip() for p in parts if p.strip())
