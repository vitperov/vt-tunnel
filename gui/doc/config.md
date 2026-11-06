# Daemon configuration (`connections.d/<name>.conf`)

`vt-tunnel-gui` edits the settings of the `vt-tunnel` daemon. This document
describes them from the GUI side; the daemon itself is a separate package
(`vt-tunnel`).

## Location and layout

Each connection (tunnel) is its own file, named after the connection:

    /etc/vt-tunnel/connections.d/<NAME>.conf

and is run by its own instance of a systemd template unit:

    vt-tunnel@<NAME>.service    (EnvironmentFile=/etc/vt-tunnel/connections.d/%i.conf)

so a connection is enabled, started and stopped on its own
(`systemctl enable --now vt-tunnel@home`). The files are root-owned,
mode 644 (they hold no secrets: the SSH keys stay in the run user's
`~/.ssh`). `vt-tunnel-gui --config-dir DIR` edits another directory.

> **Pending daemon update:** the template unit doesn't exist yet. The
> current `vt-tunnel.service` still reads the old single file
> `/etc/systemd/system/vt-tunnel.cfg`, which the GUI no longer writes:
> until the daemon is rewritten, the GUI's connections are not used by
> it. The GUI's "Check daemon" button checks that old service for now
> and says so.

On start, the GUI checks the directory: if it doesn't exist, it asks
whether to create it (with missing parents) and exits if the answer is
no or it can't be created (e.g. not root: `sudo mkdir -p
/etc/vt-tunnel/connections.d`). A path that exists but isn't a directory
is an error too.

Files in the directory that are connections: `*.conf`, regular files (or
symlinks to them), not hidden (a leading `.`). Anything else — `*.conf~`,
`*.dpkg-old`, notes, the GUI's own temporary files (`.<name>.conf.*.tmp`)
— is ignored. Connections are listed by name, case-insensitively.

## File format

systemd reads the file itself (`EnvironmentFile=`); no daemon code parses
it. The GUI parses it the way systemd does, so it shows the values the
daemon will get:

- one `KEY=VALUE` pair per line; the value is the rest of the line,
  surrounding whitespace stripped
- lines starting with `#` or `;` (after optional whitespace) are
  comments. A `#` later in a line is **not** a comment: it is part of the
  value (`LOCAL_PORT=22 # ssh` gives the daemon `22 # ssh`, so the GUI
  flags it as an invalid port)
- lines without `=` and empty lines are ignored; if a key repeats, the
  last one wins
- systemd also strips quotes and reads backslash escapes (and a trailing
  backslash continues the line). The GUI doesn't: such values are shown
  verbatim and fail validation, since no valid value contains quotes or
  backslashes

## Keys

The connection's name is the file name; the file holds the other fields:

| key | example | meaning |
|---|---|---|
| `NAME` | `home` | **not a key**: the file name (`home.conf`) and the service instance (`vt-tunnel@home`); shown in the GUI's connection list; unique by nature. A `NAME=` line in a file is ignored |
| `ENABLED` | `false` | **dead** — nothing consumes it. Enable/disable a connection via `systemctl enable/disable --now vt-tunnel@<NAME>` instead |
| `RUN_DAEMON_USER` | `username` | local user the tunnel runs as |
| `REMOTE_USER` | `vasya` | SSH user on the remote server |
| `REMOTE_SERVER` | `vasya.com` | server with the external IP and domain name |
| `REMOTE_SERVER_SSH_PORT` | `22` | SSH port of the remote server; a new connection starts with the standard `22` |
| `LOCAL_PORT` | `22` | local port to expose |
| `REMOTE_PORT` | `5001` | port bound on the remote server, forwarding back to `LOCAL_PORT` |

`REMOTE_SERVER_SSH_PORT` is the port ssh connects to on the server. It
is required and always passed to ssh (`-p`), so it overrides a `Port`
for that host in `~/.ssh/config`. A file from before the key existed
lacks it: the GUI shows the field empty and asks for a value on save (it
doesn't assume 22, since the daemon wouldn't either). Not to be confused
with the old single-file config's `REMOTE_SSH_PORT`.

Example, `/etc/vt-tunnel/connections.d/home.conf` as written by the GUI:

    # vt-tunnel connection, read by systemd (EnvironmentFile=).
    # The connection's name is this file's name.
    ENABLED=false
    RUN_DAEMON_USER=username
    REMOTE_USER=vasya
    REMOTE_SERVER=vasya.com
    REMOTE_SERVER_SSH_PORT=22
    LOCAL_PORT=22
    REMOTE_PORT=5001

Writing rules:

- A new connection gets a new file: the header comment above, then the
  keys in schema order.
- Saving an existing one rewrites its keys **in place**: each key's last
  line gets the new value (earlier duplicates, overridden anyway, are
  dropped), keys the file lacks are appended. Every other line —
  comments, other keys — stays as it is.
- Renaming writes the file under the new name (keeping its other lines
  and permissions), then deletes the old one. A name that another file
  already has is refused.
- Deleting a connection deletes its file.
- Files are replaced atomically (temporary file, `rename`), keeping their
  permission bits and owner.

The machine-readable counterpart of the table is
`src/vt_tunnel_gui/config_schema.py` — authoritative for the validation
rules (types, ranges, allowed charset).

## Validation constraints

The current `vt-tunnel.service` interpolates the values into a `bash -c`
string (with the old key names), and a per-connection template built the
same way would do so with these keys:

    ExecStart=/usr/bin/sudo su -s /bin/bash -c 'autossh -N -p ${REMOTE_SERVER_SSH_PORT} ${REMOTE_USER}@${REMOTE_SERVER} -R ${REMOTE_PORT}:localhost:${LOCAL_PORT}' ${RUN_DAEMON_USER}

Because values flow verbatim into that shell line, a hand-edited file can
inject shell commands. Any code that writes a connection file (GUI or
helper) must validate strictly before writing:

- `REMOTE_SERVER_SSH_PORT`, `LOCAL_PORT`, `REMOTE_PORT`: integer, `1`–`65535`
  (ASCII digits only: no sign, spaces or options such as `22 -oX=y`)
- `REMOTE_USER`, `RUN_DAEMON_USER`, `REMOTE_SERVER`: conservative charset
  — letters, digits, `.`, `-`, `_`; no whitespace, quotes, `$`, `;`, `|`,
  `&`, backticks or other shell metacharacters; must not start with `-`,
  or `ssh`/`su` would take the value for a command-line option (e.g.
  `REMOTE_USER=-F.evil`)
- `NAME`: a file name and a systemd instance name — 1 to 64 letters,
  digits, `.`, `-`, `_`, starting with a letter or digit (so no `/`, no
  hidden files, no `.` or `..`, nothing that looks like an option)
- untyped values (`ENABLED`): no line breaks, NUL, backslashes or quotes,
  no surrounding whitespace — what systemd would read differently

## Applying changes

systemd re-reads `EnvironmentFile=` when a service starts, so applying a
change to a connection is `systemctl restart vt-tunnel@<NAME>` (no
`daemon-reload` needed).

The GUI currently writes the files directly, so it needs write access to
the directory (i.e. root for `/etc/vt-tunnel/connections.d`). Planned:
writing through polkit (action `org.vt-tunnel-gui.apply-config`, helper
`/usr/lib/vt-tunnel-gui/apply-config`, started via `pkexec`), which
re-validates, writes the file atomically, then restarts the service.
