"""Facade model: the single object the rest of the GUI talks to.

Wraps one directory model and holds the loaded connection list. Every
other module of the GUI reaches the connections directory only through
this facade; the directory model's operations are delegated unchanged,
except that ``load`` swallows a directory-listing failure — a warning is
logged and the loaded list becomes empty — so a missing or unreadable
directory never breaks the GUI at startup.

The connection type and the validation-error type are re-exported here
as part of the facade's public surface.
"""

import logging

from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.connections_dir import ConnectionsDir, ValidationError

__all__ = ["Connection", "Model", "ValidationError"]

_log = logging.getLogger(__name__)


class Model:
    """The connections directory as one loaded list of connections."""

    def __init__(self, directory):
        """Wrap the directory model for the given connections directory."""
        self._store = ConnectionsDir(directory)
        self._connections = []

    @property
    def directory(self):
        """The directory path exactly as given (never resolved or expanded)."""
        return self._store.directory

    def connection_path(self, name):
        """The file path for a connection name: name + .conf suffix."""
        return self._store.connection_path(name)

    def load(self):
        """Re-read the directory and replace the in-memory list.

        A directory that cannot be listed (say, it is missing) never
        propagates: a warning is logged and the loaded list becomes
        empty. Everything else — read errors on single files, for
        instance — is the directory model's own behavior.
        """
        try:
            self._connections = self._store.read()
        except OSError as error:
            _log.warning(
                "Cannot list connections in %s: %s", self._store.directory, error
            )
            self._connections = []

    @property
    def connections(self):
        """A defensive copy of the loaded connection list.

        The list is copied so callers cannot change what the model
        holds; the connections themselves are immutable, so only the
        list needs copying.
        """
        return list(self._connections)

    def find(self, name):
        """The loaded connection with the given name, or None.

        A linear scan over the loaded list; a name that is not loaded
        yields None.
        """
        for connection in self._connections:
            if connection.name == name:
                return connection
        return None

    def validate(self, connection, saved_name=None):
        """Check a connection's values; the saved name drives the
        uniqueness check against the files. See the directory model."""
        return self._store.validate(connection, saved_name=saved_name)

    def save(self, connection, saved_name=None):
        """Validate and write a connection; a different saved name
        renames. Validation errors and OS errors propagate."""
        self._store.save(connection, saved_name=saved_name)

    def delete(self, name):
        """Remove one connection's file; a missing file is silently fine."""
        self._store.delete(name)
