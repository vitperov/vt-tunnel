"""Model stub for vt-tunnel-gui.

Does not read or write the cfg file yet: it keeps the last submitted
values in memory and prints them to the console on update.
"""

from vt_tunnel_gui import config_schema


class Model:
    """In-memory placeholder for the future config model."""

    def __init__(self) -> None:
        # Raw cfg strings keyed by config key; empty until a file is read.
        self._values: dict[str, str] = {
            field.key: "" for field in config_schema.FIELDS
        }

    def values(self) -> dict[str, str]:
        """Return a copy of the current config values."""
        return dict(self._values)

    def update(self, values: dict[str, str]) -> None:
        """Stub: print the submitted values and remember them."""
        print("Update requested:")
        for field in config_schema.FIELDS:
            print(f"  {field.key}={values.get(field.key, '')}")
        self._values = dict(values)
