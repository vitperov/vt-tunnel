"""Tests of Connection: one connection's fields and their validation.

Validation rules: config_schema.py and doc/config.md.
"""

import pytest

from conftest import (
    DANGEROUS_IDENTIFIERS,
    DANGEROUS_PORTS,
    IDENTIFIER_KEYS,
    LEADING_DASH_IDENTIFIERS,
    OUT_OF_RANGE_PORTS,
    PORT_KEYS,
    VALID_VALUES,
)
from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.connection import Connection


def invalid_keys(values: dict[str, str]) -> list[str]:
    """Keys reported by Connection.validate() for ``values``."""
    return [e.split(":", 1)[0] for e in Connection(values).validate()]


class TestConstruction:
    def test_has_every_schema_field(self, valid):
        assert list(valid.values()) == [f.key for f in config_schema.FIELDS]

    def test_missing_fields_are_empty(self):
        connection = Connection({"NAME": "home"})
        assert connection["NAME"] == "home"
        assert all(
            connection[f.key] == ""
            for f in config_schema.FIELDS if f.key != "NAME"
        )

    def test_empty_connection(self):
        assert Connection().values() == {f.key: "" for f in config_schema.FIELDS}

    @pytest.mark.parametrize("key", ["NAME1", "OTHER", "name", ""])
    def test_unknown_field_is_rejected(self, key):
        with pytest.raises(KeyError):
            Connection({key: "x"})

    def test_values_returns_a_copy(self, valid):
        valid.values()["NAME"] = "changed"
        assert valid.name == VALID_VALUES["NAME"]

    def test_input_mapping_is_copied(self, valid_values):
        connection = Connection(valid_values)
        valid_values["NAME"] = "changed"
        assert connection.name == VALID_VALUES["NAME"]

    def test_name(self, valid):
        assert valid.name == "home"

    def test_equality_by_value(self, valid_values):
        assert Connection(valid_values) == Connection(dict(valid_values))
        assert Connection(valid_values) != Connection(
            valid_values | {"NAME": "x"}
        )


class TestValidValues:
    def test_schema_examples_are_valid(self, valid):
        assert valid.validate() == []

    @pytest.mark.parametrize("enabled", ["true", "false"])
    def test_enabled_values(self, valid_values, enabled):
        assert invalid_keys(valid_values | {"ENABLED": enabled}) == []

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize(
        "port", [str(config_schema.PORT_MIN), "443", str(config_schema.PORT_MAX)]
    )
    def test_port_range_boundaries_are_valid(self, valid_values, key, port):
        assert invalid_keys(valid_values | {key: port}) == []

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize(
        "value",
        ["a", "vasya", "VASYA_01", "my-host.example.com", "10.0.0.1",
         "vasya-", "a-b-c", "_svc", ".local", "9-lives"],
    )
    def test_identifier_charset_is_valid(self, valid_values, key, value):
        assert invalid_keys(valid_values | {key: value}) == []

    def test_enabled_has_no_value_rules(self, valid_values):
        # Dead key (see config_schema.ENABLED): any storable value is OK.
        for value in ["", "yes", "0"]:
            assert invalid_keys(valid_values | {"ENABLED": value}) == []


class TestInvalidValues:
    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("port", OUT_OF_RANGE_PORTS)
    def test_port_out_of_range(self, valid_values, key, port):
        assert invalid_keys(valid_values | {key: port}) == [key]

    def test_port_error_names_the_allowed_range(self, valid_values):
        [error] = Connection(valid_values | {"LOCAL_PORT": "0"}).validate()
        assert error.startswith("LOCAL_PORT:")
        assert "1" in error and "65535" in error

    @pytest.mark.parametrize("key", PORT_KEYS + IDENTIFIER_KEYS)
    def test_empty_value_is_invalid(self, valid_values, key):
        assert invalid_keys(valid_values | {key: ""}) == [key]

    def test_empty_connection_reports_every_required_field(self):
        assert sorted(invalid_keys({})) == sorted(
            PORT_KEYS + IDENTIFIER_KEYS + ["NAME"]
        )

    def test_all_errors_are_reported_at_once(self, valid_values):
        values = valid_values | {"LOCAL_PORT": "65536", "REMOTE_PORT": "-5"}
        assert invalid_keys(values) == ["LOCAL_PORT", "REMOTE_PORT"]

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_IDENTIFIERS)
    def test_dangerous_identifier(self, valid_values, key, value):
        assert invalid_keys(valid_values | {key: value}) == [key]

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize("value", LEADING_DASH_IDENTIFIERS)
    def test_leading_dash(self, valid_values, key, value):
        # ssh/su would parse the value as a command-line option.
        assert invalid_keys(valid_values | {key: value}) == [key]

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_PORTS)
    def test_dangerous_port(self, valid_values, key, value):
        assert invalid_keys(valid_values | {key: value}) == [key]

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("true\nREMOTE_USER1=x", id="newline-injects-key"),
            # systemd reads backslashes as escapes, strips quotes
            pytest.param("tr\\ue", id="backslash"),
            pytest.param("true\\", id="line-continuation"),
            pytest.param('"true"', id="double-quotes"),
            pytest.param("'true'", id="single-quotes"),
            pytest.param("true\r", id="carriage-return"),
            pytest.param("true\x00", id="nul"),
            pytest.param(" true", id="leading-space"),
        ],
    )
    def test_enabled_cannot_break_the_file(self, valid_values, value):
        assert invalid_keys(valid_values | {"ENABLED": value}) == ["ENABLED"]


class TestName:
    """NAME is a file name (<NAME>.conf) and a systemd instance name."""

    @pytest.mark.parametrize("name", [
        "home", "Home2", "office-web", "nas_backup", "a.b", "7",
        "x" * config_schema.NAME_MAX_LENGTH,
    ])
    def test_valid(self, valid_values, name):
        assert invalid_keys(valid_values | {"NAME": name}) == []

    @pytest.mark.parametrize("name", [
        pytest.param("", id="empty"),
        pytest.param(".", id="dot"),
        pytest.param("..", id="dot-dot"),
        pytest.param("../evil", id="parent-dir"),
        pytest.param("a/b", id="slash"),
        pytest.param("/etc/passwd", id="absolute"),
        pytest.param(".hidden", id="hidden-file"),
        pytest.param("-rf", id="leading-dash"),
        pytest.param("_x", id="leading-underscore"),
        pytest.param("my home", id="space"),
        pytest.param("a@b", id="at-splits-instance"),
        pytest.param("x" * (config_schema.NAME_MAX_LENGTH + 1),
                     id="too-long"),
        pytest.param("d\u00e9j\u00e0", id="non-ascii"),
    ])
    def test_invalid(self, valid_values, name):
        assert invalid_keys(valid_values | {"NAME": name}) == ["NAME"]

    @pytest.mark.parametrize("value", DANGEROUS_IDENTIFIERS)
    def test_dangerous_identifiers_are_invalid_names(
        self, valid_values, value
    ):
        assert invalid_keys(valid_values | {"NAME": value}) == ["NAME"]
