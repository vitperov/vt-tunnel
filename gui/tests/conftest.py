"""Shared fixtures and test data for the config model tests."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.tunnel_config import TunnelConfig

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


def cfg_text(*connections: dict[str, str], start: int = 1) -> str:
    """Render connections as numbered ``KEY<n>=value`` lines (no comments)."""
    return "".join(
        f"{key}{number}={value}\n"
        for number, values in enumerate(connections, start=start)
        for key, value in values.items()
    )


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
def cfg_path(tmp_path: Path) -> Path:
    """Path of a config file that doesn't exist yet."""
    return tmp_path / "vt-tunnel.cfg"


@pytest.fixture
def make_config(cfg_path: Path) -> Callable[[str], TunnelConfig]:
    """Write ``text`` to the config file and return a TunnelConfig for it."""

    def make(text: str) -> TunnelConfig:
        cfg_path.write_text(text, encoding="utf-8")
        return TunnelConfig(cfg_path)

    return make


# --------------------------------------------------------------------------
# Values that could break or inject into the ssh command line
# --------------------------------------------------------------------------
#
#   ExecStart=/usr/bin/sudo su -s /bin/bash -c 'autossh -N
#       ${REMOTE_USER}@${REMOTE_SERVER}
#       -R ${REMOTE_PORT}:localhost:${LOCAL_PORT}' ${RUN_DAEMON_USER}

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
