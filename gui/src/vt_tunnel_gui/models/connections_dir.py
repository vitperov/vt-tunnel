"""Directory model: all filesystem behavior for one connections directory.

Holds the directory path, the path arithmetic for connection files, the
existence probes and directory creation used by the app's startup gate,
and the read side: discovering connection files, reading them BOM-
tolerantly, parsing them the way systemd's EnvironmentFile= does, and
building one value set per file. The write side (validation, saving,
renaming, deletion) lives in this module too.
"""

import logging
import os
import tempfile

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.connection import Connection

_log = logging.getLogger(__name__)


class ValidationError(Exception):
    """A connection's values failed validation; nothing was written.

    Carries the list of error messages as ``errors``; the exception text
    is the messages joined with newlines.
    """

    def __init__(self, messages):
        super().__init__("\n".join(messages))
        self.errors = list(messages)


class ConnectionsDir:
    """One directory of per-connection files: discovery, reading, parsing."""

    def __init__(self, directory):
        """Take the connections directory path, exactly as given.

        The path is never resolved or expanded; str and pathlib.Path are
        both kept verbatim. Read errors accumulate in the public
        ``read_errors`` list, empty until the first read.
        """
        self._directory = directory
        self.read_errors = []

    @property
    def directory(self):
        """The directory path exactly as given (never resolved or expanded)."""
        return self._directory

    def connection_path(self, name):
        """The file path for a connection name: name + .conf suffix."""
        return os.path.join(
            os.fspath(self._directory), name + config_schema.FILE_SUFFIX
        )

    def exists(self):
        """Whether the directory path exists (symlinks are followed)."""
        return os.path.exists(self._directory)

    def is_directory(self):
        """Whether the directory path is (or points at) a directory."""
        return os.path.isdir(self._directory)

    def create(self):
        """Create the directory with parents; an existing directory is fine.

        A failed creation (e.g. without permission) propagates.
        """
        os.makedirs(self._directory, exist_ok=True)

    def validate(self, connection, saved_name=None):
        """Check a connection's values against the schema and the directory.

        Runs the per-connection validation over all fields; every message
        is collected, never fail-fast. On top of the field errors, a
        "connection named X already exists" error is prepended when the
        name itself is well-formed, differs from the name the connection
        is currently saved under (``saved_name`` is None for a new
        connection), and a file with that name already exists. A name
        that is itself invalid is never checked against the files.
        Returns the message list; empty means the connection can be
        saved.
        """
        errors = connection.validate()
        name = connection.name
        name_is_valid = not connection.validate(keys=[config_schema.NAME.key])
        if (
            name_is_valid
            and name != saved_name
            and os.path.exists(self.connection_path(name))
        ):
            errors.insert(0, f"connection named {name} already exists")
        return errors

    def save(self, connection, saved_name=None):
        """Validate a connection and write it to its file atomically.

        Validation runs first; any error raises ValidationError and
        nothing is written. The plain save — no saved_name, or the
        connection already saved under its own name — writes the file
        named after the connection, resolving the target through
        symlinks first so an existing symlink is written through rather
        than replaced. The old file's text is the base for the rendered
        output (a missing old file means a fresh file); the write is
        atomic and preserves the old file's mode and owner.

        A saved_name different from the connection's name renames
        instead: the new file is written atomically under the new name
        — carrying the old file's mode and owner — and only then is the
        old file removed; a failed write keeps the old file.
        """
        errors = self.validate(connection, saved_name=saved_name)
        if errors:
            raise ValidationError(errors)
        if saved_name is not None and saved_name != connection.name:
            self._rename(connection, saved_name)
            return
        target = os.path.realpath(self.connection_path(connection.name))
        old_text = _read_old_text(target)
        if old_text is None:
            text = _render_new_file(connection)
        else:
            text = _render(old_text, connection)
        _atomic_write(target, text)

    def _rename(self, connection, saved_name):
        """Write the connection to its new file, then remove the old one.

        The old file's full text — comments, unknown keys, formatting —
        is the base for the rendered new file; the new file is written
        atomically under the new name carrying the old file's mode and
        owner, and only then is the old file unlinked. An old name whose
        file never existed means just a fresh file at the new name; a
        failed write keeps the old file and removes the temp file.
        """
        source = self.connection_path(saved_name)
        target = self.connection_path(connection.name)
        old_text = _read_old_text(source)
        if old_text is None:
            text = _render_new_file(connection)
        else:
            text = _render(old_text, connection)
        carry_from = source if old_text is not None else None
        _atomic_write(target, text, carry_from=carry_from)
        if old_text is not None:
            _remove_quietly(source)

    def delete(self, name):
        """Remove one connection's file.

        A file that is already gone is silently fine; any other OS error
        (e.g. no permission to remove from the directory) propagates.
        """
        try:
            os.unlink(self.connection_path(name))
        except FileNotFoundError:
            pass

    def read(self):
        """Discover, read and parse every connection file in the directory.

        One directory listing per read; a directory that cannot be listed
        raises the OS error. Files that cannot be read are skipped and
        reported in ``read_errors`` (reset at the start of every read).
        Results are sorted case-insensitively by connection name, ties
        broken by raw file name.
        """
        self.read_errors = []
        with os.scandir(self._directory) as scan:
            entries = [entry for entry in scan if _is_candidate(entry)]
        entries.sort(key=lambda entry: (_name_of(entry).lower(), entry.name))
        connections = []
        for entry in entries:
            text = self._read_file(entry.path)
            if text is None:
                continue
            connections.append(_connection_from_text(_name_of(entry), text))
        return connections

    def _read_file(self, path):
        """Read one file's text, recording (not raising) a read error.

        The file is read fully as UTF-8 with BOM stripping and undecodable
        bytes replaced with the replacement character, so the text is
        always display-safe. Returns None when the file cannot be read.
        """
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as file:
                return file.read()
        except OSError as error:
            message = f"{path}: {error}"
            self.read_errors.append(message)
            _log.warning("Skipping unreadable connection file: %s", message)
            return None


