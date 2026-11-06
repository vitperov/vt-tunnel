"""The vt-tunnel connection files: one per connection, in one directory.

Layout, as specified in ``doc/config.md``::

    /etc/vt-tunnel/connections.d/<NAME>.conf

The file name is the connection's NAME (and the systemd instance name,
``vt-tunnel@<NAME>.service``); the file holds the other fields as
``KEY=VALUE`` lines, read by systemd via ``EnvironmentFile=``.

Parsing follows what systemd does with such a file, so the GUI shows the
values the daemon will get:

- lines starting with ``#`` or ``;`` (after leading whitespace) are
  comments; a ``#`` later in a line is part of the value
- lines without ``=`` are ignored
- the value is the rest of the line, surrounding whitespace stripped; if
  a key repeats, the last one wins

systemd also removes quotes and reads backslash escapes; the GUI doesn't,
so such values show up verbatim and fail validation (no valid value has
quotes or backslashes): a hand-edited file can't be saved back until
fixed.

Writing replaces the connection's key lines in place and keeps every
other line (comments, other keys) as it is. Values are validated first:
they end up in the daemon's command line, so unvalidated values could
inject shell commands.
"""

import logging
import os
import stat
import tempfile
from pathlib import Path

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.connection import Connection

log = logging.getLogger(__name__)

SUFFIX = config_schema.CONFIG_SUFFIX
NEW_FILE_MODE = 0o644  # root-owned, world-readable: no secrets inside
NEW_DIR_MODE = 0o755
COMMENT_CHARS = ("#", ";")
FILE_KEYS = tuple(f.key for f in config_schema.FILE_FIELDS)
NEW_FILE_HEADER = (
    "# vt-tunnel connection, read by systemd (EnvironmentFile=).\n"
    "# The connection's name is this file's name.\n"
)


class ValidationError(ValueError):
    """Values rejected by the schema; ``errors`` holds one message each."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class ConnectionsDir:
    """Reads and writes the connection files of one directory."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.read_errors: list[str] = []  # files :meth:`read` skipped

    @property
    def path(self) -> Path:
        return self._path

    def path_for(self, name: str) -> Path:
        """The file of connection ``name`` (which must be a valid NAME)."""
        return self._path / f"{name}{SUFFIX}"

    # ----------------------------------------------------------- directory

    def exists(self) -> bool:
        return self._path.exists()

    def is_dir(self) -> bool:
        return self._path.is_dir()

    def create(self) -> None:
        """Create the directory (and missing parents); ``OSError`` if it
        can't be."""
        self._path.mkdir(mode=NEW_DIR_MODE, parents=True, exist_ok=True)

    # ---------------------------------------------------------------- read

    def read(self) -> list[Connection]:
        """Return the connections, one per ``*.conf`` file, by name.

        Files that can't be read are skipped and listed in
        :attr:`read_errors`. ``OSError`` if the directory itself can't be
        listed (e.g. ``FileNotFoundError``).
        """
        self.read_errors = []
        connections = []
        for path in self._connection_files():
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError as err:
                self.read_errors.append(f"{path}: {err.strerror or err}")
                log.warning("Can't read %s: %s", path, err)
                continue
            connections.append(self.connection_from(name_of(path), text))
        return connections

    def _connection_files(self) -> list[Path]:
        files = [
            p for p in self._path.iterdir()
            if p.name.endswith(SUFFIX)
            and not p.name.startswith(".")  # hidden, e.g. our temp files
            and p.is_file()
        ]
        return sorted(files, key=lambda p: (name_of(p).casefold(), p.name))

    @staticmethod
    def connection_from(name: str, text: str) -> Connection:
        """The connection ``name`` with the schema values found in
        ``text``; keys missing from it are empty."""
        values = {k: v for k, v in parse(text).items() if k in FILE_KEYS}
        return Connection(values | {config_schema.NAME.key: name})

    # ------------------------------------------------------------ validate

    def validate(
        self, connection: Connection, old_name: str | None = None
    ) -> list[str]:
        """Error messages for saving ``connection`` (empty: OK).

        ``old_name`` is the name it is saved under now (``None`` for a new
        connection); another connection's name can't be taken.
        """
        errors = connection.validate()
        name = connection.name
        name_ok = not any(
            e.startswith(f"{config_schema.NAME.key}:") for e in errors
        )
        if name_ok and name != old_name and self.path_for(name).exists():
            errors.insert(0, (
                f"{config_schema.NAME.key}: a connection named \"{name}\" "
                "already exists"
            ))
        return errors

    # --------------------------------------------------------------- write

    def write(
        self, connection: Connection, old_name: str | None = None
    ) -> None:
        """Save ``connection``, as a new file or over ``old_name``'s.

        Renaming (``old_name`` given, and not the connection's name) moves
        the old file's content — comments, other keys — to the new name.
        Raises :class:`ValidationError` (nothing written) if
        :meth:`validate` fails, ``OSError`` if a file can't be written or
        the old one removed.
        """
        errors = self.validate(connection, old_name)
        if errors:
            raise ValidationError(errors)

        target = self.path_for(connection.name)
        source = self.path_for(old_name) if old_name else target
        renaming = source != target
        if not renaming:
            target = Path(os.path.realpath(target))  # write through symlinks
        try:
            # surrogateescape: undecodable bytes of other lines survive
            # the round trip unchanged.
            old_text = source.read_text(
                encoding="utf-8-sig", errors="surrogateescape"
            )
        except FileNotFoundError:
            old_text = None

        mode_from = source if old_text is not None else None
        _atomic_write(target, render(old_text, connection), mode_from)
        if renaming and old_text is not None:
            source.unlink()

    def delete(self, name: str) -> None:
        """Remove connection ``name``'s file (gone already: nothing to do);
        ``OSError`` if it can't be removed."""
        try:
            self.path_for(name).unlink()
        except FileNotFoundError:
            pass


