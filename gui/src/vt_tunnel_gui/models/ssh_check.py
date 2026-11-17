"""The ssh login check: one BatchMode ssh attempt with a marker command.

Runs ``ssh -o BatchMode=yes -o ConnectTimeout=<timeout> -p <port>
<user>@<server> echo <marker>`` — BatchMode means ssh never prompts for
a password or passphrase (a login that would need one fails with ssh's
own error message instead of waiting), and the marker tells "logged
in" apart from "ssh printed nothing". Before running, the local key
discovery decides whether a login can even be attempted. Every failure
degrades into a result, never an exception; FAILED results carry
suggestions judged by ssh's message. The check runs exactly one ssh
process (plus the key discovery's ``ssh -G`` and ``ssh-add``); it
never writes files and never touches the config directory.
"""

import dataclasses
import logging
import os
import re
import signal
import subprocess

from vt_tunnel_gui.models import ssh_keys
from vt_tunnel_gui.models.advice import Suggestion

_log = logging.getLogger(__name__)

# The login is given this long to answer by default.
DEFAULT_TIMEOUT = 10

# The fixed token the remote echo must print: proof of a real login.
MARKER = "VT_TUNNEL_LOGIN_OK"

# Outcomes of the check.
OK = "ok"
COMMAND_FAILED = "command-failed"
FAILED = "failed"
NO_KEY = "no-key"

# Shown when ssh failed without printing anything.
_NO_MESSAGE_PLACEHOLDER = "(ssh printed no message)"

# ssh error fragments meaning the server cannot be reached at all.
_UNREACHABLE_PATTERNS = (
    "Connection refused",
    "Connection timed out",
    "No route to host",
    "Network is unreachable",
    "Connection reset",
    "Connection closed",
)

# The prefix of the check's own no-answer timeout message; it counts as
# unreachable too.
_NO_ANSWER_PREFIX = "No answer from"


@dataclasses.dataclass(frozen=True)
class SshCheckResult:
    """One finished login check: outcome, message, output, command.

    ``command`` is the full command line the check ran, ready to paste
    into a terminal; ``suggestions`` is a tuple of Suggestion records.
    """

    outcome: str
    message: str
    output: str
    command: str
    suggestions: tuple


def check_login(user, server, port, timeout=DEFAULT_TIMEOUT):
    """Try one key-based ssh login and report how it went.

    ``user``, ``server`` and ``port`` go to ssh as-is — the caller must
    validate them first (a value starting with a dash would be taken
    for an option). Returns a SshCheckResult; never raises.
    """
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout}",
        "-p",
        port,
        f"{user}@{server}",
        "echo",
        MARKER,
    ]
    command = " ".join(argv)

    discovery = ssh_keys.discover_keys(user, server, port)
    if discovery is not None and not discovery:
        # Nothing to log in with — the login is not even tried.
        return SshCheckResult(
            outcome=NO_KEY,
            message=_no_key_message(discovery),
            output="",
            command=command,
            suggestions=_no_key_suggestions(user, server, port),
        )

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
    except FileNotFoundError:
        return SshCheckResult(
            outcome=FAILED,
            message="'ssh' was not found. Is the OpenSSH client installed?",
            output="",
            command=command,
            suggestions=_suggestions_for(
                "'ssh' was not found.", user, server, port
            ),
        )
    except OSError as error:
        # Not ssh's message — no server was contacted — so the ssh
        # message judge must not see it; the fallback suggestion fits.
        return SshCheckResult(
            outcome=FAILED,
            message=f"Can't run 'ssh': {error}",
            output="",
            command=command,
            suggestions=(
                _copy_id_suggestion(
                    user,
                    server,
                    port,
                    "If your key isn't on the server yet, put it there.",
                ),
            ),
        )

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        stdout, stderr = proc.communicate()
        collected = _joined(stdout, stderr)
        message = (
            f"No answer from {server} (port {port}) within "
            f"{timeout} seconds."
        )
        return SshCheckResult(
            outcome=FAILED,
            message=message,
            output=collected,
            command=command,
            suggestions=_suggestions_for(
                message + "\n" + collected, user, server, port
            ),
        )

    if proc.returncode == 0 and _has_marker(stdout):
        return SshCheckResult(
            outcome=OK,
            message=(
                f"Logged in to {user}@{server} with an SSH key, "
                "no password needed."
            ),
            output=stderr,
            command=command,
            suggestions=(),
        )

    if proc.returncode == 255:
        message = f"ssh could not log in to {user}@{server} (exit code 255)."
        output = stderr if stderr else _NO_MESSAGE_PLACEHOLDER
        return SshCheckResult(
            outcome=FAILED,
            message=message,
            output=output,
            command=command,
            suggestions=_suggestions_for(
                message + "\n" + output, user, server, port
            ),
        )

    # Logged in, but the test command didn't work: any other nonzero
    # exit, or exit 0 without the marker. The server may allow this key
    # only limited use, e.g. tunnelling.
    collected = _joined(stdout, stderr) or _NO_MESSAGE_PLACEHOLDER
    return SshCheckResult(
        outcome=COMMAND_FAILED,
        message=(
            f"Logged in to {user}@{server}, but the test command failed "
            f"(exit code {proc.returncode})."
        ),
        output=collected,
        command=command,
        suggestions=(),
    )


