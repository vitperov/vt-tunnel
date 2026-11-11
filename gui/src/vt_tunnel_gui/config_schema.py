"""Machine-readable schema of one vt-tunnel connection file.

Describes the per-connection files under /etc/vt-tunnel/connections.d —
the authoritative source for their keys, types, validation rules and
semantics. The file format and the reasoning behind the rules live in
``doc/config.md``; parsing, validation and writing are NOT done here —
they belong to the config model.
"""

from dataclasses import dataclass
from enum import Enum

DEFAULT_CONFIG_DIR = "/etc/vt-tunnel/connections.d"

FILE_SUFFIX = ".conf"

PORT_MIN = 1
PORT_MAX = 65535

# Identifier values are interpolated into the daemon's ExecStart line as
# ssh arguments (REMOTE_USER@REMOTE_SERVER) and as su's user argument, so
# a leading dash would make ssh/su parse the value as a command-line
# option (e.g. a remote user of "-F.evil"). The charset is otherwise kept
# conservative: letters, digits, dot, dash, underscore. Used with
# fullmatch.
IDENTIFIER_PATTERN = r"(?!-)[A-Za-z0-9._-]+"

# A connection's name is its file name and its systemd instance name:
# 1-64 characters starting with a letter or digit (no leading dot — rules
# out hidden files and "."/".."; no leading dash or underscore). Used with
# fullmatch.
NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"


class FieldType(Enum):
    PORT = "port"
    IDENTIFIER = "identifier"
    NAME = "name"


@dataclass(frozen=True)
class CfgField:
    key: str
    type: FieldType | None
    example: str
    description: str
    dead: bool = False
    default: str = ""


NAME = CfgField(
    key="NAME",
    type=FieldType.NAME,
    example="home",
    description=(
        "The connection's name: its file name (without the .conf suffix) "
        "and its systemd instance name; deliberately not a key stored "
        "inside the file."
    ),
)

ENABLED = CfgField(
    key="ENABLED",
    type=None,
    example="false",
    description=(
        "Dead key: nothing consumes it; kept only so upgrades of the "
        "packaged example conffile do not break."
    ),
    dead=True,
)

RUN_DAEMON_USER = CfgField(
    key="RUN_DAEMON_USER",
    type=FieldType.IDENTIFIER,
    example="username",
    description="Local user the tunnel runs as.",
)

REMOTE_USER = CfgField(
    key="REMOTE_USER",
    type=FieldType.IDENTIFIER,
    example="example_user",
    description="SSH user on the remote server.",
)

REMOTE_SERVER = CfgField(
    key="REMOTE_SERVER",
    type=FieldType.IDENTIFIER,
    example="example_site.com",
    description="Server with the external IP and domain name.",
)

REMOTE_SERVER_SSH_PORT = CfgField(
    key="REMOTE_SERVER_SSH_PORT",
    type=FieldType.PORT,
    example="22",
    description="SSH port on the remote server.",
    default="22",
)

LOCAL_PORT = CfgField(
    key="LOCAL_PORT",
    type=FieldType.PORT,
    example="22",
    description="Local port to expose.",
)

REMOTE_PORT = CfgField(
    key="REMOTE_PORT",
    type=FieldType.PORT,
    example="5001",
    description=(
        "Port bound on the remote server, forwarding back to LOCAL_PORT."
    ),
)

FIELDS: tuple[CfgField, ...] = (
    NAME,
    ENABLED,
    RUN_DAEMON_USER,
    REMOTE_USER,
    REMOTE_SERVER,
    REMOTE_SERVER_SSH_PORT,
    LOCAL_PORT,
    REMOTE_PORT,
)

FIELD_BY_KEY: dict[str, CfgField] = {field.key: field for field in FIELDS}

DEFAULTS: dict[str, str] = {
    field.key: field.default for field in FIELDS if field.default
}

FILE_KEYS: tuple[str, ...] = tuple(
    field.key for field in FIELDS if field.key != NAME.key
)
