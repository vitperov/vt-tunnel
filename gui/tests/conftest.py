"""Shared fixtures and test data."""

import os
import shlex
import stat
from pathlib import Path

# Qt widgets in tests: no display needed. Before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from vt_tunnel_gui import config_schema  # noqa: E402
from vt_tunnel_gui.models.connection import Connection  # noqa: E402
from vt_tunnel_gui.models.connections_dir import (  # noqa: E402
    ConnectionsDir,
)

# A complete, valid connection: the examples from config_schema.py, which
# are also the examples of the table in doc/config.md.
VALID_VALUES: dict[str, str] = {
    field.key: field.example for field in config_schema.FIELDS
}
# A second valid connection, different from the first.
OTHER_VALUES: dict[str, str] = VALID_VALUES | {
    "NAME": "office",
    "ENABLED": "true",
    "REMOTE_SERVER": "office.example.com",
    "LOCAL_PORT": "8080",
    "REMOTE_PORT": "5002",
}

PORT_KEYS = [
    f.key for f in config_schema.FIELDS
    if f.type is config_schema.FieldType.PORT
]
IDENTIFIER_KEYS = [
    f.key for f in config_schema.FIELDS
    if f.type is config_schema.FieldType.IDENTIFIER
]


def conf_text(values: dict[str, str]) -> str:
    """A connection file's ``KEY=value`` lines for ``values`` (NAME, the
    file name, left out; no comments)."""
    return "".join(
        f"{key}={value}\n" for key, value in values.items() if key != "NAME"
    )


