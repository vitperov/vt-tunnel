# vt-tunnel connection configuration format (v2.0.0)

This document describes the configuration format of the vt-tunnel daemon —
a systemd-managed reverse SSH tunnel — as of config format **v2.0.0**:
the template unit `vt-tunnel@.service` reading connection files from
`/etc/vt-tunnel/connections.d/` via systemd's `EnvironmentFile=`.

One file describes one connection (one tunnel). The file is a plain
`KEY=VALUE` environment file: no sections, no quoting rules you can rely
on, no structure beyond what systemd's environment-file parser accepts
(rules below).

## How the daemon reads a connection

The daemon ships the template unit
`/lib/systemd/system/vt-tunnel@.service`. Each connection is one
instance of it, named after the connection:

- the instance `vt-tunnel@<NAME>.service` reads
  `EnvironmentFile=/etc/vt-tunnel/connections.d/<NAME>.conf`
  (`%i` in the template is the instance name `<NAME>`),
- then starts the tunnel, expanding the file's keys into the command:

  ```
  autossh -N -p ${REMOTE_SERVER_SSH_PORT} ${REMOTE_USER}@${REMOTE_SERVER} \
      -R ${REMOTE_PORT}:localhost:${LOCAL_PORT}
  ```

  run as the local user `${RUN_DAEMON_USER}`.

So every value ends up verbatim on the daemon's ssh command line — that
is why the validation rules below are strict. The tunnel binds
`REMOTE_PORT` on the remote server and forwards it back to `LOCAL_PORT`
on the local machine (a reverse tunnel, ssh `-R`).

## File layout and naming

- Default config directory: `/etc/vt-tunnel/connections.d/`.
- One connection = one file named `<NAME>.conf`, where `<NAME>` is the
  connection's name.
- Files are root-owned and mode `0644` (world-readable; no secrets are
  stored inside).
- The name `<NAME>` serves three roles at once: the file name
  (`<NAME>.conf`), the systemd instance (`vt-tunnel@<NAME>.service`),
  and the connection's identity. It must satisfy the NAME rules under
  [Validation](#validation-rules).
- The connection named `example` ships as the starter file
  `/etc/vt-tunnel/connections.d/example.conf` (reproduced verbatim
  below).

## Parsing rules (systemd `EnvironmentFile=`)

The instance reads its file with systemd's environment-file parser, so
a connection file follows those rules:

- One `KEY=VALUE` assignment per line. The value is everything after
  the first `=` on the line, with surrounding whitespace stripped.
- Lines whose first non-whitespace character is `#` or `;` are
  comments. A `#` anywhere else in the line is part of the value, not a
  comment.
- Blank lines and lines without `=` are ignored.
- If a key is assigned more than once, the last occurrence wins.
- systemd additionally strips quotes and interprets backslash escapes
  in values. Keep values plain (no quotes, no backslashes): anything
  else will not survive the file as literal text.

## Keys

`NAME` is not a key inside the file — it is the file's name. The file
contains the keys below (all of them; `ENABLED` may be omitted).

| Key | Meaning | Example |
|-----|---------|---------|
| `ENABLED` | Dead key: nothing consumes it; kept only so connection files written before v2.0.0 stay valid. Enable or disable a connection with `systemctl` (`start`/`stop`), not with this key. | `false` |
| `RUN_DAEMON_USER` | Local user the tunnel runs as. | `username` |
| `REMOTE_USER` | SSH user on the remote server. | `example_user` |
| `REMOTE_SERVER` | Remote server with the external IP (or domain name) to bind ports on. | `example_site.com` |
| `REMOTE_SERVER_SSH_PORT` | SSH port of the remote server. Required — the unit expands it in the tunnel command. New connection files are pre-filled with the default `22`. | `22` |
| `LOCAL_PORT` | Local port to expose through the tunnel. | `22` |
| `REMOTE_PORT` | Port bound on the remote server, forwarding back to `LOCAL_PORT`. | `5001` |

## Validation rules

Values are expanded into the daemon's ssh command line, so an
unvalidated value could inject ssh options or commands. A valid
connection therefore satisfies:

- **Ports** — `REMOTE_SERVER_SSH_PORT`, `LOCAL_PORT`, `REMOTE_PORT`:
  an integer from 1 to 65535, ASCII digits only (no sign, no spaces,
  no non-ASCII digits).
- **Identifiers** — `RUN_DAEMON_USER`, `REMOTE_USER`, `REMOTE_SERVER`:
  non-empty, only letters, digits, `.`, `-` and `_`
  (`[A-Za-z0-9._][A-Za-z0-9._-]*`), and must not start with `-` —
  otherwise ssh/su would take the value for a command-line option
  (e.g. `REMOTE_USER=-oProxyCommand=...` would inject an option).
- **NAME** (the file name): 1–64 characters, starting with a letter or
  digit, followed by letters, digits, `.`, `-` and `_`
  (`[A-Za-z0-9][A-Za-z0-9._-]*`). This rules out `/` (path separator),
  a leading `.` (hidden file — and the special names `.` and `..`), and
  a leading `-` or `_`. The name must be valid both as a file name and
  as a systemd instance name.

## Example connection file

`/etc/vt-tunnel/connections.d/example.conf` — the starter connection
shipped by the daemon package:

```bash
# vt-tunnel connection, read by systemd (EnvironmentFile=).
# The connection's name is this file's name.
ENABLED=false
RUN_DAEMON_USER=username
REMOTE_USER=example_user
REMOTE_SERVER=example_site.com
REMOTE_SERVER_SSH_PORT=22
LOCAL_PORT=22
REMOTE_PORT=5001
```

## Applying changes

A running instance reads its file only at start, so after creating or
editing `/etc/vt-tunnel/connections.d/<NAME>.conf` apply the change
with:

```
systemctl restart vt-tunnel@<NAME>.service
```

— systemd re-reads `EnvironmentFile=` when the service starts. Creating
a new connection means creating its file and starting the new instance
(`systemctl start vt-tunnel@<NAME>.service`); removing a connection
means stopping its instance and deleting the file.
