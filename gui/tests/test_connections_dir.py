"""Tests of ConnectionsDir: one file per connection, <NAME>.conf.

File format and validation rules: doc/config.md, config_schema.py.
Per-field rules are tested in detail in test_connection.py; here they are
checked through the files (read, validate, write).
"""

import os
import stat
from pathlib import Path

import pytest

from conftest import (
    DANGEROUS_IDENTIFIERS,
    DANGEROUS_PORTS,
    IDENTIFIER_KEYS,
    LEADING_DASH_IDENTIFIERS,
    OTHER_VALUES,
    PORT_KEYS,
    VALID_VALUES,
    conf_text,
    write_conf,
)
from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.connections_dir import (
    NEW_FILE_HEADER,
    NEW_FILE_MODE,
    ConnectionsDir,
    ValidationError,
    parse,
)

# The file of VALID_VALUES as the writer creates it (the doc example).
HOME_CONF = """\
# vt-tunnel connection, read by systemd (EnvironmentFile=).
# The connection's name is this file's name.
ENABLED=false
RUN_DAEMON_USER=username
REMOTE_USER=vasya
REMOTE_SERVER=vasya.com
REMOTE_SERVER_SSH_PORT=22
LOCAL_PORT=22
REMOTE_PORT=5001
"""


def snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in directory.iterdir()}


def assert_write_rejected(
    store: ConnectionsDir, connection: Connection, old_name=None
) -> ValidationError:
    """Writing raises ValidationError and leaves the directory unchanged."""
    before = snapshot(store.path)
    with pytest.raises(ValidationError) as info:
        store.write(connection, old_name)
    assert snapshot(store.path) == before  # no file touched, no temp left
    return info.value


