"""Tests for the facade model."""

from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.model import Model


def test_load_with_missing_directory_yields_empty_list(tmp_path, caplog):
    """A directory that cannot be listed never breaks load."""
    model = Model(tmp_path / "missing.d")
    with caplog.at_level("WARNING"):
        model.load()
    assert model.connections == []
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_find_by_name_hit_and_miss(connections_dir, write_connection_file):
    """find returns the loaded connection by name, None when absent."""
    write_connection_file(
        {"NAME": "home", "REMOTE_USER": "user", "REMOTE_SERVER": "example.com"}
    )
    model = Model(connections_dir)
    model.load()
    found = model.find("home")
    assert isinstance(found, Connection)
    assert found.name == "home"
    assert model.find("no-such-connection") is None


def test_handed_out_list_is_independent(connections_dir, write_connection_file):
    """Mutating the handed-out list leaves the model's own list alone."""
    write_connection_file({"NAME": "home"})
    model = Model(connections_dir)
    model.load()
    handed_out = model.connections
    handed_out.append("garbage")
    handed_out.clear()
    assert [connection.name for connection in model.connections] == ["home"]
    assert model.find("home") is not None
