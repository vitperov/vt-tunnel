"""Connection check: can we log in to the server with an SSH key alone?

First looks for a key (the identity files ssh would try, or one held by
ssh-agent); without one there is nothing to log in with, and the result
says how to create one. Then runs ``ssh`` once, the way the tunnel will use it: no password or
passphrase prompts (``BatchMode``), so a login that would need one fails
with ssh's own error message instead of waiting for input. On the server
it runs a command with a known output, to tell "logged in" apart from
"ssh printed nothing".

The port is not passed: like the daemon, ssh uses its default port or
``~/.ssh/config`` (the cfg has no SSH port key, see ``doc/config.md``).

The check blocks for up to :data:`CHECK_TIMEOUT_S` seconds (plus a
moment for the key lookup). Failed results come with suggestions, e.g.
``ssh-copy-id`` when the server doesn't accept the key.
"""

import dataclasses
import getpass
import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from vt_tunnel_gui.models.advice import Suggestion

CHECK_TIMEOUT_S = 10

SSH = "ssh"
SSH_ADD = "ssh-add"
KEY_LOOKUP_TIMEOUT_S = 5  # local commands, normally instant
# What ssh tries without IdentityFile in its config (OpenSSH 9); used if
# `ssh -G` can't tell.
DEFAULT_IDENTITY_FILES = (
    "~/.ssh/id_rsa",
    "~/.ssh/id_ecdsa",
    "~/.ssh/id_ecdsa_sk",
    "~/.ssh/id_ed25519",
    "~/.ssh/id_ed25519_sk",
    "~/.ssh/id_dsa",
)
KEYGEN_COMMAND = "ssh-keygen -t ed25519"
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


@dataclass(frozen=True)
class Keys:
    """The SSH keys available for a login."""

    files: tuple[Path, ...]  # existing private key files ssh would try
    searched: tuple[Path, ...]  # every identity file ssh would try
    in_agent: bool  # ssh-agent holds at least one key

    def __bool__(self) -> bool:
        return bool(self.files) or self.in_agent


def check(
    user: str, server: str, timeout: float = CHECK_TIMEOUT_S
) -> CheckResult:
    """Look for a key, then (if there is one) try to log in with it.

    ``user`` and ``server`` must be validated identifiers, see
    :func:`run_check`.
    """
    target = f"{user}@{server}"
    keys = find_keys(user, server)
    if keys is not None and not keys:
        searched = ", ".join(_tilde(p) for p in keys.searched)
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
                    KEYGEN_COMMAND,
                ),
                _copy_id(target, "Then put it on the server"),
            ),
        )
    # No `keys` (ssh -G didn't run): the login attempt reports why.
    result = run_check(user, server, timeout)
    return dataclasses.replace(
        result, suggestions=suggestions_for(result, user, server)
    )


def find_keys(user: str, server: str) -> Keys | None:
    """The keys ssh would use to log in to ``user@server``; ``None`` if
    ssh can't be run at all."""
    searched = _identity_files(user, server)
    if searched is None:
        return None
    files = tuple(p for p in searched if p.is_file())
    return Keys(files, searched, _agent_has_keys())


def _identity_files(user: str, server: str) -> tuple[Path, ...] | None:
    """Ask ssh which identity files it would try (honours ~/.ssh/config)."""
    ran = _run_local([SSH, "-G", f"{user}@{server}"])
    if ran is None:
        return None
    code, stdout = ran
    names = [
        line.split(None, 1)[1]
        for line in stdout.splitlines()
        if line.lower().startswith("identityfile ") and code == 0
    ]
    if not names:
        names = list(DEFAULT_IDENTITY_FILES)
    paths = []
    for name in names:
        path = Path(_expand_tokens(name, user, server)).expanduser()
        if path not in paths:
            paths.append(path)
    return tuple(paths)


def _expand_tokens(name: str, user: str, server: str) -> str:
    """Expand the ssh_config tokens that appear in identity file names
    (whether or not ``ssh -G`` already did)."""
    tokens = {
        "d": str(Path.home()),
        "u": _local_user() or "",
        "h": server,
        "r": user,
        "%": "%",
    }
    out, i = [], 0
    while i < len(name):
        if name[i] == "%" and i + 1 < len(name) and name[i + 1] in tokens:
            out.append(tokens[name[i + 1]])
            i += 2
        else:
            out.append(name[i])
            i += 1
    return "".join(out)


def _agent_has_keys() -> bool:
    # ssh-add -l: 0 = lists keys, 1 = agent has none, 2 = no agent.
    ran = _run_local([SSH_ADD, "-l"])
    return ran is not None and ran[0] == 0


def _run_local(argv: list[str]) -> tuple[int, str] | None:
    """Run a quick local helper; (exit code, stdout), or None if it can't
    run or hangs."""
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=KEY_LOOKUP_TIMEOUT_S,
            start_new_session=True,  # no terminal to prompt on
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.returncode, done.stdout


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


def local_user_note(run_daemon_user: str) -> str | None:
    """Warn if the tunnel won't run as the user whose keys were checked."""
    me = _local_user()
    if me is None:  # no user name known: nothing to compare
        return None
    if not run_daemon_user or run_daemon_user == me:
        return None
    return (
        f"The check used your SSH keys ({me}), but the tunnel runs as "
        f"{run_daemon_user}, with {run_daemon_user}'s keys. To check "
        f"those, run the command below as {run_daemon_user} "
        f"(e.g. with sudo -u {run_daemon_user})."
    )


def _local_user() -> str | None:
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return None


def _tilde(path: Path) -> str:
    """``path`` with the home directory shown as ``~``."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _join(*parts: str) -> str:
    return "\n".join(p.strip() for p in parts if p.strip())
