"""Tests for the per-connection value set: construction and reading."""

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
