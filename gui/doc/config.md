# Connection configuration (`/etc/vt-tunnel/connections.d/`)

`vt-tunnel-gui` manages the connections of the `vt-tunnel` daemon. This
document describes the connection files from the GUI side; the daemon
itself is a separate package (`vt-tunnel`, systemd template unit
`vt-tunnel@.service`).

## Location and layout

Each connection is one file:

    /etc/vt-tunnel/connections.d/<NAME>.conf

The file name (without the `.conf` suffix) is the connection's name and
the systemd instance name: the connection `home` lives in `home.conf`
and runs as the service instance `vt-tunnel@home.service`. Files are
root-owned, mode 644 — there are no secrets inside (ssh keys stay in
the run user's `~/.ssh`).

The GUI defaults to `/etc/vt-tunnel/connections.d`; another directory
can be set with the `--config-dir` option. At startup, if the directory
is missing, the GUI asks whether to create it — and when it cannot
(e.g. no permission on `/etc`), it suggests creating it as root with a
shell-quoted `sudo mkdir -p` command. If the path exists but is not a
directory, the GUI reports the error and exits.

## Which files are connections

A file counts as a connection when it ends in `.conf`, is not hidden
(no leading dot) and is a regular file or a symlink pointing at a
regular file. Anything else in the directory — editor backups, dpkg
leftovers, notes, the GUI's own temporary files — is ignored. The
connection list is sorted by name, case-insensitively.

## File format

The daemon reads each file through systemd's `EnvironmentFile=`, and
the GUI parses it the same way, so what the GUI shows is what the
daemon gets:

- one `KEY=VALUE` pair per line; the value is the rest of the line
  with surrounding whitespace stripped
- `#` or `;` at the start of a line makes the whole line a comment; a
  `#` later in a line is part of the value (`LOCAL_PORT=22 # ssh`
  stores the value `22 # ssh`)
- empty lines and lines without `=` are ignored
- if a key is repeated, the last assignment wins
- systemd strips quotes and reads backslash escapes, but the GUI does
  not: a hand-edited value containing quotes or backslashes is shown
  verbatim and fails validation, so such a file cannot be written back
  until the value is fixed

## Keys

| key | example | meaning |
|---|---|---|
| `NAME` | `home` | **not a key stored in the file** — the connection's name is its file name (without `.conf`) and its systemd instance name; 1–64 characters of letters, digits, `.`, `-`, `_`, starting with a letter or digit |
| `ENABLED` | `false` | **dead** — nothing consumes it; kept only so upgrades of the packaged example conffile do not break. Enable/disable via `systemctl enable/disable --now vt-tunnel@<NAME>` instead |
| `RUN_DAEMON_USER` | `username` | local user the tunnel runs as |
| `REMOTE_USER` | `example_user` | SSH user on the remote server |
| `REMOTE_SERVER` | `example_site.com` | server with the external IP and domain name |
| `REMOTE_SERVER_SSH_PORT` | `22` | SSH port on the remote server. Required: it is always passed to ssh with `-p`, so it overrides a `Port` entry for that host in `~/.ssh/config`. A file written before this key existed shows the field empty and demands a value on save — it is not assumed to be 22 |
| `LOCAL_PORT` | `22` | local port to expose |
| `REMOTE_PORT` | `5001` | port bound on the remote server, forwarding back to `LOCAL_PORT` |

The machine-readable counterpart of this table is
`src/vt_tunnel_gui/config_schema.py` — authoritative for the validation
rules (types, ranges, allowed charset).

## Example file

A new connection `home.conf`, exactly as the GUI writes it — the
two-line header comment, then the keys in schema order:

    # vt-tunnel connection, read by systemd (EnvironmentFile=).
    # The connection's name is this file's name.
    ENABLED=false
    RUN_DAEMON_USER=username
    REMOTE_USER=example_user
    REMOTE_SERVER=example_site.com
    REMOTE_SERVER_SSH_PORT=22
    LOCAL_PORT=22
    REMOTE_PORT=5001

## Writing rules

- A new connection becomes a new file with the two-line header comment
  above, then every key in schema order.
- Saving an existing file rewrites each key's assignment line in
  place; earlier duplicate lines of a key are dropped (the parse is
  last-wins), keys missing from the file are appended at the end, and
  every other line — comments, blank lines, unknown keys — passes
  through untouched.
- Renaming a connection writes the new file (keeping the other lines
  and the old file's permissions) and only then deletes the old one; a
  name that is already taken is refused.
- Deleting a connection removes its file.
- Files are replaced atomically, keeping the old file's permission
  bits and owner.

## Validation constraints

The template unit interpolates the values into a `bash -c` string:

    ExecStart=/usr/bin/sudo su -s /bin/bash -c 'autossh -N -p ${REMOTE_SERVER_SSH_PORT} ${REMOTE_USER}@${REMOTE_SERVER} -R ${REMOTE_PORT}:localhost:${LOCAL_PORT}' ${RUN_DAEMON_USER}

Because config values flow verbatim into that command line, a
hand-edited file could inject shell commands or ssh options. Any code
that writes a connection file (GUI or helper) must validate strictly
before writing:

- ports (`REMOTE_SERVER_SSH_PORT`, `LOCAL_PORT`, `REMOTE_PORT`):
  integer `1`–`65535`, ASCII digits only — no sign, spaces or options
  such as `22 -oX=y`
- identifiers (`RUN_DAEMON_USER`, `REMOTE_USER`, `REMOTE_SERVER`):
  the conservative charset — letters, digits, `.`, `-`, `_` — and the
  value must not start with `-`, or ssh/su would take it for a
  command-line option (e.g. a remote user of `-F.evil`)
- `NAME`: the file-name/systemd-instance pattern — 1–64 characters of
  letters, digits, `.`, `-`, `_`, starting with a letter or digit
- the untyped `ENABLED`: no line breaks, NUL, backslashes or quotes,
  and no surrounding whitespace

## Applying changes

systemd re-reads `EnvironmentFile=` when a service starts, so applying
an edit is `systemctl restart vt-tunnel@<NAME>` (no `daemon-reload`
needed). The GUI currently writes the files directly and therefore
needs write access to them (root for the system directory). Planned:
writing through polkit (action `org.vt-tunnel-gui.apply-config`,
helper `/usr/lib/vt-tunnel-gui/apply-config`, started via `pkexec`),
which would re-validate, write the file atomically, then restart the
service.