def temp_leftovers(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


def changed(**values) -> Connection:
    return Connection(VALID_VALUES | values)


# --------------------------------------------------------------------------
# The directory
# --------------------------------------------------------------------------


class TestDirectory:
    def test_path_is_kept_as_given(self):
        assert ConnectionsDir(Path("rel/dir")).path == Path("rel/dir")

    def test_file_of_a_connection(self, store):
        assert store.path_for("home") == store.path / "home.conf"

    def test_exists(self, store, tmp_path):
        assert store.exists() and store.is_dir()
        missing = ConnectionsDir(tmp_path / "missing")
        assert not missing.exists() and not missing.is_dir()

    def test_file_is_not_a_directory(self, tmp_path):
        path = tmp_path / "file"
        path.write_text("")
        store = ConnectionsDir(path)
        assert store.exists() and not store.is_dir()

    def test_create_with_parents(self, tmp_path):
        store = ConnectionsDir(tmp_path / "etc" / "vt-tunnel" / "conn.d")
        store.create()
        assert store.is_dir()
        assert store.read() == []

    def test_create_existing_is_fine(self, store):
        store.create()
        assert store.is_dir()

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_create_without_permission(self, tmp_path):
        parent = tmp_path / "ro"
        parent.mkdir(mode=0o555)
        try:
            with pytest.raises(PermissionError):
                ConnectionsDir(parent / "connections.d").create()
        finally:
            parent.chmod(0o755)

    def test_read_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ConnectionsDir(tmp_path / "missing").read()


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


class TestRead:
    def test_empty_directory(self, store):
        assert store.read() == []

    def test_doc_example(self, store):
        (store.path / "home.conf").write_text(HOME_CONF)
        assert store.read() == [Connection(VALID_VALUES)]

    def test_name_is_the_file_name(self, store):
        write_conf(store.path, VALID_VALUES | {"NAME": "office-web"})
        [connection] = store.read()
        assert connection.name == "office-web"

    def test_name_key_in_the_file_is_ignored(self, store):
        (store.path / "home.conf").write_text(
            "NAME=other\n" + conf_text(VALID_VALUES)
        )
        assert store.read()[0].name == "home"

    def test_sorted_by_name_ignoring_case(self, store):
        for name in ["beta", "Alpha", "gamma", "alpha2"]:
            write_conf(store.path, VALID_VALUES | {"NAME": name})
        assert [c.name for c in store.read()] == [
            "Alpha", "alpha2", "beta", "gamma"
        ]

    @pytest.mark.parametrize("name", [
        "notes.txt", "home.conf~", "home.conf.dpkg-old", "home.cfg",
        ".hidden.conf", ".home.conf.abc123.tmp",
    ])
    def test_other_files_are_not_connections(self, store, name):
        (store.path / name).write_text(conf_text(VALID_VALUES))
        assert store.read() == []

    def test_subdirectories_are_not_connections(self, store):
        (store.path / "sub.conf").mkdir()
        assert store.read() == []

    def test_symlinked_file_is_read(self, store, tmp_path):
        real = tmp_path / "real.conf"
        real.write_text(conf_text(VALID_VALUES))
        (store.path / "home.conf").symlink_to(real)
        assert store.read() == [Connection(VALID_VALUES)]

    def test_invalid_file_name_is_listed_to_be_fixed(self, store):
        (store.path / "my home.conf").write_text(conf_text(VALID_VALUES))
        [connection] = store.read()
        assert connection.name == "my home"
        assert store.validate(connection, "my home")[0].startswith("NAME:")

    def test_missing_keys_are_empty(self, store):
        (store.path / "home.conf").write_text("REMOTE_USER=vasya\n")
        [connection] = store.read()
        assert connection["REMOTE_USER"] == "vasya"
        assert connection["LOCAL_PORT"] == ""

    def test_empty_file(self, store):
        (store.path / "home.conf").write_text("")
        [connection] = store.read()
        assert connection == Connection({"NAME": "home"})

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_unreadable_file_is_skipped_and_reported(self, store):
        write_conf(store.path, VALID_VALUES)
        secret = write_conf(store.path, OTHER_VALUES)
        secret.chmod(0o000)
        try:
            assert [c.name for c in store.read()] == ["home"]
            [error] = store.read_errors
            assert str(secret) in error
        finally:
            secret.chmod(0o644)
        store.read()
        assert store.read_errors == []

    def test_undecodable_bytes_do_not_crash(self, store):
        (store.path / "home.conf").write_bytes(
            conf_text(VALID_VALUES).encode() + b"# \xff\xfe\n"
        )
        assert store.read() == [Connection(VALID_VALUES)]

    def test_crlf_and_bom(self, store):
        text = "\ufeff" + conf_text(VALID_VALUES).replace("\n", "\r\n")
        (store.path / "home.conf").write_text(text, newline="")
        assert store.read() == [Connection(VALID_VALUES)]


class TestParseLikeSystemd:
    """EnvironmentFile= semantics: what the daemon will get."""

    @pytest.mark.parametrize("text, expected", [
        ("A=1\n", {"A": "1"}),
        ("# comment\nA=1\n", {"A": "1"}),
        ("; comment\nA=1\n", {"A": "1"}),
        ("   # indented comment\nA=1", {"A": "1"}),
        ("#A=1\n", {}),
        ("A=1\nA=2\n", {"A": "2"}),  # last one wins
        ("  A = 1  \n", {"A": "1"}),
        ("A=\n", {"A": ""}),
        ("no equals sign\n", {}),
        ("=value\n", {}),
        ("\n\n", {}),
        ("A=a=b\n", {"A": "a=b"}),
        ("A=1\t\r\n", {"A": "1"}),
    ])
    def test_parse(self, text, expected):
        assert parse(text) == expected

    def test_inline_hash_is_part_of_the_value(self):
        # systemd keeps it: the daemon would get "22 # ssh"
        assert parse("LOCAL_PORT=22 # ssh\n") == {"LOCAL_PORT": "22 # ssh"}

    def test_inline_comment_is_flagged(self, store):
        (store.path / "home.conf").write_text(
            conf_text(VALID_VALUES).replace("LOCAL_PORT=22",
                                            "LOCAL_PORT=22  # ssh")
        )
        [connection] = store.read()
        assert connection["LOCAL_PORT"] == "22  # ssh"
        assert store.validate(connection, "home")[0].startswith("LOCAL_PORT:")

    @pytest.mark.parametrize("line, key", [
        ('REMOTE_USER="vasya"', "REMOTE_USER"),  # systemd strips quotes
        ("REMOTE_USER='vasya'", "REMOTE_USER"),
        ("REMOTE_USER=va\\sya", "REMOTE_USER"),  # ... reads escapes
        ("REMOTE_USER=vasya\\", "REMOTE_USER"),  # ... continues the line
    ])
    def test_quotes_and_backslashes_are_kept_and_flagged(
        self, store, line, key
    ):
        values = dict(VALID_VALUES)
        del values[key]
        (store.path / "home.conf").write_text(conf_text(values) + line + "\n")
        [connection] = store.read()
        assert connection[key] == line.split("=", 1)[1]
        assert [e.split(":")[0] for e in store.validate(connection, "home")] \
            == [key]


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


class TestWriteNew:
    def test_new_file(self, store):
        store.write(Connection(VALID_VALUES))
        path = store.path / "home.conf"
        assert path.read_text() == HOME_CONF
        assert stat.S_IMODE(path.stat().st_mode) == NEW_FILE_MODE
        assert temp_leftovers(store.path) == []

    def test_round_trip(self, store):
        store.write(Connection(VALID_VALUES))
        store.write(Connection(OTHER_VALUES))
        assert store.read() == [
            Connection(VALID_VALUES), Connection(OTHER_VALUES)
        ]

    def test_header_has_no_name(self):
        # a rename keeps the file's text: nothing in it may go stale
        assert "home" not in NEW_FILE_HEADER

    def test_name_taken(self, store):
        write_conf(store.path, VALID_VALUES)
        error = assert_write_rejected(store, changed(REMOTE_USER="petya"))
        assert error.errors[0].startswith("NAME:")
        assert "already exists" in error.errors[0]

    def test_into_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ConnectionsDir(tmp_path / "missing").write(
                Connection(VALID_VALUES)
            )

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_without_permission_raises(self, store):
        store.path.chmod(0o555)
        try:
            with pytest.raises(PermissionError):
                store.write(Connection(VALID_VALUES))
            assert list(store.path.iterdir()) == []
        finally:
            store.path.chmod(0o755)


class TestWriteExisting:
    def test_values_replaced_in_place(self, store):
        path = store.path / "home.conf"
        path.write_text(
            "# my tunnel to the NAS\n"
            "REMOTE_USER=vasya\n"
            "\n"
            "; ports\n"
            "LOCAL_PORT=22\n"
            "REMOTE_PORT=5001\n"
            "EXTRA_OPTION=keep me\n"
        )
        store.write(changed(REMOTE_USER="petya", LOCAL_PORT="2222"), "home")
        assert path.read_text() == (
            "# my tunnel to the NAS\n"
            "REMOTE_USER=petya\n"
            "\n"
            "; ports\n"
            "LOCAL_PORT=2222\n"
            "REMOTE_PORT=5001\n"
            "EXTRA_OPTION=keep me\n"
            # missing keys: appended, in schema order
            "ENABLED=false\n"
            "RUN_DAEMON_USER=username\n"
            "REMOTE_SERVER=vasya.com\n"
            "REMOTE_SERVER_SSH_PORT=22\n"
        )

    def test_rewrite_is_idempotent(self, store):
        store.write(Connection(VALID_VALUES))
        first = (store.path / "home.conf").read_text()
        store.write(Connection(VALID_VALUES), "home")
        assert (store.path / "home.conf").read_text() == first

    def test_duplicates_collapse_to_the_last_place(self, store):
        path = store.path / "home.conf"
        path.write_text(
            conf_text(VALID_VALUES)
            + "# later override\nREMOTE_USER=other\n"
        )
        store.write(changed(REMOTE_USER="petya"), "home")
        text = path.read_text()
        assert text.count("REMOTE_USER=") == 1
        assert text.endswith("# later override\nREMOTE_USER=petya\n")

    def test_inline_comment_line_is_replaced(self, store):
        path = store.path / "home.conf"
        path.write_text(conf_text(VALID_VALUES).replace(
            "LOCAL_PORT=22", "LOCAL_PORT=22 # ssh"
        ))
        store.write(Connection(VALID_VALUES), "home")
        # "# ssh" was part of the value for systemd: it must not survive
        assert "LOCAL_PORT=22\n" in path.read_text()
        assert "# ssh" not in path.read_text()

    def test_keeps_its_mode(self, store):
        path = write_conf(store.path, VALID_VALUES)
        path.chmod(0o600)
        store.write(changed(REMOTE_USER="petya"), "home")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_through_symlink_updates_target(self, store, tmp_path):
        real = tmp_path / "real.conf"
        real.write_text(conf_text(VALID_VALUES))
        link = store.path / "home.conf"
        link.symlink_to(real)
        store.write(changed(REMOTE_USER="petya"), "home")
        assert link.is_symlink()
        assert "REMOTE_USER=petya\n" in real.read_text()

    def test_undecodable_bytes_in_other_lines_survive(self, store):
        path = store.path / "home.conf"
        path.write_bytes(b"# caf\xe9\n" + conf_text(VALID_VALUES).encode())
        store.write(changed(REMOTE_USER="petya"), "home")
        assert path.read_bytes().startswith(b"# caf\xe9\n")

    def test_crlf_file_is_rewritten_with_lf(self, store):
        path = store.path / "home.conf"
        path.write_bytes(conf_text(VALID_VALUES).replace("\n", "\r\n")
                         .encode())
        store.write(Connection(VALID_VALUES), "home")
        assert b"\r" not in path.read_bytes()

    def test_bom_is_not_duplicated(self, store):
        path = store.path / "home.conf"
        path.write_text("\ufeff" + conf_text(VALID_VALUES))
        store.write(Connection(VALID_VALUES), "home")
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert store.read() == [Connection(VALID_VALUES)]

    def test_failed_write_keeps_file_and_removes_temp_file(
        self, store, monkeypatch
    ):
        path = write_conf(store.path, VALID_VALUES)
        original = path.read_text()

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError, match="No space left"):
            store.write(changed(REMOTE_USER="petya"), "home")
        assert path.read_text() == original
        assert temp_leftovers(store.path) == []

    def test_saved_file_deleted_meanwhile_is_recreated(self, store):
        store.write(Connection(VALID_VALUES), "home")  # no file: new one
        assert store.read() == [Connection(VALID_VALUES)]


