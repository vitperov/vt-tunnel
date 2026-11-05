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

The file describes one connection (one tunnel pair); support for
multiple connections is being prepared:

| key | example | meaning |
|---|---|---|
| `NAME` | `home` | connection name, shown in the GUI's connection list |
| `ENABLED` | `false` | **dead** — nothing consumes it; kept only for conffile-upgrade compatibility. Enable/disable via `systemctl enable/disable --now vt-tunnel` instead |
| `RUN_DAEMON_USER` | `username` | local user the tunnel runs as |
| `REMOTE_USER` | `vasya` | SSH user on the remote server |
| `REMOTE_SERVER` | `vasya.com` | server with the external IP and domain name |
| `LOCAL_PORT` | `22` | local port to expose |
| `REMOTE_PORT` | `5001` | port bound on the remote server, forwarding back to `LOCAL_PORT` |

The machine-readable counterpart of this table is
`src/vt_tunnel_gui/config_schema.py` — authoritative for the validation
rules (types, ranges, allowed charset). Keys not listed there must be
preserved verbatim when the file is rewritten; comments need not be.

## Validation constraints

`vt-tunnel.service` interpolates the values into a `bash -c` string:

    ExecStart=/usr/bin/sudo su -s /bin/bash -c 'autossh -N -p${REMOTE_SSH_PORT} ${REMOTE_USER}@${REMOTE_SERVER} -R ${REMOTE_PORT1}:localhost:${LOCAL_PORT1}' ${RUN_DAEMON_USER}

> **Pending daemon update:** this is the current `vt-tunnel.service`. It
> still reads the old keys `REMOTE_SSH_PORT`, `LOCAL_PORT1` and
> `REMOTE_PORT1`, which the schema replaced with `LOCAL_PORT` and
> `REMOTE_PORT` (`REMOTE_SSH_PORT` was dropped: ssh uses its default port
> or `~/.ssh/config`). The unit has to be updated to the new keys.

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