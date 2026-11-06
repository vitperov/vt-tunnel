"""The vt-tunnel daemon config file (systemd ``EnvironmentFile=`` format).

Format, as specified in ``doc/config.md``:

- one ``KEY=VALUE`` pair per line
- everything after ``#`` is a comment
- no quoting and no variable expansion: the value is the rest of the
  line, verbatim (only surrounding whitespace is stripped)
- empty lines are ignored

Lines without ``=`` are ignored; if a key repeats, the last one wins.

The file holds a list of connections. ``EnvironmentFile=`` has no lists,
so each schema key carries the 1-based connection number as a suffix:
``NAME1``, ``ENABLED1``, ..., ``NAME2``, ... On write, connections are
numbered 1..N in list order (gaps close up) and each one is preceded by
a delimiter comment. Other lines are kept verbatim.

Values are validated before anything is written: they end up inside the
``bash -c`` line of ``vt-tunnel.service``, so unvalidated values could
inject shell commands.
"""

import os
import re
import stat
import tempfile
from collections.abc import Sequence
from pathlib import Path

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.connection import COMMENT_CHAR, Connection

NEW_FILE_MODE = 0o644  # dpkg conffile, root-owned, world-readable

# KEY + connection number without leading zeros (NAME1, LOCAL_PORT12).
_NUMBERED_KEY_RE = re.compile(r"([A-Z_]+)([1-9][0-9]*)")
# Delimiter comment written before each connection; recognised (and
# regenerated) on rewrite.
_DELIMITER_RE = re.compile(r"#\s*=+\s*Connection\s+[0-9]+\b.*")


def delimiter(number: int, connection: Connection) -> str:
    return f"# ===== Connection {number}: {connection.name} ====="


class ValidationError(ValueError):
    """Values rejected by the schema; ``errors`` holds one message each."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class TunnelConfig:
    """Reads and writes the connections of one vt-tunnel config file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    # ---------------------------------------------------------------- read

    def read(self) -> list[Connection]:
        """Return the connections of the file, ordered by their number.

        Fields missing from the file are empty. Keys that are not numbered
        schema keys are ignored (and kept verbatim by :meth:`write`).
        ``OSError`` (e.g. ``FileNotFoundError``) propagates to the caller.
        """
        text = self._path.read_text(encoding="utf-8-sig", errors="replace")
        return self.connections_from(self.parse(text))

    @staticmethod
    def parse(text: str) -> dict[str, str]:
        """Parse config text into a flat ``{KEY: VALUE}`` dict."""
        values: dict[str, str] = {}
        for line in text.splitlines():
            key, value = TunnelConfig._split_line(line)
            if key is not None:
                values[key] = value
        return values

    @staticmethod
    def connections_from(flat: dict[str, str]) -> list[Connection]:
        """Group numbered keys (``NAME1``...) into connections by number."""
        by_number: dict[int, dict[str, str]] = {}
        for key, value in flat.items():
            split = TunnelConfig._split_numbered_key(key)
            if split is not None:
                field_key, number = split
                by_number.setdefault(number, {})[field_key] = value
        return [Connection(by_number[n]) for n in sorted(by_number)]

    @staticmethod
    def _split_line(line: str) -> tuple[str | None, str]:
        """Return ``(key, value)`` of a line, or ``(None, "")`` if none."""
        code = line.split(COMMENT_CHAR, 1)[0]
        key, sep, value = code.partition("=")
        key = key.strip()
        if not sep or not key:
            return None, ""
        return key, value.strip()

    @staticmethod
    def _split_numbered_key(key: str) -> tuple[str, int] | None:
        """``"NAME12"`` -> ``("NAME", 12)``; None if not a connection key."""
        match = _NUMBERED_KEY_RE.fullmatch(key)
        if match is None or match[1] not in config_schema.FIELD_BY_KEY:
            return None
        return match[1], int(match[2])

    # ------------------------------------------------------------ validate

    @staticmethod
    def validate(connections: Sequence[Connection]) -> list[str]:
        """Check every connection; return the error messages (empty: OK).

        Messages are prefixed with the connection's name — what the user
        sees — or, if it has no valid name, its number. Names must be
        unique.
        """
        errors: list[str] = []
        seen_names: set[str] = set()
        for number, connection in enumerate(connections, start=1):
            field_errors = connection.validate()
            name_ok = not any(
                e.startswith(f"{config_schema.NAME.key}:") for e in field_errors
            )
            if name_ok:
                label = f'Connection "{connection.name}"'
                if connection.name in seen_names:
                    field_errors.insert(0, (
                        f"{config_schema.NAME.key}: must be unique, "
                        "another connection has this name"
                    ))
                seen_names.add(connection.name)
            else:
                label = f"Connection {number}"
            errors.extend(f"{label}: {error}" for error in field_errors)
        return errors

    # --------------------------------------------------------------- write

    def write(self, connections: Sequence[Connection]) -> None:
        """Replace the connections in the file, creating it if missing.

        ``connections`` must pass :meth:`validate`, otherwise
        :class:`ValidationError` is raised and nothing is written.

        Lines that are not connection keys (other keys, comments) are kept
        verbatim, at the top; the connections follow, numbered 1..N, each
        after a delimiter comment. The file is replaced atomically and
        keeps its permission bits. Raises ``OSError`` if the file can't be
        read or written.
        """
        errors = self.validate(connections)
        if errors:
            raise ValidationError(errors)

        target = Path(os.path.realpath(self._path))  # write through symlinks
        try:
            # surrogateescape: undecodable bytes of other lines survive
            # the round trip unchanged.
            old_text = target.read_text(
                encoding="utf-8-sig", errors="surrogateescape"
            )
        except FileNotFoundError:
            old_text = None

        new_text = self.render(old_text or "", connections)
        self._atomic_write(target, new_text, exists=old_text is not None)

    @staticmethod
    def render(old_text: str, connections: Sequence[Connection]) -> str:
        """Return the new file text: kept lines of ``old_text``, then the
        connection blocks."""
        kept = [
            line for line in old_text.splitlines()
            if not TunnelConfig._is_connection_line(line)
        ]
        sections = []
        other = "\n".join(_squeeze_blank_lines(kept))
        if other:
            sections.append(other)
        for number, connection in enumerate(connections, start=1):
            lines = [delimiter(number, connection)]
            lines += [
                f"{field.key}{number}={connection[field.key]}"
                for field in config_schema.FIELDS
            ]
            sections.append("\n".join(lines))
        return "\n\n".join(sections) + "\n" if sections else ""

    @staticmethod
    def _is_connection_line(line: str) -> bool:
        """A numbered key line or one of our delimiter comments."""
        if _DELIMITER_RE.fullmatch(line.strip()):
            return True
        key, _ = TunnelConfig._split_line(line)
        return key is not None and TunnelConfig._split_numbered_key(key) is not None

    @staticmethod
    def _atomic_write(target: Path, text: str, exists: bool) -> None:
        if exists:
            st = target.stat()
            mode, owner = stat.S_IMODE(st.st_mode), (st.st_uid, st.st_gid)
        else:
            mode, owner = NEW_FILE_MODE, None

        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8", errors="surrogateescape",
                newline="\n",
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


def _squeeze_blank_lines(lines: list[str]) -> list[str]:
    """Drop leading/trailing blank lines and collapse runs of them.

    Removing the old connection blocks leaves their separating blank lines
    behind; without this they would pile up on every save.
    """
    result: list[str] = []
    for line in lines:
        if not line.strip() and (not result or not result[-1].strip()):
            continue
        result.append(line)
    while result and not result[-1].strip():
        result.pop()
    return result
