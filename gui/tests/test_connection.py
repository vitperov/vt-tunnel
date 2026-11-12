"""Tests for the per-connection value set: construction, reading, validation."""

import pytest

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.connection import Connection


def test_every_schema_field_present(valid_values):
    connection = Connection(valid_values)
    for key in config_schema.FIELD_BY_KEY:
        assert connection[key] == valid_values[key]
    assert set(connection.values()) == set(config_schema.FIELD_BY_KEY)


def test_missing_fields_empty(valid_values):
    del valid_values["REMOTE_SERVER_SSH_PORT"]
    del valid_values["LOCAL_PORT"]
    connection = Connection(valid_values)
    assert connection["REMOTE_SERVER_SSH_PORT"] == ""
    assert connection["LOCAL_PORT"] == ""
    assert connection["NAME"] == valid_values["NAME"]
    assert connection["REMOTE_SERVER"] == valid_values["REMOTE_SERVER"]


def test_empty_connection():
    connection = Connection({})
    for key in config_schema.FIELD_BY_KEY:
        assert connection[key] == ""


def test_unknown_field_rejected(valid_values):
    values = dict(valid_values)
    values["NOT_A_KEY"] = "x"
    with pytest.raises(ValueError) as excinfo:
        Connection(values)
    assert "NOT_A_KEY" in str(excinfo.value)


def test_several_unknown_fields_rejected_all_named(valid_values):
    values = dict(valid_values)
    values["FOO"] = "1"
    values["BAR"] = "2"
    with pytest.raises(ValueError) as excinfo:
        Connection(values)
    message = str(excinfo.value)
    assert "FOO" in message
    assert "BAR" in message


def test_values_returns_a_copy(valid_values):
    connection = Connection(valid_values)
    handed_out = connection.values()
    handed_out["NAME"] = "changed"
    handed_out["EXTRA"] = "x"
    assert connection["NAME"] == valid_values["NAME"]
    assert "EXTRA" not in connection.values()


def test_input_mapping_copied(valid_values):
    values = dict(valid_values)
    original_name = values["NAME"]
    connection = Connection(values)
    values["NAME"] = "changed"
    values["LOCAL_PORT"] = "9"
    assert connection["NAME"] == original_name
    assert connection["LOCAL_PORT"] == valid_values["LOCAL_PORT"]


def test_name(valid_values):
    connection = Connection(valid_values)
    assert connection.name == valid_values["NAME"]


def test_equality_by_value(valid_values, other_valid_values):
    assert Connection(valid_values) == Connection(dict(valid_values))
    assert Connection(valid_values) != Connection(other_valid_values)


def test_values_stored_verbatim():
    values = {
        "NAME": " My Name ",
        "REMOTE_USER": "User",
        "LOCAL_PORT": " 22 ",
    }
    connection = Connection(values)
    assert connection["NAME"] == " My Name "
    assert connection["REMOTE_USER"] == "User"
    assert connection["LOCAL_PORT"] == " 22 "


# --- validation: valid values ---


def test_schema_examples_are_valid(valid_values):
    assert Connection(valid_values).validate() == []


def test_other_valid_values_are_valid(other_valid_values):
    assert Connection(other_valid_values).validate() == []


@pytest.mark.parametrize("enabled", ["true", "false", "TRUE", "1", "0", "yes", "no", ""])
def test_enabled_values_are_valid(valid_values, enabled):
    values = dict(valid_values)
    values["ENABLED"] = enabled
    assert Connection(values).validate() == []


@pytest.mark.parametrize("port", ["1", "65535"])
def test_port_boundaries_are_valid(valid_values, port):
    for key in ("REMOTE_SERVER_SSH_PORT", "LOCAL_PORT", "REMOTE_PORT"):
        values = dict(valid_values)
        values[key] = port
        assert Connection(values).validate() == []


def test_leading_zero_ports_are_valid(valid_values):
    values = dict(valid_values)
    values["LOCAL_PORT"] = "022"
    values["REMOTE_PORT"] = "0005001"
    assert Connection(values).validate() == []


@pytest.mark.parametrize(
    "identifier",
    ["a", "A9", "a.b", "a-b", "a_b", ".lead", "_lead", "a.b-c_d_e", "0start"],
)
def test_identifier_charset_is_valid(valid_values, identifier):
    for key in ("RUN_DAEMON_USER", "REMOTE_USER", "REMOTE_SERVER"):
        values = dict(valid_values)
        values[key] = identifier
        assert Connection(values).validate() == []


@pytest.mark.parametrize(
    "enabled",
    ["any thing", "a#b", "a;b", "$PATH", "a|b", "true,false", "a=b", "0"],
)
def test_enabled_has_no_value_rules(valid_values, enabled):
    values = dict(valid_values)
    values["ENABLED"] = enabled
    assert Connection(values).validate() == []


# --- validation: invalid values ---


def test_ports_out_of_range(valid_values, out_of_range_ports):
    for port in out_of_range_ports:
        for key in ("REMOTE_SERVER_SSH_PORT", "LOCAL_PORT", "REMOTE_PORT"):
            values = dict(valid_values)
            values[key] = port
            errors = Connection(values).validate()
            assert len(errors) == 1, (
                f"{key}={port!r}: expected exactly one error, got {errors}"
            )
            assert errors[0].startswith(key + ":")


def test_port_error_names_the_allowed_range(valid_values):
    values = dict(valid_values)
    values["LOCAL_PORT"] = "70000"
    message = Connection(values).validate()[0]
    assert str(config_schema.PORT_MIN) in message
    assert str(config_schema.PORT_MAX) in message


