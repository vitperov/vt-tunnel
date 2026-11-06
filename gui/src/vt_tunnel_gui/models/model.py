"""Config model for vt-tunnel-gui: loads, validates, saves and deletes
connections (one file each, see :mod:`connections_dir`)."""

import logging
from pathlib import Path

from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.connections_dir import (
    ConnectionsDir,
    ValidationError,
)

__all__ = ["Connection", "Model", "ValidationError"]

log = logging.getLogger(__name__)


class Model:
    """Holds the connections of one :class:`ConnectionsDir`, by name."""

    def __init__(self, store: ConnectionsDir) -> None:
        self._store = store
        self._connections: list[Connection] = []

    @property
    def config_dir(self) -> Path:
        return self._store.path

    def path_of(self, name: str) -> Path:
        """The file of connection ``name``."""
        return self._store.path_for(name)

    def load(self) -> None:
        """(Re)read the connections from the directory.

        If it can't be read (e.g. it doesn't exist), there are none.
        """
        try:
            self._connections = self._store.read()
        except OSError as err:
            log.warning("Can't read %s: %s", self.config_dir, err)
            self._connections = []

    def connections(self) -> list[Connection]:
        """Return a copy of the list (Connections themselves are immutable)."""
        return list(self._connections)

    def find(self, name: str) -> Connection | None:
        for connection in self._connections:
            if connection.name == name:
                return connection
        return None

    def validate(
        self, connection: Connection, old_name: str | None = None
    ) -> list[str]:
        """Error messages for saving ``connection`` (empty if OK);
        ``old_name``: its saved name, ``None`` if new."""
        return self._store.validate(connection, old_name)

    def save(
        self, connection: Connection, old_name: str | None = None
    ) -> None:
        """Write ``connection`` (renaming its file if its name changed).

        Raises :class:`ValidationError` (nothing is written) or ``OSError``.
        """
        self._store.write(connection, old_name)

    def delete(self, name: str) -> None:
        """Remove connection ``name``; ``OSError`` if it can't be."""
        self._store.delete(name)