def write_conf(directory: Path, values: dict[str, str]) -> Path:
    """Write the file of connection ``values`` into ``directory``."""
    path = directory / f"{values['NAME']}.conf"
    path.write_text(conf_text(values), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def qapp():
    """The QApplication; widgets (and QPixmap) abort the process without."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class App:
    """The composition of app.main(), with quit recorded instead of run."""

    def __init__(self, config_dir) -> None:
        from vt_tunnel_gui.controller import Controller
        from vt_tunnel_gui.models.model import Model
        from vt_tunnel_gui.views.connection_view import ConnectionView
        from vt_tunnel_gui.views.tray_view import TrayView
        from vt_tunnel_gui.views.view import MainWindow

        self.quit_calls = 0
        self.main_view = MainWindow()
        self.connection_view = ConnectionView(self.main_view)
        self.tray = TrayView()
        self.controller = Controller(
            Model(ConnectionsDir(config_dir)),
            self.main_view,
            self.connection_view,
            self.tray,
            self._quit,
        )

    def _quit(self) -> None:
        self.quit_calls += 1

    def close(self) -> None:
        self.tray.hide()
        self.connection_view.hide()
        self.main_view.hide()


@pytest.fixture
def valid_values() -> dict[str, str]:
    return dict(VALID_VALUES)


@pytest.fixture
def valid() -> Connection:
    return Connection(VALID_VALUES)


@pytest.fixture
def other() -> Connection:
    return Connection(OTHER_VALUES)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """An empty connections directory."""
    path = tmp_path / "connections.d"
    path.mkdir()
    return path


@pytest.fixture
def store(config_dir: Path) -> ConnectionsDir:
    return ConnectionsDir(config_dir)


# --------------------------------------------------------------------------
# Values that could break or inject into the ssh command line
# --------------------------------------------------------------------------
#
#   ExecStart=/usr/bin/sudo su -s /bin/bash -c 'autossh -N
#       ${REMOTE_USER}@${REMOTE_SERVER}
#       -R ${REMOTE_PORT}:localhost:${LOCAL_PORT}' ${RUN_DAEMON_USER}
#
# (the daemon unit is still to be updated to the new keys, see
# doc/config.md)

DANGEROUS_IDENTIFIERS = [
    pytest.param("vasya smith", id="space"),
    pytest.param("vasya\tx", id="tab"),
    pytest.param(" vasya", id="leading-space"),
    pytest.param("$USER", id="dollar-var"),
    pytest.param("${USER}", id="dollar-brace"),
    pytest.param("$(reboot)", id="command-subst"),
    pytest.param("`reboot`", id="backticks"),
    pytest.param("vasya;reboot", id="semicolon"),
    pytest.param("vasya&&reboot", id="and"),
    pytest.param("vasya&", id="background"),
    pytest.param("vasya|nc", id="pipe"),
    pytest.param("vasya>/etc/passwd", id="redirect-out"),
    pytest.param("vasya</etc/shadow", id="redirect-in"),
    pytest.param("va'sya", id="single-quote-closes-bash-c"),
    pytest.param('va"sya', id="double-quote"),
    pytest.param("va\\sya", id="backslash"),
    pytest.param("vasya*", id="glob-star"),
    pytest.param("vasy?", id="glob-question"),
    pytest.param("[ab]", id="glob-class"),
    pytest.param("{a,b}", id="brace-expansion"),
    pytest.param("~root", id="tilde"),
    pytest.param("vasya!", id="history"),
    pytest.param("(vasya)", id="subshell"),
    pytest.param("vasya@evil.com", id="at-redirects-host"),
    pytest.param("evil.com:2222", id="colon"),
    pytest.param("-oProxyCommand=reboot", id="ssh-option-with-equals"),
    pytest.param("a/b", id="slash"),
    pytest.param("a,b", id="comma"),
    pytest.param("vasya#x", id="hash-comment"),
    pytest.param("vasya\nREMOTE_PORT1=1", id="newline-injects-key"),
    pytest.param("vasya\r", id="carriage-return"),
    pytest.param("vasya\x00", id="nul"),
    pytest.param("v\u0430sya", id="cyrillic-homoglyph"),
    pytest.param("vasy\u0430.com", id="cyrillic-a-in-host"),
    pytest.param("", id="empty"),
]

LEADING_DASH_IDENTIFIERS = [
    pytest.param("-F.evil", id="ssh-config-option"),
    pytest.param("-v", id="short-option"),
    pytest.param("--", id="end-of-options"),
    pytest.param("-", id="dash-only"),
    pytest.param("-oProxyCommand", id="ssh-o-option"),
    pytest.param("--login", id="su-long-option"),
]

DANGEROUS_PORTS = [
    pytest.param("22 -oProxyCommand=reboot", id="space-option"),
    pytest.param("22;reboot", id="semicolon"),
    pytest.param("$PORT", id="dollar-var"),
    pytest.param("${PORT}", id="dollar-brace"),
    pytest.param("$(echo 22)", id="command-subst"),
    pytest.param("`echo 22`", id="backticks"),
    pytest.param("22|nc", id="pipe"),
    pytest.param("22&", id="background"),
    pytest.param("22'", id="single-quote"),
    pytest.param("22:localhost:23", id="colon-changes-forward"),
    pytest.param("22\nLOCAL_PORT1=1", id="newline-injects-key"),
    pytest.param(" 22", id="leading-space"),
    pytest.param("22 ", id="trailing-space"),
    pytest.param("2 2", id="inner-space"),
    pytest.param("+22", id="plus-sign"),
    pytest.param("-22", id="minus-sign"),
    pytest.param("22.0", id="decimal"),
    pytest.param("2_2", id="underscore"),
    pytest.param("0x16", id="hex"),
    pytest.param("1e3", id="exponent"),
    pytest.param("\uff12\uff12", id="fullwidth-digits"),
    pytest.param("\u0662\u0662", id="arabic-indic-digits"),
    pytest.param("twenty-two", id="letters"),
]

OUT_OF_RANGE_PORTS = ["0", "-1", "65536", "70000", "99999999999999999999"]


# --------------------------------------------------------------------------
# A fake ssh and a private home directory, for the SSH check and key lookup
# --------------------------------------------------------------------------

from vt_tunnel_gui.models import ssh_keys  # noqa: E402

# What `ssh -G` prints for identity files without IdentityFile in the
# config (OpenSSH 9; other lines left out).
DEFAULT_G_OUTPUT = "".join(
    f"identityfile {name}\n" for name in ssh_keys.DEFAULT_IDENTITY_FILES
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
