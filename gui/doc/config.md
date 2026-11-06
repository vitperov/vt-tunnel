# Daemon configuration (`vt-tunnel.cfg`)

`vt-tunnel-gui` edits the settings of the `vt-tunnel` daemon. This document
describes them from the GUI side; the daemon itself is a separate package
(`vt-tunnel`, systemd unit `vt-tunnel.service`).

## Location and format

The daemon is configured with a single environment file:

    /etc/systemd/system/vt-tunnel.cfg

It is a dpkg conffile (root-owned, mode 644), read by systemd itself via
`EnvironmentFile=` in `vt-tunnel.service` — no daemon code parses it.

Format (systemd `EnvironmentFile=`):

- one `KEY=VALUE` pair per line
- everything after `#` is a comment
- no quoting and no variable expansion: the value is the rest of the
  line, verbatim
- empty lines are ignored

## Keys

The file holds a list of connections (tunnel pairs). `EnvironmentFile=`
has no lists, so every key of a connection carries the connection's
number as a suffix, starting at 1: `NAME1`, `ENABLED1`, ..., `NAME2`,
`ENABLED2`, ... The fields of one connection:

| key (+ number) | example | meaning |
|---|---|---|
| `NAME` | `home` | connection name, shown in the GUI's connection list; unique |
| `ENABLED` | `false` | **dead** — nothing consumes it; kept only for conffile-upgrade compatibility. Enable/disable via `systemctl enable/disable --now vt-tunnel` instead |
| `RUN_DAEMON_USER` | `username` | local user the tunnel runs as |
| `REMOTE_USER` | `vasya` | SSH user on the remote server |
| `REMOTE_SERVER` | `vasya.com` | server with the external IP and domain name |
| `LOCAL_PORT` | `22` | local port to expose |
| `REMOTE_PORT` | `5001` | port bound on the remote server, forwarding back to `LOCAL_PORT` |

Example with two connections, as written by the GUI:

    # ===== Connection 1: home =====
    NAME1=home
    ENABLED1=true
    RUN_DAEMON_USER1=username
    REMOTE_USER1=vasya
    REMOTE_SERVER1=vasya.com
    LOCAL_PORT1=22
    REMOTE_PORT1=5001

    # ===== Connection 2: office =====
    NAME2=office
    ...

Reading and writing rules:

- The number is a positive integer without leading zeros (`NAME01` and
  `NAME0` are not connection keys). Connections are ordered by number;
  gaps are allowed. A field missing from a connection is empty.
- On write, connections are renumbered 1..N in list order: deleting
  connection 2 turns connection 3 into connection 2. Each connection is
  preceded by a `# ===== Connection N: name =====` comment; these
  delimiters are regenerated on every write.
- Any other line — other keys, un-numbered keys such as `NAME=`, user
  comments — is kept verbatim at the top of the file; comments next to
  connection keys (including inline ones) are not kept.

The machine-readable counterpart of this table is
`src/vt_tunnel_gui/config_schema.py` — authoritative for the validation
rules (types, ranges, allowed charset). Keys that are not numbered
schema keys must be preserved verbatim when the file is rewritten;
comments need not be.

## Validation constraints

`vt-tunnel.service` interpolates the values into a `bash -c` string:

    ExecStart=/usr/bin/sudo su -s /bin/bash -c 'autossh -N ${REMOTE_USER1}@${REMOTE_SERVER1} -R ${REMOTE_PORT1}:localhost:${LOCAL_PORT1}' ${RUN_DAEMON_USER1}

Because config values flow verbatim into that shell line, a hand-edited
cfg can inject shell commands. Any code that writes this file (GUI or
helper) must validate strictly before writing:

- `LOCAL_PORT`, `REMOTE_PORT`: integer, `1`–`65535`
- `NAME`, `REMOTE_USER`, `RUN_DAEMON_USER`, `REMOTE_SERVER`: conservative
  charset — letters, digits, `.`, `-`, `_`; no whitespace, quotes, `$`,
  `;`, `|`, `&`, backticks or other shell metacharacters; must not start
  with `-`, or `ssh`/`su` would take the value for a command-line option
  (e.g. `REMOTE_USER=-F.evil`). `NAME` is not used by the daemon yet; it
  follows the same rule so it stays safe to use in commands or unit names.

## Applying changes

systemd re-reads `EnvironmentFile=` when the service starts, so applying
is `systemctl restart vt-tunnel` (no `daemon-reload` needed). The GUI does
not write `/etc` directly: it goes through polkit (action
`org.vt-tunnel-gui.apply-config`, helper
`/usr/lib/vt-tunnel-gui/apply-config`, started via `pkexec`), which
re-validates, writes the file atomically, then restarts the service.