class TestRename:
    def test_moves_the_file(self, store):
        write_conf(store.path, VALID_VALUES)
        store.write(changed(NAME="nas"), "home")
        assert sorted(p.name for p in store.path.iterdir()) == ["nas.conf"]
        assert store.read() == [changed(NAME="nas")]

    def test_keeps_comments_and_other_keys(self, store):
        (store.path / "home.conf").write_text(
            "# my NAS\nEXTRA=1\n" + conf_text(VALID_VALUES)
        )
        store.write(changed(NAME="nas"), "home")
        text = (store.path / "nas.conf").read_text()
        assert text.startswith("# my NAS\nEXTRA=1\n")

    def test_keeps_the_mode(self, store):
        write_conf(store.path, VALID_VALUES).chmod(0o600)
        store.write(changed(NAME="nas"), "home")
        assert stat.S_IMODE((store.path / "nas.conf").stat().st_mode) == 0o600

    def test_to_a_taken_name_is_rejected(self, store):
        write_conf(store.path, VALID_VALUES)
        write_conf(store.path, OTHER_VALUES)
        error = assert_write_rejected(store, changed(NAME="office"), "home")
        assert "already exists" in error.errors[0]

    def test_old_file_gone_meanwhile(self, store):
        store.write(changed(NAME="nas"), "home")
        assert [c.name for c in store.read()] == ["nas"]

    def test_failed_write_keeps_the_old_file(self, store, monkeypatch):
        write_conf(store.path, VALID_VALUES)

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError):
            store.write(changed(NAME="nas"), "home")
        assert sorted(p.name for p in store.path.iterdir()) == ["home.conf"]