def _has_marker(stdout):
    """Whether the marker appears in stdout as a whole word.

    A longer token merely containing the marker does not count.
    """
    return re.search(rf"\b{re.escape(MARKER)}\b", stdout) is not None


def _joined(stdout, stderr):
    """Both captured streams as one text, empty pieces dropped."""
    return "\n".join(part for part in (stdout, stderr) if part)


def _kill_process_group(proc):
    """SIGKILL the whole process group of one started ssh process.

    The process runs in its own session, so the group covers every
    child too — e.g. a ProxyCommand child that would otherwise keep the
    pipes open after ssh itself is gone.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError as error:
        _log.debug("killing ssh process group failed: %s", error)


def _no_key_message(discovery):
    """The NO_KEY message: the searched paths, or a generic phrase."""
    searched = ", ".join(
        ssh_keys.display_path(path) for path in discovery.candidates
    )
    if searched:
        return (
            "No SSH key was found for this login (searched: "
            f"{searched}), and the SSH agent holds none."
        )
    return "No SSH key was found for this login, and the SSH agent holds none."


def _no_key_suggestions(user, server, port):
    """The NO_KEY suggestions: create a key, then put it on the server."""
    return (
        Suggestion(
            text=(
                "Create an SSH key with an empty passphrase — the "
                "tunnel starts unattended and can't type one:"
            ),
            command=ssh_keys.ED25519_KEYGEN_COMMAND,
        ),
        _copy_id_suggestion(
            user,
            server,
            port,
            "Then put the key on the server.",
        ),
    )


def _copy_id_suggestion(user, server, port, lead):
    """The ssh-copy-id suggestion: password login once, key installed."""
    return Suggestion(
        text=(
            f"{lead} ssh-copy-id logs in with the password once (in a "
            "terminal) and adds your public key to the server's "
            "authorized_keys:"
        ),
        command=f"ssh-copy-id -p {port} {user}@{server}",
    )


def _first_login_suggestion(user, server, port, lead):
    """The first-login suggestion: accept the host key by hand once."""
    return Suggestion(
        text=(
            f"{lead} Log in once by hand: check the fingerprint, "
            'answer "yes", it may ask for the password, and quit right '
            "after:"
        ),
        command=f"ssh -p {port} {user}@{server}",
    )


def _known_hosts_name(server, port):
    """The server's name in known_hosts form: [server]:port off 22."""
    if port == "22":
        return server
    return f"[{server}]:{port}"


def _suggestions_for(text, user, server, port):
    """Suggestions for one FAILED outcome, judged by ssh's message.

    The first matching pattern wins; anything unmatched falls back to
    the ssh-copy-id suggestion.
    """
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in text:
        return (
            Suggestion(
                text=(
                    "The server's host key changed. This happens on a "
                    "reinstall, but it can also mean the connection is "
                    "being intercepted. Only if you know why it "
                    "changed: remove the old key, then connect once to "
                    "accept the new one:"
                ),
                command=f"ssh-keygen -R {_known_hosts_name(server, port)}",
            ),
            _first_login_suggestion(
                user, server, port, "Then accept the new host key."
            ),
        )
    if "Host key verification failed" in text:
        return (
            _first_login_suggestion(
                user,
                server,
                port,
                "ssh doesn't know this server's host key yet.",
            ),
        )
    if "Could not resolve hostname" in text:
        return (
            Suggestion(
                text=(
                    "The server's name could not be resolved. Check the "
                    "REMOTE_SERVER value for typos, and check your "
                    "network."
                ),
            ),
        )
    if _NO_ANSWER_PREFIX in text or any(
        pattern in text for pattern in _UNREACHABLE_PATTERNS
    ):
        return (
            Suggestion(
                text=(
                    f"{server} can't be reached on port {port}: check "
                    "your network, that the server is up, and that its "
                    f"SSH server listens on port {port} "
                    "(REMOTE_SERVER_SSH_PORT)."
                ),
            ),
        )
    if "'ssh' was not found" in text:
        return (
            Suggestion(
                text="Install the OpenSSH client:",
                command="sudo apt install openssh-client",
            ),
        )
    if "Permission denied" in text:
        return (
            _copy_id_suggestion(
                user,
                server,
                port,
                "The server doesn't accept your key. Put it there.",
            ),
        )
    return (
        _copy_id_suggestion(
            user,
            server,
            port,
            "If your key isn't on the server yet, put it there.",
        ),
    )
