"""Config model for vt-tunnel-gui: loads, validates and saves connections."""

import logging
from collections.abc import Sequence
from pathlib import Path

from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.tunnel_config import TunnelConfig, ValidationError

__all__ = ["Connection", "Model", "ValidationError"]

log = logging.getLogger(__name__)


class Model:
    """Holds the list of connections of one :class:`TunnelConfig` file.

    A connection's number in the file is just its position in the list;
    it isn't stored, so removing one renumbers the following ones on save.
    """

    def __init__(self, config: TunnelConfig) -> None:
        self._config = config
        self._connections: list[Connection] = []

    @property
    def config_path(self) -> Path:
        return self._config.path

    def config_exists(self) -> bool:
        return self._config.exists()

    def load(self) -> None:
        """(Re)read the connections from the config file.

        If the file can't be read (e.g. it doesn't exist), there are none.
        """
        try:
            self._connections = self._config.read()
        except FileNotFoundError:
            log.warning("Config file not found: %s", self.config_path)
            self._connections = []
        except OSError as err:
            log.warning("Can't read config file %s: %s", self.config_path, err)
            self._connections = []

    def connections(self) -> list[Connection]:
        """Return a copy of the list (Connections themselves are immutable)."""
        return list(self._connections)

    @staticmethod
    def validate(connections: Sequence[Connection]) -> list[str]:
        """Return the error messages for ``connections`` (empty if OK)."""
        return TunnelConfig.validate(connections)

    def save(self, connections: Sequence[Connection]) -> None:
        """Write ``connections`` to the config file, numbered in order.

        Raises :class:`ValidationError` (nothing is written) or ``OSError``.
        """
        self._config.write(connections)
        self._connections = list(connections)
