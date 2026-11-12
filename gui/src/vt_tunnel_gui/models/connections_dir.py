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