def name_of(path: Path) -> str:
    """The connection name of a connection file."""
    return path.name[: -len(SUFFIX)]


def parse(text: str) -> dict[str, str]:
    """Parse file text into ``{KEY: VALUE}`` (all keys, last one wins)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        split = split_line(line)
        if split is not None:
            values[split[0]] = split[1]
    return values


def split_line(line: str) -> tuple[str, str] | None:
    """``(key, value)`` of an assignment line; ``None`` for comments,
    blank lines and lines without ``=``."""
    stripped = line.lstrip()
    if not stripped or stripped.startswith(COMMENT_CHARS):
        return None
    key, sep, value = stripped.partition("=")
    key = key.strip()
    if not sep or not key:
        return None
    return key, value.strip(" \t\r")


def render(old_text: str | None, connection: Connection) -> str:
    """The file text for ``connection``.

    From an existing file (``old_text``): each schema key's last line gets
    the new value, its earlier duplicates go, keys it lacks are appended;
    every other line stays as it was. A new file gets a header comment and
    the keys in schema order.
    """
    assignments = [f"{key}={connection[key]}" for key in FILE_KEYS]
    if old_text is None:
        return NEW_FILE_HEADER + "\n".join(assignments) + "\n"

    lines = old_text.splitlines()
    last_line_of: dict[str, int] = {}
    for number, line in enumerate(lines):
        split = split_line(line)
        if split is not None and split[0] in FILE_KEYS:
            last_line_of[split[0]] = number

    out = []
    for number, line in enumerate(lines):
        split = split_line(line)
        if split is not None and split[0] in FILE_KEYS:
            key = split[0]
            if last_line_of[key] == number:
                out.append(f"{key}={connection[key]}")
            # else: an earlier duplicate, overridden anyway — dropped
        else:
            out.append(line)
    out += [
        f"{key}={connection[key]}" for key in FILE_KEYS
        if key not in last_line_of
    ]
    return "\n".join(out) + "\n" if out else ""


def _atomic_write(target: Path, text: str, mode_from: Path | None) -> None:
    """Replace ``target`` with ``text`` atomically; take permission bits
    and owner from ``mode_from`` if given."""
    if mode_from is not None:
        st = mode_from.stat()
        mode, owner = stat.S_IMODE(st.st_mode), (st.st_uid, st.st_gid)
    else:
        mode, owner = NEW_FILE_MODE, None

    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(
            fd, "w", encoding="utf-8", errors="surrogateescape", newline="\n"
        ) as tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, mode)
        if owner is not None:
            try:
                os.chown(tmp_name, *owner)
            except PermissionError:
                pass  # not root: the file ends up owned by us
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

    dir_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)  # make the rename itself durable
    finally:
        os.close(dir_fd)
