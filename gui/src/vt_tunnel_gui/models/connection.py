"""One tunnel connection: the fields of ``config_schema``, without index.

In the config file the fields of connection N carry an index suffix
(``NAME1``, ``ENABLED1``, ...); that numbering is the file's business
(see ``tunnel_config``). A Connection only knows its own field values.
"""

import re
from collections.abc import Iterable, Mapping

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.config_schema import CfgField, FieldType

COMMENT_CHAR = "#"

_PORT_RE = re.compile(r"[0-9]+")  # ASCII digits only; int() is too lenient
_IDENTIFIER_RE = re.compile(config_schema.IDENTIFIER_PATTERN)
# Can't be stored in a value: they would end it early, or be lost or
# mangled when the file is read back.
_UNSTORABLE_CHARS = ("\n", "\r", "\0", COMMENT_CHAR)


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


class Connection:
    """Immutable set of values for every schema field of one connection.

    Values are the raw strings as stored in the config file; fields not
    given are empty. To change a value, build a new Connection.
    """

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        values = values or {}
        unknown = sorted(set(values) - set(config_schema.FIELD_BY_KEY))
        if unknown:
            raise KeyError(f"Not connection fields: {', '.join(unknown)}")
        self._values: dict[str, str] = {
            field.key: values.get(field.key, "")
            for field in config_schema.FIELDS
        }

    def __getitem__(self, key: str) -> str:
        return self._values[key]

    def values(self) -> dict[str, str]:
        """Return a copy of the values, keyed by schema key (no index)."""
        return dict(self._values)

    @property
    def name(self) -> str:
        return self._values[config_schema.NAME.key]

    def validate(self, keys: Iterable[str] | None = None) -> list[str]:
        """Return one error message per invalid field (empty if valid).

        Only the fields named in ``keys`` are checked, if given.
        """
        wanted = None if keys is None else set(keys)
        errors = []
        for field in config_schema.FIELDS:
            if wanted is not None and field.key not in wanted:
                continue
            error = _field_error(field, self._values[field.key])
            if error:
                errors.append(error)
        return errors

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Connection):
            return NotImplemented
        return self._values == other._values

    __hash__ = None  # equality by value, but not meant as a dict key

    def __repr__(self) -> str:
        return f"Connection({self._values!r})"
