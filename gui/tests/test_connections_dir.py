"""Tests for the directory model: directory ops, reading, parsing."""

import os

import pytest

from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.connections_dir import ConnectionsDir, ValidationError

# The packaged example connection (daemon/example.conf): comment lines
# plus every schema key at its example value.
DOC_EXAMPLE_TEXT = (
    "# vt-tunnel connection, read by systemd (EnvironmentFile=).\n"
    "# The connection's name is this file's name.\n"
    "ENABLED=false\n"
    "RUN_DAEMON_USER=username\n"
    "REMOTE_USER=example_user\n"
    "REMOTE_SERVER=example_site.com\n"
    "REMOTE_SERVER_SSH_PORT=22\n"
    "LOCAL_PORT=22\n"
    "REMOTE_PORT=5001\n"
)


# ---------------------------------------------------------------------
# directory ops
# ---------------------------------------------------------------------


def test_directory_path_kept_as_given(tmp_path):
    raw = str(tmp_path / "sub" / ".." / "connections.d")
    model = ConnectionsDir(raw)
    assert model.directory == raw


def test_connection_file_path(connections_dir):
    model = ConnectionsDir(connections_dir)
    assert model.connection_path("home") == os.path.join(
        str(connections_dir), "home.conf"
    )


def test_exists(connections_dir, tmp_path):
    assert ConnectionsDir(connections_dir).exists() is True
    assert ConnectionsDir(tmp_path / "missing").exists() is False


def test_exists_follows_symlinks(tmp_path):
    target = tmp_path / "real-dir"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    model = ConnectionsDir(link)
    assert model.exists() is True
    assert model.is_directory() is True


def test_file_is_not_a_directory(tmp_path):
    file = tmp_path / "file"
    file.write_text("")
    model = ConnectionsDir(file)
    assert model.exists() is True
    assert model.is_directory() is False


def test_create_with_parents(tmp_path):
    model = ConnectionsDir(tmp_path / "a" / "b" / "connections.d")
    model.create()
    assert model.is_directory() is True


def test_create_existing_is_fine(connections_dir):
    model = ConnectionsDir(connections_dir)
    model.create()
    model.create()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_create_without_permission_raises(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    parent.chmod(0o555)
    try:
        with pytest.raises(OSError):
            ConnectionsDir(parent / "connections.d").create()
    finally:
        parent.chmod(0o755)


def test_read_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ConnectionsDir(tmp_path / "missing").read()


# ---------------------------------------------------------------------
# read
# ---------------------------------------------------------------------


def test_read_empty_directory(connections_dir):
    model = ConnectionsDir(connections_dir)
    assert model.read() == []
    assert model.read_errors == []


def test_doc_example(connections_dir, valid_values):
    (connections_dir / "home.conf").write_text(DOC_EXAMPLE_TEXT, encoding="utf-8")
    connections = ConnectionsDir(connections_dir).read()
    assert connections == [Connection(valid_values)]


def test_name_is_the_file_name(connections_dir, write_connection_file, valid_values):
    write_connection_file(valid_values)
    connections = ConnectionsDir(connections_dir).read()
    assert [connection.name for connection in connections] == ["home"]


def test_name_key_in_the_file_is_ignored(connections_dir, valid_values):
    lines = ["NAME=intruder"] + [
        f"{key}={valid_values[key]}" for key in valid_values if key != "NAME"
    ]
    (connections_dir / "home.conf").write_text("\n".join(lines) + "\n")
    connections = ConnectionsDir(connections_dir).read()
    assert [connection.name for connection in connections] == ["home"]
    assert connections == [Connection(valid_values)]


def test_sorted_by_name_ignoring_case(connections_dir):
    for name in ("b", "A", "a", "C"):
        (connections_dir / f"{name}.conf").write_text("")
    connections = ConnectionsDir(connections_dir).read()
    assert [connection.name for connection in connections] == ["A", "a", "b", "C"]


def test_other_files_are_not_connections(
    connections_dir, write_connection_file, valid_values
):
    write_connection_file(valid_values)
    (connections_dir / "notes.txt").write_text("x")
    (connections_dir / "backup.conf.old").write_text("x")
    (connections_dir / "conf").write_text("x")
    (connections_dir / ".hidden.conf").write_text("x")
    connections = ConnectionsDir(connections_dir).read()
    assert [connection.name for connection in connections] == ["home"]
    assert ConnectionsDir(connections_dir).read_errors == []


def test_subdirectories_are_not_connections(connections_dir, write_connection_file, valid_values):
    write_connection_file(valid_values)
    subdirectory = connections_dir / "sub.conf"
    subdirectory.mkdir()
    (subdirectory / "nested.conf").write_text("REMOTE_USER=nested\n")
    connections = ConnectionsDir(connections_dir).read()
    assert [connection.name for connection in connections] == ["home"]


def test_symlinked_file_is_read(connections_dir, tmp_path, valid_values):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "home.conf").write_text(DOC_EXAMPLE_TEXT, encoding="utf-8")
    (connections_dir / "home.conf").symlink_to(real / "home.conf")
    connections = ConnectionsDir(connections_dir).read()
    assert connections == [Connection(valid_values)]