@pytest.mark.parametrize(
    "key",
    [
        "NAME",
        "RUN_DAEMON_USER",
        "REMOTE_USER",
        "REMOTE_SERVER",
        "REMOTE_SERVER_SSH_PORT",
        "LOCAL_PORT",
        "REMOTE_PORT",
    ],
)
def test_empty_required_value_reported(valid_values, key):
    values = dict(valid_values)
    values[key] = ""
    errors = Connection(values).validate()
    assert len(errors) == 1
    assert errors[0].startswith(key + ":")
    assert "required" in errors[0]


def test_empty_connection_reports_every_required_field():
    errors = Connection({}).validate()
    reported = {error.split(":")[0] for error in errors}
    required = [f.key for f in config_schema.FIELDS if f.type is not None]
    assert reported == set(required)
    assert len(errors) == len(required)
    assert not any(error.startswith("ENABLED:") for error in errors)


def test_all_errors_reported_at_once(valid_values):
    values = dict(valid_values)
    values["NAME"] = "bad name"          # space
    values["REMOTE_USER"] = "$USER"      # injection
    values["LOCAL_PORT"] = "0"           # out of range
    values["ENABLED"] = "a\nb"           # unstorable
    errors = Connection(values).validate()
    reported = {error.split(":")[0] for error in errors}
    assert reported == {"NAME", "REMOTE_USER", "LOCAL_PORT", "ENABLED"}
    assert len(errors) == 4


def test_scoped_validation_reports_only_requested_keys(valid_values):
    values = dict(valid_values)
    values["NAME"] = "bad name"
    values["REMOTE_USER"] = "$USER"
    values["LOCAL_PORT"] = "0"
    errors = Connection(values).validate(["LOCAL_PORT"])
    assert [error.split(":")[0] for error in errors] == ["LOCAL_PORT"]


def test_scoped_validation_of_valid_keys_is_empty(valid_values):
    values = dict(valid_values)
    values["NAME"] = "bad name"
    values["ENABLED"] = "a\nb"
    assert Connection(values).validate(["REMOTE_USER", "REMOTE_SERVER_SSH_PORT"]) == []


def test_unknown_scope_keys_rejected(valid_values):
    with pytest.raises(ValueError) as excinfo:
        Connection(valid_values).validate(["REMOTE_USERS"])
    assert "REMOTE_USERS" in str(excinfo.value)


def test_dangerous_identifiers_rejected(valid_values, dangerous_identifiers):
    for value in dangerous_identifiers:
        for key in ("RUN_DAEMON_USER", "REMOTE_USER", "REMOTE_SERVER"):
            values = dict(valid_values)
            values[key] = value
            errors = Connection(values).validate()
            assert len(errors) == 1, (
                f"{key}={value!r}: expected exactly one error, got {errors}"
            )
            assert errors[0].startswith(key + ":")


def test_leading_dash_identifiers_rejected(valid_values, leading_dash_identifiers):
    for value in leading_dash_identifiers:
        for key in ("RUN_DAEMON_USER", "REMOTE_USER", "REMOTE_SERVER"):
            values = dict(valid_values)
            values[key] = value
            errors = Connection(values).validate()
            assert len(errors) == 1, (
                f"{key}={value!r}: expected exactly one error, got {errors}"
            )
            assert errors[0].startswith(key + ":")
            assert "dash" in errors[0]


def test_dangerous_ports_rejected(valid_values, dangerous_ports):
    for port in dangerous_ports:
        for key in ("REMOTE_SERVER_SSH_PORT", "LOCAL_PORT", "REMOTE_PORT"):
            values = dict(valid_values)
            values[key] = port
            errors = Connection(values).validate()
            assert len(errors) == 1, (
                f"{key}={port!r}: expected exactly one error, got {errors}"
            )
            assert errors[0].startswith(key + ":")


@pytest.mark.parametrize(
    "enabled",
    ["a\nb", "a\rb", "a\x00b", "a\\b", 'a"b', "a'b", " pad", "pad "],
)
def test_enabled_cannot_break_the_file(valid_values, enabled):
    values = dict(valid_values)
    values["ENABLED"] = enabled
    errors = Connection(values).validate()
    assert len(errors) == 1
    assert errors[0].startswith("ENABLED:")


# --- validation: NAME ---


@pytest.mark.parametrize(
    "name",
    ["home", "A", "9lives", "a.b", "a-b", "a_b", "a" * 64, "x"],
)
def test_valid_names(valid_values, name):
    values = dict(valid_values)
    values["NAME"] = name
    assert Connection(values).validate() == []


@pytest.mark.parametrize(
    "name",
    [
        "",
        " " + "a",
        "a b",
        ".hidden",
        "..",
        ".",
        "-lead",
        "_lead",
        "/etc",
        "a/b",
        "a" * 65,
        "a\nb",
        "naïve",
    ],
)
def test_invalid_names(valid_values, name):
    values = dict(valid_values)
    values["NAME"] = name
    errors = Connection(values).validate()
    assert errors, f"NAME={name!r} must be rejected"
    assert all(error.startswith("NAME:") for error in errors)


def test_dangerous_identifiers_are_invalid_names(valid_values, dangerous_identifiers):
    for name in dangerous_identifiers:
        values = dict(valid_values)
        values["NAME"] = name
        errors = Connection(values).validate()
        assert errors, f"NAME={name!r} must be rejected"
        assert all(error.startswith("NAME:") for error in errors)