def _name_of(entry):
    """The connection name derived from a file name: name without the suffix."""
    return entry.name.removesuffix(config_schema.FILE_SUFFIX)


def _is_candidate(entry):
    """Whether a directory entry is a connection-file candidate.

    A candidate ends in .conf, is not hidden (no leading dot — which also
    excludes this model's own crash-orphaned temp files), and is a regular
    file or a symlink pointing at a regular file; broken symlinks,
    directories and other shapes are skipped.
    """
    if not entry.name.endswith(config_schema.FILE_SUFFIX):
        return False
    if entry.name.startswith("."):
        return False
    return entry.is_file()


def _parse_environment(text):
    """Parse file text the way systemd's EnvironmentFile= does.

    Leading whitespace is stripped; blank lines and lines whose first
    non-blank character is # or ; are comments; a line without = is
    ignored; the key is everything before the first =, whitespace-
    stripped (an empty key makes the line ignorable); the value is the
    rest of the line with surrounding space/tab/CR stripped; repeated
    keys: last one wins. No quote stripping and no backslash handling —
    quotes and backslashes are kept verbatim, so a hand-edited file
    containing them shows those characters and fails validation.
    """
    values = {}
    for line in text.split("\n"):
        line = line.strip(" \t\r")
        if not line or line[0] in "#;":
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip(" \t\r")
        if not key:
            continue
        values[key] = value.strip(" \t\r")
    return values


def _connection_from_text(name, text):
    """Build a Connection from one file's text.

    Parsing keeps only the schema's file keys (unknown keys dropped);
    NAME is forced to the name derived from the file name — a stray
    NAME= line inside the file is ignored for values.
    """
    parsed = _parse_environment(text)
    values = {
        key: value
        for key, value in parsed.items()
        if key in config_schema.FILE_KEYS
    }
    values[config_schema.NAME.key] = name
    return Connection(values)


# The fixed two-line header comment of a brand-new connection file: what
# the file is, and that the connection's name is this file's name.
_HEADER_LINES = (
    "# vt-tunnel connection, read by systemd (EnvironmentFile=).",
    "# The connection's name is this file's name.",
)


