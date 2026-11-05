"""The vt-tunnel daemon config file (systemd ``EnvironmentFile=`` format).

Format, as specified in ``doc/config.md``:

- one ``KEY=VALUE`` pair per line
- everything after ``#`` is a comment
- no quoting and no variable expansion: the value is the rest of the
  line, verbatim (only surrounding whitespace is stripped)
- empty lines are ignored

Lines without ``=`` are ignored; if a key repeats, the last one wins.

Values are validated against ``config_schema`` before anything is
written: they end up inside the ``bash -c`` line of ``vt-tunnel.service``,
so unvalidated values could inject shell commands.
"""

import os
import re
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.config_schema import CfgField, FieldType

COMMENT_CHAR = "#"
NEW_FILE_MODE = 0o644  # dpkg conffile, root-owned, world-readable

_PORT_RE = re.compile(r"[0-9]+")  # ASCII digits only; int() is too lenient
_IDENTIFIER_RE = re.compile(config_schema.IDENTIFIER_PATTERN)
# Can't be stored in a value: they would end it early, or be lost or
# mangled when the file is read back.
_UNSTORABLE_CHARS = ("\n", "\r", "\0", COMMENT_CHAR)


class ValidationError(ValueError):
    """Values rejected by the schema; ``errors`` holds one message each."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def _field_error(field: CfgField, value: str) -> str | None:
    if field.type is FieldType.PORT:
        if not _PORT_RE.fullmatch(value) or not (
            config_schema.PORT_MIN <= int(value) <= config_schema.PORT_MAX
        ):
            return (
                f"{field.key}: must be an integer from "
                f"{config_schema.PORT_MIN} to {config_schema.PORT_MAX}"
            )
    elif field.type is FieldType.IDENTIFIER:
        if not _IDENTIFIER_RE.fullmatch(value):
            return (
                f"{field.key}: must be non-empty, contain only "
                "letters, digits, '.', '-' and '_', and not start with '-'"
            )
    elif value != value.strip() or any(c in value for c in _UNSTORABLE_CHARS):
        # No schema rule (e.g. the dead ENABLED key): only make sure the
        # value survives a write/read round trip.
        return f"{field.key}: contains characters that can't be stored"
    return None


class TunnelConfig:
    """Reads and writes one vt-tunnel config file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def read(self) -> dict[str, str]:
        """Return all ``{KEY: VALUE}`` pairs of the file.

        ``OSError`` (e.g. ``FileNotFoundError``) propagates to the caller.
        """
        text = self._path.read_text(encoding="utf-8-sig", errors="replace")
        return self.parse(text)

    @staticmethod
    def validate(values: Mapping[str, str]) -> list[str]:
        """Check ``values`` against the schema; return the error messages.

        Every schema key is required and no other key is accepted. An
        empty list means ``values`` can be written.
        """
        errors = [
            f"{key!r}: unknown key"
            for key in values
            if key not in config_schema.FIELD_BY_KEY
        ]
        for field in config_schema.FIELDS:
            if field.key not in values:
                errors.append(f"{field.key}: missing")
                continue
            error = _field_error(field, values[field.key])
            if error:
                errors.append(error)
        return errors

    def write(self, values: Mapping[str, str]) -> None:
        """Set ``values`` in the file, creating it if it doesn't exist.

        ``values`` must pass :meth:`validate`, otherwise
        :class:`ValidationError` is raised and nothing is written.

        The existing file is edited rather than regenerated: lines of other
        keys, comments and blank lines are kept verbatim. A line setting one
        of ``values`` is replaced by a bare ``KEY=VALUE`` (duplicates are
        dropped); keys not yet in the file are appended. The file is
        replaced atomically and keeps its permission bits.

        Raises :class:`ValidationError`, or ``OSError`` if the file can't
        be read or written.
        """
        errors = self.validate(values)
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

        new_text = self._merge(old_text or "", values)
        self._atomic_write(target, new_text, exists=old_text is not None)

    @staticmethod
    def parse(text: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in text.splitlines():
            key, value = TunnelConfig._split_line(line)
            if key is not None:
                values[key] = value
        return values

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
    def _merge(old_text: str, values: Mapping[str, str]) -> str:
        pending = dict(values)
        lines: list[str] = []
        for line in old_text.splitlines():
            key, _ = TunnelConfig._split_line(line)
            if key in values:
                # Inline comments on these lines are dropped on purpose:
                # real systemd doesn't treat a mid-line '#' as a comment.
                if key in pending:
                    lines.append(f"{key}={pending.pop(key)}")
                continue
            lines.append(line)
        lines.extend(f"{key}={value}" for key, value in pending.items())
        return "".join(line + "\n" for line in lines)

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
