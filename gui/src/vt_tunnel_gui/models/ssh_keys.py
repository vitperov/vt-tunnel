"""SSH key and agent discovery for one tunnel login.

Asks the local ssh client which identity files it would try for the
tunnel's login (an ``ssh -G`` query honouring the user's ssh config),
falls back to the OpenSSH 9 default identity names when ssh cannot
answer, expands ssh_config tokens and tildes to the calling user's
home, and checks whether the local agent holds keys. Helpers give the
UI a run-user mismatch warning, a display form for long paths and a
ready-made key-generation command. No exceptions escape this module:
every subprocess failure degrades silently.
"""

import dataclasses
import logging
import os
import pwd
import subprocess

_log = logging.getLogger(__name__)

# Local command, normally instant; a stuck ssh must not hang the GUI.
_SSH_TIMEOUT = 5

# The identity-file keyword in `ssh -G` output (matched case-insensitively).
_IDENTITY_KEYWORD = "identityfile"

# OpenSSH 9's default private-identity names, under ~/.ssh.
_DEFAULT_IDENTITY_NAMES = tuple(
    "~/.ssh/" + name
    for name in (
        "id_rsa",
        "id_ecdsa",
        "id_ecdsa_sk",
        "id_ed25519",
        "id_ed25519_sk",
        "id_dsa",
    )
)

# A ready-made key-generation command for the UI to offer: empty
# passphrase, because the tunnel starts unattended and cannot type one.
ED25519_KEYGEN_COMMAND = 'ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519'


@dataclasses.dataclass(frozen=True)
class DiscoveryResult:
    """What the local ssh client would log in with for one login.

    ``key_files`` is the tuple of existing private-key files ssh would
    try; ``candidates`` is the tuple of every candidate path searched,
    existing or not; ``agent_keys`` says whether the agent holds keys.
    The result is falsy when there is nothing to log in with: no
    existing key file and no agent keys.
    """

    key_files: tuple
    candidates: tuple
    agent_keys: bool

    def __bool__(self):
        return bool(self.key_files) or self.agent_keys


def discover_keys(user, server, port):
    """Discover the key files and agent keys for one tunnel login.

    Returns a DiscoveryResult, or None only when ssh itself cannot be
    run (binary missing, OS error, timeout).
    """
    names = _query_identity_files(user, server, port)
    if names is None:
        return None
    home = os.path.expanduser("~")
    local = local_user()
    candidates = []
    for name in names:
        path = _expand_tokens(
            name,
            server=server,
            port=port,
            remote_user=user,
            local_user=local,
            home=home,
        )
        path = _expand_tilde(path, home)
        if path not in candidates:
            candidates.append(path)
    key_files = tuple(path for path in candidates if os.path.isfile(path))
    return DiscoveryResult(
        key_files=key_files,
        candidates=tuple(candidates),
        agent_keys=_agent_has_keys(),
    )


def _query_identity_files(user, server, port):
    """Ask the local ssh client which identity files it would try.

    Runs ``ssh -G`` for the login with stdin cut off and no controlling
    terminal. On exit 0 the identity-file lines contribute their second
    whitespace-separated token; anything else (nonzero exit, no
    identity-file lines) falls back to the OpenSSH 9 default names.
    Returns None when ssh itself cannot be run.
    """
    argv = ["ssh", "-G", "-p", port, f"{user}@{server}"]
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SSH_TIMEOUT,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        _log.debug("ssh -G query failed: %s", error)
        return None
    if proc.returncode != 0:
        _log.debug("ssh -G exited %s; falling back to defaults", proc.returncode)
        return list(_DEFAULT_IDENTITY_NAMES)
    names = []
    for line in proc.stdout.splitlines():
        if not line.lower().startswith(_IDENTITY_KEYWORD):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        names.append(tokens[1])
    if not names:
        return list(_DEFAULT_IDENTITY_NAMES)
    return names


def _expand_tokens(path, server, port, remote_user, local_user, home):
    """Expand ssh_config tokens in one candidate path.

    %d (local home), %u (local user), %h (server host), %p (port),
    %r (remote user) and %% (literal percent) are applied whether or
    not ssh already expanded them; an unknown token is left verbatim.
    """
    out = []
    i = 0
    while i < len(path):
        char = path[i]
        if char == "%" and i + 1 < len(path):
            nxt = path[i + 1]
            if nxt == "%":
                out.append("%")
                i += 2
                continue
            if nxt == "d":
                out.append(home)
                i += 2
                continue
            if nxt == "u":
                out.append(local_user or "")
                i += 2
                continue
            if nxt == "h":
                out.append(server)
                i += 2
                continue
            if nxt == "p":
                out.append(port)
                i += 2
                continue
            if nxt == "r":
                out.append(remote_user)
                i += 2
                continue
        out.append(char)
        i += 1
    return "".join(out)


def _expand_tilde(path, home):
    """Expand a leading tilde to the calling user's home directory.

    Only a bare ``~`` or ``~/...`` is expanded — never a ``~user``
    form, so no other user's home is ever involved.
    """
    if path == "~":
        return home
    if path.startswith("~/"):
        return home + path[1:]
    return path


def _agent_has_keys():
    """Whether the local ssh agent holds at least one key.

    ``ssh-add -l``: exit 0 means keys; exit 1 (agent alive, empty) and
    exit 2 (no agent) both mean no agent keys, as does any failure to
    run ssh-add at all.
    """
    try:
        proc = subprocess.run(
            ["ssh-add", "-l"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SSH_TIMEOUT,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        _log.debug("ssh-add -l failed: %s", error)
        return False
    return proc.returncode == 0


def local_user():
    """The calling user's name, or None when it cannot be determined."""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except (KeyError, OSError) as error:
        _log.debug("local user lookup failed: %s", error)
        return None


def mismatch_warning(daemon_user):
    """A warning when the check's keys differ from the tunnel's user.

    Returns nothing when the configured daemon-run-user is empty, when
    the local user name cannot be determined, or when it equals the
    configured user — the check then used exactly the right keys.
    Otherwise a message explaining that the check used the local
    user's keys while the tunnel will run as the configured user,
    suggesting re-running the check as that user.
    """
    if not daemon_user:
        return None
    current = local_user()
    if current is None or current == daemon_user:
        return None
    return (
        f"The check used the keys of the local user {current}, but the "
        f"tunnel will run as {daemon_user}. Re-run the check as that "
        f"user, e.g. via: sudo -u {daemon_user} <this application>"
    )


def display_path(path):
    """A display form of one path: tilde form under the home directory.

    Paths under the calling user's home are shortened to ``~/...``;
    the home itself becomes ``~``; anything else is returned unchanged.
    """
    home = os.path.expanduser("~")
    text = os.fspath(path)
    if text == home:
        return "~"
    if text.startswith(home + os.sep):
        return "~" + text[len(home):]
    return text
