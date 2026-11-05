"""Config model for vt-tunnel-gui."""

import logging
from pathlib import Path

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.tunnel_config import TunnelConfig

log = logging.getLogger(__name__)


class Model:
    """Holds the config values of a ``TunnelConfig`` file."""

    def __init__(self, config: TunnelConfig) -> None:
        self.config = config
        self._values = self._empty_values()

    @property
    def config_path(self) -> Path:
        return self.config.path

    @staticmethod
    def _empty_values() -> dict[str, str]:
        return {field.key: "" for field in config_schema.FIELDS}

    def load(self) -> None:
        """(Re)read the config file.

        Keys known to the schema are taken from the file; keys missing from
        it are empty. If the file can't be read (e.g. it doesn't exist), all
        values are empty.
        """
        values = self._empty_values()
        try:
            parsed = self.config.read()
        except FileNotFoundError:
            log.warning("Config file not found: %s", self.config_path)
        except OSError as err:
            log.warning("Can't read config file %s: %s", self.config_path, err)
        else:
            for key in values:
                if key in parsed:
                    values[key] = parsed[key]
        self._values = values

    def values(self) -> dict[str, str]:
        """Return a copy of the current config values."""
        return dict(self._values)

    def config_exists(self) -> bool:
        return self.config.exists()

    def validate(self, values: dict[str, str]) -> dict[str, str]:
        """Return ``{key: error}`` for invalid values (empty if all valid)."""
        return self.config.validate(values)

    def save(self, values: dict[str, str], *, create: bool = False) -> None:
        """Write ``values`` to the config file.

        Raises ``ConfigValidationError``, ``FileNotFoundError`` (file absent
        and ``create`` is false) or ``OSError``; see ``TunnelConfig.write``.
        """
        self.config.write(values, create=create)
        self._values = dict(values)
