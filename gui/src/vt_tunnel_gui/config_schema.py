"""Machine-readable schema of the vt-tunnel daemon configuration.

Describes the keys of ``/etc/systemd/system/vt-tunnel.cfg`` — the
authoritative source for their types, validation rules and semantics.
The file format and the reasoning behind the rules live in
``doc/config.md``; parsing, validation and writing are NOT done here —
they belong to the config model.
"""

from dataclasses import dataclass
from enum import Enum

DEFAULT_CONFIG_PATH = "/etc/systemd/system/vt-tunnel.cfg"

PORT_MIN = 1
PORT_MAX = 65535

# Conservative charset; must not start with "-", or ssh/su would take the
# value for a command-line option (e.g. REMOTE_USER=-oProxyCommand...).
IDENTIFIER_PATTERN = r"[A-Za-z0-9._][A-Za-z0-9._-]*"


class FieldType(Enum):
    PORT = "port"
    IDENTIFIER = "identifier"


@dataclass(frozen=True)
class CfgField:
    key: str
    type: FieldType | None
    example: str
    description: str
    dead: bool = False


ENABLED = CfgField(
    key="ENABLED",
    type=None,
    example="false",
    description=(
        "Dead key: nothing consumes it; kept only for conffile-upgrade "
        "compatibility. Enable/disable the service via systemctl instead."
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
    example="vasya",
    description="SSH user on the remote server.",
)

REMOTE_SERVER = CfgField(
    key="REMOTE_SERVER",
    type=FieldType.IDENTIFIER,
    example="vasya.com",
    description="Server with the external IP and domain name.",
)

REMOTE_SSH_PORT = CfgField(
    key="REMOTE_SSH_PORT",
    type=FieldType.PORT,
    example="22",
    description="SSH port on the remote server.",
)

LOCAL_PORT1 = CfgField(
    key="LOCAL_PORT1",
    type=FieldType.PORT,
    example="22",
    description="Local port to expose.",
)

REMOTE_PORT1 = CfgField(
    key="REMOTE_PORT1",
    type=FieldType.PORT,
    example="5001",
    description=(
        "Port bound on the remote server, forwarding back to LOCAL_PORT1."
    ),
)

FIELDS: tuple[CfgField, ...] = (
    ENABLED,
    RUN_DAEMON_USER,
    REMOTE_USER,
    REMOTE_SERVER,
    REMOTE_SSH_PORT,
    LOCAL_PORT1,
    REMOTE_PORT1,
)

FIELD_BY_KEY: dict[str, CfgField] = {field.key: field for field in FIELDS}