def test_broken_symlink_is_skipped(connections_dir, tmp_path):
    (connections_dir / "broken.conf").symlink_to(tmp_path / "gone")
    model = ConnectionsDir(connections_dir)
    assert model.read() == []
    assert model.read_errors == []


@pytest.mark.parametrize("name", ["-bad", "_under", "a b"], ids=str)
def test_invalid_file_name_is_listed_to_be_fixed(connections_dir, name):
    (connections_dir / f"{name}.conf").write_text("")
    connections = ConnectionsDir(connections_dir).read()
    assert [connection.name for connection in connections] == [name]


def test_missing_keys_are_empty(connections_dir):
    (connections_dir / "home.conf").write_text("REMOTE_USER=user\n")
    connection = ConnectionsDir(connections_dir).read()[0]
    assert connection["REMOTE_USER"] == "user"
    assert connection["NAME"] == "home"
    assert connection["RUN_DAEMON_USER"] == ""
    assert connection["REMOTE_SERVER"] == ""
    assert connection["LOCAL_PORT"] == ""


def test_empty_file(connections_dir):
    (connections_dir / "home.conf").write_text("")
    connection = ConnectionsDir(connections_dir).read()[0]
    assert connection.name == "home"
    assert all(
        value == "" for key, value in connection.values().items() if key != "NAME"
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_unreadable_file_skipped_and_reported(
    connections_dir, write_connection_file, valid_values
):
    write_connection_file(valid_values)
    locked = connections_dir / "locked.conf"
    locked.write_text("REMOTE_USER=x\n")
    locked.chmod(0o000)
    try:
        model = ConnectionsDir(connections_dir)
        connections = model.read()
        assert [connection.name for connection in connections] == ["home"]
        assert len(model.read_errors) == 1
        assert "locked.conf" in model.read_errors[0]
    finally:
        locked.chmod(0o644)


def test_undecodable_bytes_do_not_crash(connections_dir):
    (connections_dir / "home.conf").write_bytes(b"REMOTE_USER=caf\xe9\n")
    connection = ConnectionsDir(connections_dir).read()[0]
    assert connection["REMOTE_USER"] == "caf\ufffd"


def test_crlf_and_bom(connections_dir):
    (connections_dir / "home.conf").write_bytes(
        b"\xef\xbb\xbfREMOTE_USER=user\r\nRUN_DAEMON_USER=tunnel\r\n"
    )
    connection = ConnectionsDir(connections_dir).read()[0]
    assert connection["REMOTE_USER"] == "user"
    assert connection["RUN_DAEMON_USER"] == "tunnel"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_read_errors_reset_each_read(connections_dir):
    locked = connections_dir / "locked.conf"
    locked.write_text("REMOTE_USER=x\n")
    locked.chmod(0o000)
    try:
        model = ConnectionsDir(connections_dir)
        model.read()
        assert len(model.read_errors) == 1
    finally:
        locked.chmod(0o644)
    model.read()
    assert model.read_errors == []


# ---------------------------------------------------------------------
# parse-like-systemd
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "expected"),
    [
        ("REMOTE_USER=user\n", "REMOTE_USER", "user"),
        ("   REMOTE_USER=user\n", "REMOTE_USER", "user"),
        ("\n\nREMOTE_USER=user\n\n", "REMOTE_USER", "user"),
        ("# comment\nREMOTE_USER=user\n", "REMOTE_USER", "user"),
        ("; comment\nREMOTE_USER=user\n", "REMOTE_USER", "user"),
        ("   # indented comment\nREMOTE_USER=user\n", "REMOTE_USER", "user"),
        ("no equals sign\nREMOTE_USER=user\n", "REMOTE_USER", "user"),
        ("=no key\nREMOTE_USER=user\n", "REMOTE_USER", "user"),
        ("  REMOTE_USER  =user\n", "REMOTE_USER", "user"),
        ("REMOTE_USER=  user \t\r\r\n", "REMOTE_USER", "user"),
        ("REMOTE_USER=first\nREMOTE_USER=second\n", "REMOTE_USER", "second"),
        ("REMOTE_SERVER=a=b\n", "REMOTE_SERVER", "a=b"),
        ("\r\nREMOTE_USER=user\r\n", "REMOTE_USER", "user"),
    ],
)
def test_parse_cases(connections_dir, text, key, expected):
    (connections_dir / "case.conf").write_text(text, encoding="utf-8")
    connections = ConnectionsDir(connections_dir).read()
    assert len(connections) == 1
    assert connections[0][key] == expected


def test_unknown_keys_dropped(connections_dir):
    (connections_dir / "home.conf").write_text("REMOTE_USER=u\nMYSTERY=x\n")
    connection = ConnectionsDir(connections_dir).read()[0]
    assert "MYSTERY" not in connection.values()
    assert connection["REMOTE_USER"] == "u"


def test_inline_hash_is_part_of_value(connections_dir):
    (connections_dir / "home.conf").write_text("REMOTE_SERVER=example.com # home\n")
    connection = ConnectionsDir(connections_dir).read()[0]
    assert connection["REMOTE_SERVER"] == "example.com # home"


