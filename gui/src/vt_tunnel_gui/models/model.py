"""Config model for vt-tunnel-gui.

Reads the daemon config file; writing is still a stub that only prints
the submitted values to the console.
"""

import logging
from pathlib import Path

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models import config_file

log = logging.getLogger(__name__)


class Model:
    """Holds the config values loaded from ``config_path``."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._values = self._empty_values()

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
            parsed = config_file.read(self.config_path)
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

    def update(self, values: dict[str, str]) -> None:
        """Stub: print the submitted values (nothing is written yet)."""
        print("Update requested:")
        for field in config_schema.FIELDS:
            print(f"  {field.key}={values.get(field.key, '')}")
