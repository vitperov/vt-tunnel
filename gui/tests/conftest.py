"""Shared fixtures and helpers for the vt-tunnel GUI test suite."""

import os

# Force Qt onto its offscreen platform before anything imports Qt: the test
# suite runs headless, and Qt would otherwise try to open a real display.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PyQt6.QtWidgets import QApplication

from vt_tunnel_gui import config_schema


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for the whole test session.

    Constructing a QWidget without an existing QApplication aborts the
    process, so every widget test depends on this fixture (directly or
    through another fixture).
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def connections_dir(tmp_path):
    """A fresh temporary connections directory for one test.

    Stands in for /etc/vt-tunnel/connections.d; created empty. A test that
    needs a missing directory builds its own path under tmp_path instead.
    """
    directory = tmp_path / "connections.d"
    directory.mkdir()
    return directory


@pytest.fixture
def write_connection_file(connections_dir):
    """Return a helper that writes one connection file from a value dict.

    The file is named ``<NAME>.conf`` after the dict's NAME value; every
    other key becomes one ``KEY=value`` line, in dict order. NAME itself is
    left out of the file — the file name is the connection's name.
    """

    def write(values):
        name = values["NAME"]
        lines = [f"{key}={values[key]}" for key in values if key != "NAME"]
        path = connections_dir / f"{name}.conf"
        content = "\n".join(lines)
        if content:
            content += "\n"
        path.write_text(content, encoding="utf-8")
        return path

    return write


@pytest.fixture
def valid_values():
    """A valid value dict holding exactly the schema's example values.

    One entry per schema field, NAME included (write_connection_file
    leaves NAME out of the file itself); a fresh dict per test, so tests
    may mutate their copy.
    """
    return {field.key: field.example for field in config_schema.FIELDS}


@pytest.fixture
def other_valid_values():
    """A second valid value dict, every value distinct from valid_values.

    Same keys in schema order, all values valid under the schema's rules,
    none equal to the corresponding schema example.
    """
    return {
        "NAME": "backup-server",
        "ENABLED": "true",
        "RUN_DAEMON_USER": "tunnel",
        "REMOTE_USER": "deploy",
        "REMOTE_SERVER": "srv.example.org",
        "REMOTE_SERVER_SSH_PORT": "2222",
        "LOCAL_PORT": "8080",
        "REMOTE_PORT": "9091",
    }


@pytest.fixture
def dangerous_identifiers():
    """Values an identifier field must never accept: shell metacharacters.

    One string per injection shape — spaces, tabs, dollar forms, command
    substitution, backticks, semicolons, pipes, redirects, quotes,
    backslash, globs, braces, tilde, history expansion, subshells, at
    and colon, path slashes, commas, hashes, line breaks, carriage
    returns, NUL, Cyrillic homoglyphs of a plain ASCII name, and the
    empty string (identifiers are required). Every entry must fail
    validation for RUN_DAEMON_USER, REMOTE_USER and REMOTE_SERVER.
    """
    return [
        "example user",        # space
        "example\tuser",       # tab
        "$HOME",
        "${HOME}",
        "$(echo example)",     # command substitution
        "`echo example`",      # backticks
        "a;b",
        "a|b",
        "a>b",
        "a<b",
        'a"b',
        "a'b",
        "a\\b",
        "a*b",
        "a?b",
        "a[b]",
        "a{b,c}",
        "~user",
        "!!",
        "!$",
        "(id)",
        "a@b",
        "a:b",
        "a/b",
        "a,b",
        "a#b",
        "a\nb",
        "a\rb",
        "a\x00b",
        "us\u0435r",           # Cyrillic homoglyph of "user"
        "",                    # identifiers are required
    ]


@pytest.fixture
def leading_dash_identifiers():
    """Values starting with a dash that ssh/su would take for options.

    Real ssh options, su options, the end-of-options marker and a bare
    dash; every entry must fail identifier validation.
    """
    return [
        "-F.evil",
        "-oProxyCommand=evil",
        "-N",
        "-4",
        "--",
        "-",
    ]


