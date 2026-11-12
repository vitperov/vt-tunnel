"""Value set of one connection: its raw config values.

Holds exactly the keys the schema declares (the connection's NAME
included) as raw strings exactly as they would appear in a config file.
Values are stored verbatim — no trimming, no case changes — and schema
keys missing from the input are empty; no defaults are applied here
(defaults only pre-fill new connections). The value set is immutable by
convention: it offers no way to change a value, so an edit means
building a new instance. It never touches the filesystem.
"""

from vt_tunnel_gui import config_schema


class Connection:
    """One connection's raw config values, keyed by schema key."""

    __slots__ = ("_values",)

    def __init__(self, values):
        """Build a value set from a key-to-string mapping of raw values.

        Keys outside the schema are rejected immediately, naming the
        offenders; schema keys missing from the mapping become empty
        strings.
        """
        unknown = sorted(
            key for key in values if key not in config_schema.FIELD_BY_KEY
        )
        if unknown:
            raise ValueError(
                "Unknown connection keys: " + ", ".join(unknown)
            )
        self._values = {
            key: values.get(key, "") for key in config_schema.FIELD_BY_KEY
        }

    def __getitem__(self, key):
        """Return the raw value stored for a schema key."""
        return self._values[key]

    @property
    def name(self):
        """The connection's name (its NAME value)."""
        return self._values[config_schema.NAME.key]

    def values(self):
        """A copy of the full key-to-value map."""
        return dict(self._values)

    def __eq__(self, other):
        """Two value sets are equal when all their values match."""
        if not isinstance(other, Connection):
            return NotImplemented
        return self._values == other._values

    def __repr__(self):
        return f"Connection({self._values!r})"
