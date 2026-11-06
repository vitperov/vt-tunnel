"""SSH keys of the local user: which ones ssh would log in with.

ssh is asked which identity files it would try for a login
(``ssh -G``: honours ``IdentityFile`` in ``~/.ssh/config``, falls back to
the default names), and ``ssh-add -l`` whether an ssh-agent holds keys.
A key is "available" if one of those files exists or the agent has one.

These are the keys of the user running the GUI: the tunnel runs as
RUN_DAEMON_USER, see :func:`local_user_note`.
"""

import getpass
import subprocess
from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class Keys:
    """The SSH keys available for a login."""

    files: tuple[Path, ...]  # existing private key files ssh would try
    searched: tuple[Path, ...]  # every identity file ssh would try
    in_agent: bool  # ssh-agent holds at least one key

    def __bool__(self) -> bool:
        return bool(self.files) or self.in_agent


def find_keys(user: str, server: str, port: str) -> Keys | None:
    """The keys ssh would use to log in to ``user@server`` on ``port``;
    ``None`` if ssh can't be run at all."""
    searched = _identity_files(user, server, port)
    if searched is None:
        return None
    files = tuple(p for p in searched if p.is_file())
    return Keys(files, searched, _agent_has_keys())


def _identity_files(
    user: str, server: str, port: str
) -> tuple[Path, ...] | None:
    """Ask ssh which identity files it would try (honours ~/.ssh/config)."""
    ran = _run_local([SSH, "-G", "-p", port, f"{user}@{server}"])
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
        path = Path(_expand_tokens(name, user, server, port)).expanduser()
        if path not in paths:
            paths.append(path)
    return tuple(paths)


def _expand_tokens(name: str, user: str, server: str, port: str) -> str:
    """Expand the ssh_config tokens that appear in identity file names
    (whether or not ``ssh -G`` already did)."""
    tokens = {
        "d": str(Path.home()),
        "u": local_user() or "",
        "h": server,
        "p": port,
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


def local_user_note(run_daemon_user: str) -> str | None:
    """Warn if the tunnel won't run as the user whose keys were checked."""
    me = local_user()
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


def local_user() -> str | None:
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return None


def display_path(path: Path) -> str:
    """``path`` with the home directory shown as ``~``."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)
