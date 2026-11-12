"""Value set of one connection: its raw config values and their validation.

Holds exactly the keys the schema declares (the connection's NAME
included) as raw strings exactly as they would appear in a config file.
Values are stored verbatim — no trimming, no case changes — and schema
keys missing from the input are empty; no defaults are applied here
(defaults only pre-fill new connections). The value set is immutable by
convention: it offers no way to change a value, so an edit means
building a new instance. It never touches the filesystem.
"""

import re

from vt_tunnel_gui import config_schema

# The six characters a stored value must never contain: a line break or
# NUL would end the stored line, and systemd's EnvironmentFile reader
# treats backslashes as escapes and strips quotes, so the daemon would
# read back a different value than the one shown.
_UNSTORABLE_CHARACTERS = ("\n", "\r", "\x00", "\\", '"', "'")


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

    def validate(self, keys=None):
        """Check this connection's values against the schema's rules.

        Returns a list of error messages — one per invalid field, every
        message prefixed with the offending key and a colon; empty when
        everything is valid. All errors are reported at once, never
        fail-fast. NAME, every identifier and every port must be
        non-empty; ENABLED, the dead untyped field, may stay empty.

        With *keys* (an iterable of schema keys) only those fields are
        checked — used where only part of the values is about to be
        consumed, e.g. the ssh login check reading just the remote user,
        server and port. Keys outside the schema are rejected, naming
        the offenders, like unknown constructor keys.
        """
        if keys is None:
            scoped = set(config_schema.FIELD_BY_KEY)
        else:
            scoped = set(keys)
            unknown = sorted(scoped - config_schema.FIELD_BY_KEY.keys())
            if unknown:
                raise ValueError(
                    "Unknown connection keys: " + ", ".join(unknown)
                )
        errors = []
        for field in config_schema.FIELDS:
            if field.key not in scoped:
                continue
            value = self._values[field.key]
            if field.type is None:
                # the untyped dead field: no required value, only
                # storability rules
                error = _untyped_error(field.key, value)
            elif not value:
                error = f"{field.key}: a value is required"
            elif field.type is config_schema.FieldType.PORT:
                error = _port_error(field.key, value)
            elif field.type is config_schema.FieldType.NAME:
                error = _name_error(value)
            else:  # identifier
                error = _identifier_error(field.key, value)
            if error is not None:
                errors.append(error)
        return errors

    def __eq__(self, other):
        """Two value sets are equal when all their values match."""
        if not isinstance(other, Connection):
            return NotImplemented
        return self._values == other._values

    def __repr__(self):
        return f"Connection({self._values!r})"


def _is_ascii_digits(value):
    """True when value is a non-empty run of ASCII digits 0-9 only.

    Hand-rolled rather than str.isdigit(), which also accepts Unicode
    digits (e.g. Arabic-Indic or fullwidth) — a port of those would not
    survive the shell/systemd interpolation.
    """
    return bool(value) and all("0" <= character <= "9" for character in value)


def _port_error(key, value):
    """The error for a non-empty port value, naming the allowed range."""
    if not _is_ascii_digits(value) or not (
        config_schema.PORT_MIN <= int(value) <= config_schema.PORT_MAX
    ):
        return (
            f"{key}: port must be an integer from "
            f"{config_schema.PORT_MIN} to {config_schema.PORT_MAX}"
        )
    return None


def _name_error(value):
    """The error for a non-empty NAME value."""
    if re.fullmatch(config_schema.NAME_PATTERN, value) is None:
        return (
            "NAME: must be 1 to 64 characters of letters, digits, "
            "'.', '-' or '_', starting with a letter or digit"
        )
    return None


def _identifier_error(key, value):
    """The error for a non-empty identifier value."""
    if value.startswith("-"):
        return (
            f"{key}: must not start with a dash "
            "(ssh and su would read it as a command-line option)"
        )
    if re.fullmatch(config_schema.IDENTIFIER_PATTERN, value) is None:
        return (
            f"{key}: may contain only letters, digits, '.', '_' and '-'"
        )
    return None


def _untyped_error(key, value):
    """The error for the untyped dead field (ENABLED), empty allowed."""
    if value != value.strip() or any(
        character in value for character in _UNSTORABLE_CHARACTERS
    ):
        return (
            f"{key}: must not start or end with whitespace, and must "
            "not contain a line break, NUL, backslash or quote"
        )
    return None