class TestDelete:
    def test_delete(self, store):
        write_conf(store.path, VALID_VALUES)
        write_conf(store.path, OTHER_VALUES)
        store.delete("home")
        assert [c.name for c in store.read()] == ["office"]

    def test_already_gone(self, store):
        store.delete("home")

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_without_permission_raises(self, store):
        write_conf(store.path, VALID_VALUES)
        store.path.chmod(0o555)
        try:
            with pytest.raises(PermissionError):
                store.delete("home")
        finally:
            store.path.chmod(0o755)


# --------------------------------------------------------------------------
# Validation through the files
# --------------------------------------------------------------------------


class TestValidate:
    def test_valid(self, store):
        assert store.validate(Connection(VALID_VALUES)) == []

    def test_saving_under_its_own_name(self, store):
        write_conf(store.path, VALID_VALUES)
        assert store.validate(Connection(VALID_VALUES), "home") == []

    def test_new_with_taken_name(self, store):
        write_conf(store.path, VALID_VALUES)
        [error] = store.validate(Connection(VALID_VALUES))
        assert error.startswith("NAME:")

    def test_invalid_name_is_not_checked_against_files(self, store):
        [error] = store.validate(changed(NAME="../evil"))
        assert "already exists" not in error

    @pytest.mark.parametrize("name", ["../evil", "a/b", ".hidden", ""])
    def test_path_like_names_are_not_written(self, store, tmp_path, name):
        def tree():
            return sorted(str(p) for p in tmp_path.rglob("*"))

        before = tree()
        with pytest.raises(ValidationError):
            store.write(changed(NAME=name))
        assert tree() == before  # nothing written anywhere

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize(
        "value", DANGEROUS_IDENTIFIERS + LEADING_DASH_IDENTIFIERS
    )
    def test_dangerous_identifier_is_not_written(self, store, key, value):
        write_conf(store.path, VALID_VALUES)
        assert_write_rejected(store, changed(**{key: value}), "home")

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_PORTS)
    def test_dangerous_port_is_not_written(self, store, key, value):
        write_conf(store.path, VALID_VALUES)
        assert_write_rejected(store, changed(**{key: value}), "home")

    @pytest.mark.parametrize("line, key", [
        ("REMOTE_USER=$(reboot)", "REMOTE_USER"),
        ("REMOTE_SERVER=vasya.com;reboot", "REMOTE_SERVER"),
        ("RUN_DAEMON_USER=root' -c 'reboot", "RUN_DAEMON_USER"),
        ("REMOTE_PORT=22 -oProxyCommand=reboot", "REMOTE_PORT"),
        ("LOCAL_PORT=`reboot`", "LOCAL_PORT"),
        ("REMOTE_USER=-F.evil", "REMOTE_USER"),
    ])
    def test_hand_edited_injection_is_read_verbatim_and_flagged(
        self, store, line, key
    ):
        values = dict(VALID_VALUES)
        del values[key]
        (store.path / "home.conf").write_text(conf_text(values) + line + "\n")
        [connection] = store.read()
        assert connection[key] == line.split("=", 1)[1]
        [error] = store.validate(connection, "home")
        assert error.startswith(f"{key}:")

    def test_rejected_newline_cannot_add_a_line(self, store):
        write_conf(store.path, VALID_VALUES)
        assert_write_rejected(
            store, changed(REMOTE_USER="x\nREMOTE_PORT=1"), "home"
        )


class TestDoc:
    DOC = Path(__file__).parent.parent / "doc" / "config.md"

    def doc_example(self) -> str:
        """The indented example after "as written by the GUI:"."""
        text = self.DOC.read_text()
        after = text.split("as written by the GUI:\n\n", 1)[1]
        lines = []
        for line in after.splitlines():
            if not line.startswith("    "):
                break
            lines.append(line[4:])
        return "\n".join(lines) + "\n"

    def test_writer_output_is_the_doc_example(self, store):
        store.write(Connection(VALID_VALUES))
        assert (store.path / "home.conf").read_text() == self.doc_example()

    def test_doc_example_reads_back(self, store):
        (store.path / "home.conf").write_text(self.doc_example())
        assert store.read() == [Connection(VALID_VALUES)]