def _read_old_text(path):
    """The old file's text, or None when there is no old file.

    Read BOM-tolerantly (a leading BOM is stripped) keeping undecodable
    bytes as surrogates, so untouched lines re-encode to the same bytes
    they were read from. A missing file means a fresh file.
    """
    try:
        with open(path, encoding="utf-8-sig", errors="surrogateescape") as file:
            return file.read()
    except FileNotFoundError:
        return None


def _render_new_file(connection):
    """The text of a brand-new connection file.

    The fixed two-line header comment, then every file key in schema
    order, then a trailing newline.
    """
    lines = list(_HEADER_LINES)
    lines.extend(f"{key}={connection[key]}" for key in config_schema.FILE_KEYS)
    return "\n".join(lines) + "\n"


def _render(old_text, connection):
    """Render the new file text from the old text and a connection.

    Every schema key's last assignment line is replaced in place and
    its earlier duplicates dropped (the parse is last-wins); keys
    absent from the file are appended at the end in schema order;
    every other line — comments, blank lines, unknown keys, a stray
    NAME line — passes through untouched. The output always ends with
    exactly one trailing newline; a fully empty result stays empty.
    """
    lines = old_text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the text ended with a newline
    last_assignment = {}
    for index, line in enumerate(lines):
        key = _assignment_key(line)
        if key is not None:
            last_assignment[key] = index
    kept = []
    for index, line in enumerate(lines):
        key = _assignment_key(line)
        if key is not None:
            if last_assignment[key] != index:
                continue  # an earlier duplicate of a schema key
            line = f"{key}={connection[key]}"
        kept.append(line)
    for key in config_schema.FILE_KEYS:
        if key not in last_assignment:
            kept.append(f"{key}={connection[key]}")
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


def _assignment_key(line):
    """The schema file key a line assigns, or None.

    Mirrors the systemd-style parse: leading whitespace ignored, blank
    and comment lines ignored, a line without '=' ignored, the key is
    the text before the first '=' whitespace-stripped. Only schema file
    keys count — a stray NAME line or an unknown key is not an
    assignment and passes through untouched.
    """
    stripped = line.strip(" \t\r")
    if not stripped or stripped[0] in "#;":
        return None
    key, separator, _ = stripped.partition("=")
    if not separator:
        return None
    key = key.strip(" \t\r")
    if key in config_schema.FILE_KEYS:
        return key
    return None


def _atomic_write(path, text, carry_from=None):
    """Write text to path atomically, preserving the old mode and owner.

    The text is written to a hidden dotted temp file in the same
    directory (an interrupted write leaves something discovery skips)
    as UTF-8 with the same surrogate escape and LF line endings,
    flushed and fsynced. Permission bits are copied from the file
    ``carry_from`` names — the file being replaced, or the old file a
    rename carries the mode and owner over from — or 0644 for a new
    file; ownership is copied from that file's uid/gid when known, with
    a permission failure silently ignored. The temp file is then
    atomically renamed over the target, and the directory itself is
    fsynced last so the rename is durable. On any failure the temp file
    is removed and the error re-raised; the old file is never truncated
    in place.
    """
    directory = os.path.dirname(path)
    handle, temp_path = tempfile.mkstemp(
        dir=directory, prefix=".vt-tunnel-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(text.encode("utf-8", "surrogateescape"))
            file.flush()
            os.fsync(file.fileno())
        try:
            old_stat = os.stat(carry_from if carry_from is not None else path)
        except FileNotFoundError:
            old_stat = None
        os.chmod(temp_path, old_stat.st_mode & 0o7777 if old_stat else 0o644)
        if old_stat is not None:
            try:
                os.chown(temp_path, old_stat.st_uid, old_stat.st_gid)
            except PermissionError:
                pass
        os.replace(temp_path, path)
    except BaseException:
        _remove_quietly(temp_path)
        raise
    _fsync_directory(directory)


def _remove_quietly(path):
    """Remove a file, tolerating its already being gone."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _fsync_directory(directory):
    """Fsync a directory so a rename inside it is durable."""
    handle = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)