@pytest.fixture
def dangerous_ports():
    """Port values that must never reach the daemon's command line.

    One string per shape — ssh options after the number, separators,
    shell substitutions, whitespace variants, signs, decimals,
    underscores, hex, exponents, non-ASCII digits and plain letters.
    Every entry must fail port validation.
    """
    return [
        "22 -oProxyCommand=evil",  # options after the number
        "22,23",
        "22;23",
        "22:23",
        "$PORT",
        "$(echo 22)",
        "`echo 22`",
        " 22",
        "22 ",
        "22\t",
        "\n22",
        "22\n",
        "+22",
        "-22",
        "22.5",
        "22.0",
        "2_2",
        "22_000",
        "0x16",
        "0X16",
        "2e1",
        "22e0",
        "\u0662\u0662",   # Arabic-Indic digits — str.isdigit() accepts them
        "\uFF12\uFF12",   # fullwidth digits — also isdigit() true
        "abc",
        "22a",
        "a22",
    ]


@pytest.fixture
def out_of_range_ports():
    """Well-formed port numbers outside 1-65535."""
    return ["0", "-1", "65536", "99999999999999999999"]


class FakeSsh:
    """Handle over the scripted ssh/ssh-add executables of fake_ssh."""

    def __init__(self, state, bin_dir):
        self._state = state
        self.bin_dir = bin_dir

    def set_g_output(self, text):
        """Script the output the fake ssh prints in -G mode."""
        (self._state / "g-output").write_text(text)

    def set_g_exit(self, code):
        """Script the fake ssh's exit code in -G mode."""
        (self._state / "g-exit").write_text(f"{code}\n")

    def set_add_exit(self, code):
        """Script the fake ssh-add's exit code."""
        (self._state / "add-exit").write_text(f"{code}\n")

    def set_login_body(self, body):
        """Script the shell body a fake ssh login runs after logging."""
        (self._state / "login-body").write_text(body)

    @property
    def login_argv(self):
        """The argv (without argv[0]) of the most recent fake ssh run."""
        return (self._state / "login-argv").read_text().splitlines()

    @property
    def ssh_path(self):
        """Path of the fake ssh executable (remove it to hide ssh)."""
        return self.bin_dir / "ssh"

    @property
    def ssh_add_path(self):
        """Path of the fake ssh-add executable (remove it to hide it)."""
        return self.bin_dir / "ssh-add"


_SSH_SCRIPT = """#!/bin/sh
# Absolute paths for cat: the PATH override holds only the fake bin dir.
printf '%s\\n' "$@" > "{state}/login-argv"
for arg in "$@"; do
    if [ "$arg" = "-G" ]; then
        /bin/cat "{state}/g-output"
        exit "$(/bin/cat "{state}/g-exit")"
    fi
done
if [ -f "{state}/login-body" ]; then
    . "{state}/login-body"
fi
"""

_SSH_ADD_SCRIPT = """#!/bin/sh
exit "$(/bin/cat "{state}/add-exit")"
"""


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """Scripted ssh and ssh-add executables on a PATH override.

    The fake ssh, run with -G, prints the scripted output and exits
    with the scripted code; run as a login, it runs the scripted body
    (nothing, exit 0, by default). Every invocation — -G or login —
    logs its argv (one argument per line, without argv[0]) to a file
    the handle exposes. The fake ssh-add exits with its scripted code
    (default 2: no agent). The PATH override holds only the fake bin
    directory, so no real ssh binary can answer a test, and the real
    agent socket environment variable is removed, so a developer's own
    agent never leaks in.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    state = tmp_path / "fake-ssh-state"
    state.mkdir()
    (state / "g-output").write_text("")
    (state / "g-exit").write_text("0\n")
    (state / "add-exit").write_text("2\n")
    ssh = bin_dir / "ssh"
    ssh.write_text(_SSH_SCRIPT.format(state=state))
    ssh.chmod(0o755)
    ssh_add = bin_dir / "ssh-add"
    ssh_add.write_text(_SSH_ADD_SCRIPT.format(state=state))
    ssh_add.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    return FakeSsh(state, bin_dir)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A fresh home directory with an empty ~/.ssh, with HOME overridden.

    Every tilde and %d expansion inside a test resolves here, so tests
    see exactly the home they prepared and never the developer's own.
    """
    home = tmp_path / "gui-home"
    (home / ".ssh").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home