def test_inline_comment_is_flagged(connections_dir):
    (connections_dir / "home.conf").write_text("REMOTE_SERVER=example.com # home\n")
    connection = ConnectionsDir(connections_dir).read()[0]
    errors = connection.validate()
    assert any(error.startswith("REMOTE_SERVER:") for error in errors)


def test_quotes_and_backslashes_kept_and_flagged(connections_dir):
    (connections_dir / "home.conf").write_text(
        'REMOTE_USER="user"\nRUN_DAEMON_USER=a\\b\n'
    )
    connection = ConnectionsDir(connections_dir).read()[0]
    assert connection["REMOTE_USER"] == '"user"'
    assert connection["RUN_DAEMON_USER"] == "a\\b"
    errors = connection.validate()
    assert any(error.startswith("REMOTE_USER:") for error in errors)
    assert any(error.startswith("RUN_DAEMON_USER:") for error in errors)


# ---------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------


def test_validation_error_carries_messages():
    error = ValidationError(["NAME: bad", "LOCAL_PORT: worse"])
    assert error.errors == ["NAME: bad", "LOCAL_PORT: worse"]
    assert str(error) == "NAME: bad\nLOCAL_PORT: worse"


def test_validate_valid(connections_dir, valid_values):
    model = ConnectionsDir(connections_dir)
    assert model.validate(Connection(valid_values)) == []


def test_validate_saving_under_its_own_name(connections_dir, valid_values):
    (connections_dir / "home.conf").write_text(DOC_EXAMPLE_TEXT, encoding="utf-8")
    model = ConnectionsDir(connections_dir)
    assert model.validate(Connection(valid_values), saved_name="home") == []


def test_validate_new_with_taken_name(connections_dir, valid_values):
    (connections_dir / "home.conf").write_text(DOC_EXAMPLE_TEXT, encoding="utf-8")
    model = ConnectionsDir(connections_dir)
    errors = model.validate(Connection(valid_values), saved_name=None)
    assert errors == ["connection named home already exists"]


def test_validate_invalid_name_not_checked_against_files(
    connections_dir, valid_values
):
    (connections_dir / "a b.conf").write_text("")
    values = dict(valid_values, NAME="a b")
    model = ConnectionsDir(connections_dir)
    errors = model.validate(Connection(values), saved_name=None)
    assert any(error.startswith("NAME:") for error in errors)
    assert not any("already exists" in error for error in errors)


def test_validate_path_like_name_not_written(connections_dir, valid_values):
    values = dict(valid_values, NAME="sub/home")
    model = ConnectionsDir(connections_dir)
    errors = model.validate(Connection(values), saved_name=None)
    assert any(error.startswith("NAME:") for error in errors)
    assert list(connections_dir.iterdir()) == []


def test_validate_dangerous_identifier_not_written(connections_dir, valid_values):
    values = dict(valid_values, RUN_DAEMON_USER="a;b")
    model = ConnectionsDir(connections_dir)
    errors = model.validate(Connection(values), saved_name=None)
    assert any(error.startswith("RUN_DAEMON_USER:") for error in errors)
    assert not any("already exists" in error for error in errors)


def test_validate_dangerous_port_not_written(connections_dir, valid_values):
    values = dict(valid_values, LOCAL_PORT="22;23")
    model = ConnectionsDir(connections_dir)
    errors = model.validate(Connection(values), saved_name=None)
    assert any(error.startswith("LOCAL_PORT:") for error in errors)


def test_validate_hand_edited_injection_read_verbatim_and_flagged(connections_dir):
    (connections_dir / "home.conf").write_text(
        'REMOTE_USER="user"\nRUN_DAEMON_USER=a\\b\n', encoding="utf-8"
    )
    model = ConnectionsDir(connections_dir)
    connection = model.read()[0]
    assert connection["REMOTE_USER"] == '"user"'
    errors = model.validate(connection, saved_name="home")
    assert any(error.startswith("REMOTE_USER:") for error in errors)
    assert any(error.startswith("RUN_DAEMON_USER:") for error in errors)


def test_validate_rejected_newline_cannot_add_line(connections_dir, valid_values):
    values = dict(valid_values, REMOTE_SERVER="evil\nENABLED=true")
    model = ConnectionsDir(connections_dir)
    errors = model.validate(Connection(values), saved_name=None)
    assert any(error.startswith("REMOTE_SERVER:") for error in errors)


# ---------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------


def test_delete(connections_dir, write_connection_file, valid_values):
    write_connection_file(valid_values)
    model = ConnectionsDir(connections_dir)
    model.delete("home")
    assert not (connections_dir / "home.conf").exists()
    assert model.read() == []


def test_delete_already_gone(connections_dir):
    ConnectionsDir(connections_dir).delete("ghost")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_delete_without_permission_raises(connections_dir):
    (connections_dir / "home.conf").write_text("")
    connections_dir.chmod(0o555)
    try:
        with pytest.raises(OSError):
            ConnectionsDir(connections_dir).delete("home")
    finally:
        connections_dir.chmod(0o755)
