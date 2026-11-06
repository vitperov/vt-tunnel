"""Connection check: can we log in to the server with an SSH key alone?

First looks for a key (see :mod:`ssh_keys`); without one there is
nothing to log in with, and the result says how to create one. Then runs
``ssh`` once, the way the tunnel will use it: no password or passphrase
prompts (``BatchMode``), so a login that would need one fails
with ssh's own error message instead of waiting for input. On the server
it runs a command with a known output, to tell "logged in" apart from
"ssh printed nothing".

The port is not passed: like the daemon, ssh uses its default port or
``~/.ssh/config`` (connections have no SSH port key, see
``doc/config.md``).

The check blocks for up to :data:`CHECK_TIMEOUT_S` seconds (plus a
moment for the key lookup). Failed results come with suggestions, e.g.
``ssh-copy-id`` when the server doesn't accept the key.
"""

import dataclasses
import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from enum import Enum

from vt_tunnel_gui.models import ssh_keys
from vt_tunnel_gui.models.advice import Suggestion

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
    NO_KEY = "no_key"  # no key to log in with: the login wasn't tried


@dataclass(frozen=True)
class CheckResult:
    outcome: Outcome
    message: str  # one-line summary for the user
    output: str  # what ssh printed, verbatim (may be empty)
    command: str  # the command line, ready to paste into a terminal
    suggestions: tuple[Suggestion, ...] = ()


def check(
    user: str, server: str, timeout: float = CHECK_TIMEOUT_S
) -> CheckResult:
    """Look for a key, then (if there is one) try to log in with it.

    ``user`` and ``server`` must be validated identifiers, see
    :func:`run_check`.
    """
    target = f"{user}@{server}"
    keys = ssh_keys.find_keys(user, server)
    if keys is not None and not keys:
        searched = ", ".join(ssh_keys.display_path(p) for p in keys.searched)
        return CheckResult(
            Outcome.NO_KEY,
            "You have no SSH key to log in with: none of "
            f"{searched or 'the identity files'} exists, and ssh-agent "
            "holds none. The login was not tried.",
            "",
            shlex.join(ssh_command(user, server)),
            (
                Suggestion(
                    "Create a key. Leave the passphrase empty: the tunnel "
                    "starts unattended and can't type it.",
                    ssh_keys.KEYGEN_COMMAND,
                ),
                _copy_id(target, "Then put it on the server"),
            ),
        )
    # No `keys` (ssh -G didn't run): the login attempt reports why.
    result = run_check(user, server, timeout)
    return dataclasses.replace(
        result, suggestions=suggestions_for(result, user, server)
    )


def suggestions_for(
    result: CheckResult, user: str, server: str
) -> tuple[Suggestion, ...]:
    """What to do about a failed login, judged by ssh's message."""
    if result.outcome is not Outcome.FAILED:
        return ()
    target = f"{user}@{server}"
    output = result.output
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in output:
        return (
            Suggestion(
                "The server's host key changed. That happens when the "
                "server is reinstalled, but it can also mean someone is "
                "intercepting the connection. Only if you know why it "
                "changed, remove the old key, then connect once to accept "
                "the new one:",
                shlex.join(["ssh-keygen", "-R", server]),
            ),
            _first_login(target, "Then connect once in a terminal"),
        )
    if "Host key verification failed" in output:
        return (_first_login(
            target,
            "ssh doesn't know this server's host key yet. Connect once in "
            "a terminal",
        ),)
    if "Could not resolve hostname" in output:
        return (Suggestion(
            f"The name {server} can't be resolved: check REMOTE_SERVER "
            "for typos, and your network."
        ),)
    if any(m in output for m in _UNREACHABLE) or result.message.startswith(
        "No answer"
    ):
        return (Suggestion(
            f"{server} can't be reached: check your network, that the "
            "server is up and runs an SSH server, and on which port (ssh "
            "uses 22, or what ~/.ssh/config says for this host)."
        ),)
    if result.message.startswith(f"'{SSH}' was not found"):
        return (Suggestion(
            "Install the OpenSSH client.", "sudo apt install openssh-client"
        ),)
    if "Permission denied" in output:
        return (_copy_id(
            target, "The server doesn't accept your key. Put it there"
        ),)
    return (_copy_id(target, "If your key isn't on the server yet, put it "
                             "there"),)


_UNREACHABLE = (
    "Connection refused",
    "Connection timed out",
    "No route to host",
    "Network is unreachable",
    "Connection reset",
    "Connection closed",
)


def _copy_id(target: str, lead: str) -> Suggestion:
    return Suggestion(
        f"{lead}: ssh-copy-id logs in with your password once (in a "
        "terminal) and adds your public key to the server's "
        "authorized_keys.",
        shlex.join(["ssh-copy-id", target]),
    )


def _first_login(target: str, lead: str) -> Suggestion:
    return Suggestion(
        f"{lead}, check the fingerprint it shows and answer \"yes\" (it "
        "may ask for your password); you can quit right after.",
        shlex.join(["ssh", target]),
    )


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


def _join(*parts: str) -> str:
    return "\n".join(p.strip() for p in parts if p.strip())
