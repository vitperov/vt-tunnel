"""Tests of TunnelConfig: reading, validating and writing vt-tunnel.cfg.

The file holds a list of connections with numbered keys (NAME1, NAME2,
...). File format and validation rules: doc/config.md, config_schema.py.
Per-field rules are tested in detail in test_connection.py; here they are
checked through the file (read, validate, write).
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
    OUT_OF_RANGE_PORTS,
    PORT_KEYS,
    VALID_VALUES,
    cfg_text,
)
from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.tunnel_config import (
    NEW_FILE_MODE,
    TunnelConfig,
    ValidationError,
)


def assert_write_rejected(
    config: TunnelConfig, connections: list[Connection]
) -> None:
    """Writing raises ValidationError and leaves the directory unchanged."""
    directory = config.path.parent
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ValidationError):
        config.write(connections)
    after = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert after == before  # file untouched, no temp files left behind


def temp_leftovers(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


def block(number: int, values: dict[str, str]) -> str:
    """The text the writer produces for one connection."""
    return (
        f"# ===== Connection {number}: {values['NAME']} =====\n"
        + cfg_text(values, start=number)
    )


# --------------------------------------------------------------------------
# Existing and missing file
# --------------------------------------------------------------------------


class TestExistingAndMissingFile:
    def test_path_is_kept_as_given(self):
        assert TunnelConfig(Path("rel/x.cfg")).path == Path("rel/x.cfg")

    def test_exists(self, make_config):
        assert make_config("").exists()

    def test_missing_file_does_not_exist(self, cfg_path):
        assert not TunnelConfig(cfg_path).exists()

    def test_read_missing_file_raises_file_not_found(self, cfg_path):
        with pytest.raises(FileNotFoundError):
            TunnelConfig(cfg_path).read()

    def test_read_directory_raises_oserror(self, tmp_path):
        with pytest.raises(IsADirectoryError):
            TunnelConfig(tmp_path).read()

    def test_write_creates_missing_file(self, cfg_path, valid, other):
        TunnelConfig(cfg_path).write([valid, other])

        assert cfg_path.read_text() == (
            block(1, VALID_VALUES) + "\n" + block(2, OTHER_VALUES)
        )
        assert stat.S_IMODE(cfg_path.stat().st_mode) == NEW_FILE_MODE
        assert temp_leftovers(cfg_path.parent) == []

    def test_write_empty_list_to_missing_file(self, cfg_path):
        TunnelConfig(cfg_path).write([])
        assert cfg_path.read_text() == ""
        assert TunnelConfig(cfg_path).read() == []

    def test_write_then_read_round_trip(self, cfg_path, valid, other):
        config = TunnelConfig(cfg_path)
        config.write([valid, other])
        assert config.read() == [valid, other]

    def test_write_existing_file_keeps_its_mode(self, make_config, valid):
        config = make_config(cfg_text(VALID_VALUES))
        os.chmod(config.path, 0o600)

        changed = Connection(VALID_VALUES | {"REMOTE_USER": "petya"})
        config.write([changed])

        assert stat.S_IMODE(config.path.stat().st_mode) == 0o600
        assert config.read() == [changed]

    def test_write_through_symlink_updates_target(self, tmp_path, valid):
        target = tmp_path / "real.cfg"
        target.write_text(cfg_text(VALID_VALUES))
        link = tmp_path / "link.cfg"
        link.symlink_to(target)

        changed = Connection(VALID_VALUES | {"REMOTE_USER": "petya"})
        TunnelConfig(link).write([changed])

        assert link.is_symlink()
        assert TunnelConfig(target).read() == [changed]

    def test_failed_write_keeps_file_and_removes_temp_file(
        self, make_config, valid, monkeypatch
    ):
        # Fail after the temp file was written (e.g. disk full, I/O error).
        original = cfg_text(VALID_VALUES)
        config = make_config(original)

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError, match="No space left"):
            config.write([valid])

        assert config.path.read_text() == original
        assert temp_leftovers(config.path.parent) == []

    def test_write_into_missing_directory_raises(self, tmp_path, valid):
        config = TunnelConfig(tmp_path / "no" / "such" / "dir.cfg")
        with pytest.raises(FileNotFoundError):
            config.write([valid])

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_write_without_permission_raises_and_keeps_file(
        self, tmp_path, valid
    ):
        directory = tmp_path / "ro"
        directory.mkdir()
        path = directory / "vt-tunnel.cfg"
        path.write_text("OTHER=1\n")
        directory.chmod(0o555)
        try:
            with pytest.raises(PermissionError):
                TunnelConfig(path).write([valid])
            assert path.read_text() == "OTHER=1\n"
            assert temp_leftovers(directory) == []
        finally:
            directory.chmod(0o755)


# --------------------------------------------------------------------------
# Config file with expected values
# --------------------------------------------------------------------------


DOC_EXAMPLE = """\
# ===== Connection 1: home =====
NAME1=home
ENABLED1=false
RUN_DAEMON_USER1=username
REMOTE_USER1=vasya
REMOTE_SERVER1=vasya.com
LOCAL_PORT1=22
REMOTE_PORT1=5001

# ===== Connection 2: office =====
NAME2=office
ENABLED2=true
RUN_DAEMON_USER2=username
REMOTE_USER2=vasya
REMOTE_SERVER2=office.example.com
LOCAL_PORT2=8080
REMOTE_PORT2=5002
"""


class TestExpectedValues:
    def test_read_doc_example(self, make_config, valid, other):
        assert make_config(DOC_EXAMPLE).read() == [valid, other]

    def test_doc_example_is_valid(self, make_config):
        assert TunnelConfig.validate(make_config(DOC_EXAMPLE).read()) == []

    def test_writer_output_is_the_doc_example(self, cfg_path, valid, other):
        TunnelConfig(cfg_path).write([valid, other])
        assert cfg_path.read_text() == DOC_EXAMPLE

    def test_empty_file_has_no_connections(self, make_config):
        assert make_config("").read() == []

    def test_empty_list_is_valid(self):
        assert TunnelConfig.validate([]) == []

    def test_whitespace_and_comments_are_not_part_of_values(
        self, make_config, valid
    ):
        config = make_config(
            "  # indented comment\n"
            "\n"
            "NAME1=home\n"
            "ENABLED1 = false\n"
            "RUN_DAEMON_USER1=username   # trailing comment\n"
            "\tREMOTE_USER1=vasya\t\n"
            "REMOTE_SERVER1=vasya.com\n"
            "LOCAL_PORT1=22#no space before comment\n"
            "REMOTE_PORT1=5001\n"
        )
        assert config.read() == [valid]

    def test_crlf_line_endings(self, cfg_path, valid, other):
        cfg_path.write_bytes(DOC_EXAMPLE.replace("\n", "\r\n").encode())
        assert TunnelConfig(cfg_path).read() == [valid, other]

    def test_utf8_bom_is_ignored(self, cfg_path, valid):
        # BOM right before the first key, as written by some editors.
        cfg_path.write_bytes(b"\xef\xbb\xbf" + cfg_text(VALID_VALUES).encode())
        assert TunnelConfig(cfg_path).read() == [valid]

    def test_other_keys_are_not_connections(self, make_config, valid):
        config = make_config(
            "OTHER_KEY=something\n"
            "NAME=unnumbered\n"  # schema key without number
            + cfg_text(VALID_VALUES)
        )
        assert config.read() == [valid]


# --------------------------------------------------------------------------
# Connection numbering
# --------------------------------------------------------------------------


class TestNumbering:
    def test_connections_are_ordered_by_number(self, make_config, valid, other):
        # Connection 2 written first in the file.
        config = make_config(cfg_text(OTHER_VALUES, start=2) + cfg_text(VALID_VALUES))
        assert config.read() == [valid, other]

    def test_numbers_sort_numerically_not_alphabetically(self, make_config):
        config = make_config("NAME10=ten\nNAME9=nine\nNAME2=two\n")
        assert [c.name for c in config.read()] == ["two", "nine", "ten"]

    def test_gaps_are_allowed(self, make_config, valid, other):
        config = make_config(
            cfg_text(VALID_VALUES, start=3) + cfg_text(OTHER_VALUES, start=7)
        )
        assert config.read() == [valid, other]

    def test_interleaved_keys_are_grouped(self, make_config):
        config = make_config(
            "NAME1=a\nNAME2=b\nLOCAL_PORT2=2\nLOCAL_PORT1=1\n"
        )
        assert [(c.name, c["LOCAL_PORT"]) for c in config.read()] == [
            ("a", "1"), ("b", "2"),
        ]

    def test_partial_connection_has_empty_fields(self, make_config):
        [connection] = make_config("LOCAL_PORT4=22\n").read()
        assert connection == Connection({"LOCAL_PORT": "22"})

    def test_large_number(self, make_config):
        [connection] = make_config("NAME123456789012345678901=x\n").read()
        assert connection.name == "x"

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("NAME0=x", id="zero"),
            pytest.param("NAME01=x", id="leading-zero"),
            pytest.param("NAME=x", id="no-number"),
            pytest.param("NAME-1=x", id="negative"),
            pytest.param("NAME1a=x", id="suffix-after-number"),
            pytest.param("NAME_1=x", id="underscore-before-number"),
            pytest.param("name1=x", id="lowercase"),
            pytest.param("NAMES1=x", id="unknown-field"),
            pytest.param("NAME\u0661=x", id="non-ascii-digit"),
            # int() would read this as 11
            pytest.param("NAME1\u0661=x", id="non-ascii-digit-after-ascii"),
        ],
    )
    def test_not_a_connection_key(self, make_config, line):
        assert make_config(line + "\n").read() == []

    def test_duplicate_key_last_wins(self, make_config):
        [connection] = make_config("NAME1=first\nNAME1=second\n").read()
        assert connection.name == "second"


# --------------------------------------------------------------------------
# Validation of the list
# --------------------------------------------------------------------------


class TestValidateList:
    def test_errors_name_the_connection(self, valid):
        bad = Connection(OTHER_VALUES | {"LOCAL_PORT": "0"})
        [error] = TunnelConfig.validate([valid, bad])
        assert error.startswith('Connection "office": LOCAL_PORT:')

    def test_without_valid_name_the_number_is_shown(self, valid):
        bad = Connection(VALID_VALUES | {"NAME": "x;reboot"})
        [error] = TunnelConfig.validate([valid, bad])
        assert error.startswith("Connection 2: NAME:")

    def test_errors_of_all_connections_are_reported(self):
        first = Connection(VALID_VALUES | {"REMOTE_PORT": ""})
        second = Connection(OTHER_VALUES | {"REMOTE_USER": "$x"})
        errors = TunnelConfig.validate([first, second])
        assert [e.split(": ")[:2] for e in errors] == [
            ['Connection "home"', "REMOTE_PORT"],
            ['Connection "office"', "REMOTE_USER"],
        ]

    def test_names_must_be_unique(self, valid):
        duplicate = Connection(OTHER_VALUES | {"NAME": "home"})
        [error] = TunnelConfig.validate([valid, duplicate])
        assert error.startswith('Connection "home": NAME: must be unique')

    def test_duplicate_name_is_not_written(self, make_config, valid):
        config = make_config(cfg_text(VALID_VALUES))
        assert_write_rejected(config, [valid, valid])

    def test_invalid_connection_blocks_writing_the_others(
        self, make_config, valid
    ):
        config = make_config(cfg_text(VALID_VALUES))
        bad = Connection(OTHER_VALUES | {"REMOTE_PORT": "0"})
        assert_write_rejected(config, [valid, bad])


# --------------------------------------------------------------------------
# Out-of-range values
# --------------------------------------------------------------------------


class TestOutOfRangeValues:
    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("port", OUT_OF_RANGE_PORTS)
    def test_out_of_range_port_in_file_is_read_verbatim_and_flagged(
        self, make_config, key, port
    ):
        # Reading never fails on bad values, so the user can see and fix
        # them; validation reports them.
        config = make_config(
            cfg_text(VALID_VALUES, OTHER_VALUES | {key: port})
        )
        connections = config.read()
        assert connections[1][key] == port
        [error] = TunnelConfig.validate(connections)
        assert error.startswith(f'Connection "office": {key}:')

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("port", OUT_OF_RANGE_PORTS)
    def test_out_of_range_port_is_not_written(
        self, make_config, valid, key, port
    ):
        config = make_config(cfg_text(VALID_VALUES))
        bad = Connection(OTHER_VALUES | {key: port})
        assert_write_rejected(config, [valid, bad])


# --------------------------------------------------------------------------
# Malformed syntax, missing keys, missing values
# --------------------------------------------------------------------------


class TestMalformedSyntax:
    @pytest.mark.parametrize(
        "text, expected",
        [
            pytest.param("", {}, id="empty-file"),
            pytest.param("# only\n# comments\n", {}, id="only-comments"),
            pytest.param("\n\n   \n\t\n", {}, id="only-blank-lines"),
            pytest.param("NAME1 home\n", {}, id="no-equals-sign"),
            pytest.param("NAME1\n", {}, id="key-only"),
            pytest.param("=home\n", {}, id="empty-key"),
            pytest.param("  =home\n", {}, id="blank-key"),
            pytest.param("# NAME1=home\n", {}, id="commented-out"),
            pytest.param("garbage\nA=1\n", {"A": "1"}, id="garbage-skipped"),
            pytest.param("A=1\nA=2\n", {"A": "2"}, id="duplicate-last-wins"),
            pytest.param("A=b=c\n", {"A": "b=c"}, id="equals-in-value"),
            pytest.param('A="x"\n', {"A": '"x"'}, id="quotes-kept"),
            pytest.param("A='x'\n", {"A": "'x'"}, id="single-quotes-kept"),
            pytest.param("A=$HOME\n", {"A": "$HOME"}, id="no-expansion"),
            pytest.param("A=x\\\nB=y\n", {"A": "x\\", "B": "y"},
                         id="no-line-continuation"),
            pytest.param("A=1", {"A": "1"}, id="no-final-newline"),
        ],
    )
    def test_parse(self, text, expected):
        assert TunnelConfig.parse(text) == expected

    def test_quoted_value_is_kept_and_flagged(self, make_config):
        [connection] = make_config('REMOTE_USER1="vasya"\n').read()
        assert connection["REMOTE_USER"] == '"vasya"'
        assert "REMOTE_USER: " in "\n".join(connection.validate())

    def test_undecodable_bytes_do_not_crash_read(self, cfg_path):
        cfg_path.write_bytes(b"REMOTE_USER1=caf\xe9\n")
        [connection] = TunnelConfig(cfg_path).read()
        assert connection["REMOTE_USER"].startswith("caf")
        assert any(e.startswith("REMOTE_USER:") for e in connection.validate())

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("remote_user1=vasya", id="lowercase-key"),
            pytest.param("export REMOTE_USER1=vasya", id="shell-export"),
            pytest.param("REMOTE USER1=vasya", id="space-in-key"),
            pytest.param("REMOTE_USER01=vasya", id="leading-zero"),
        ],
    )
    def test_misspelled_key_leaves_field_empty(self, make_config, line):
        values = dict(VALID_VALUES)
        del values["REMOTE_USER"]
        [connection] = make_config(cfg_text(values) + line + "\n").read()
        assert connection["REMOTE_USER"] == ""
        [error] = TunnelConfig.validate([connection])
        assert error.startswith('Connection "home": REMOTE_USER:')


class TestMissingKeysAndValues:
    @pytest.mark.parametrize("key", PORT_KEYS + IDENTIFIER_KEYS)
    def test_missing_key_is_empty_and_flagged(self, make_config, key):
        values = dict(VALID_VALUES)
        del values[key]
        [connection] = make_config(cfg_text(values)).read()
        assert connection[key] == ""
        assert [e.split(":")[0] for e in connection.validate()] == [key]

    def test_missing_enabled_is_empty_and_allowed(self, make_config):
        values = dict(VALID_VALUES)
        del values["ENABLED"]
        [connection] = make_config(cfg_text(values)).read()
        assert connection["ENABLED"] == ""
        assert TunnelConfig.validate([connection]) == []

    @pytest.mark.parametrize("key", PORT_KEYS + IDENTIFIER_KEYS)
    @pytest.mark.parametrize(
        "line_value",
        [
            pytest.param("", id="empty"),
            pytest.param("   ", id="blank"),
            pytest.param(" # comment", id="comment-only"),
        ],
    )
    def test_empty_value_is_read_as_empty_and_flagged(
        self, make_config, key, line_value
    ):
        [connection] = make_config(
            cfg_text(VALID_VALUES | {key: line_value})
        ).read()
        assert connection[key] == ""
        assert [e.split(":")[0] for e in connection.validate()] == [key]

    @pytest.mark.parametrize("key", PORT_KEYS + IDENTIFIER_KEYS)
    def test_empty_value_is_not_written(self, make_config, valid, key):
        config = make_config(cfg_text(VALID_VALUES))
        assert_write_rejected(
            config, [valid, Connection(OTHER_VALUES | {key: ""})]
        )


# --------------------------------------------------------------------------
# Values that could break or inject into the ssh command line
# (see the ExecStart line in conftest.py)
# --------------------------------------------------------------------------


class TestShellBreakingValues:
    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize(
        "value", DANGEROUS_IDENTIFIERS + LEADING_DASH_IDENTIFIERS
    )
    def test_dangerous_identifier_is_not_written(
        self, make_config, valid, key, value
    ):
        config = make_config(cfg_text(VALID_VALUES))
        bad = Connection(OTHER_VALUES | {key: value})
        assert_write_rejected(config, [valid, bad])

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_PORTS)
    def test_dangerous_port_is_not_written(
        self, make_config, valid, key, value
    ):
        config = make_config(cfg_text(VALID_VALUES))
        bad = Connection(OTHER_VALUES | {key: value})
        assert_write_rejected(config, [valid, bad])

    @pytest.mark.parametrize(
        "line, key",
        [
            ("REMOTE_USER2=$(reboot)", "REMOTE_USER"),
            ("REMOTE_SERVER2=vasya.com;reboot", "REMOTE_SERVER"),
            ("RUN_DAEMON_USER2=root' -c 'reboot", "RUN_DAEMON_USER"),
            ("REMOTE_PORT2=22 -oProxyCommand=reboot", "REMOTE_PORT"),
            ("LOCAL_PORT2=`reboot`", "LOCAL_PORT"),
            ("REMOTE_USER2=-F.evil", "REMOTE_USER"),
            ("NAME2=home;reboot", "NAME"),
        ],
    )
    def test_hand_edited_injection_is_read_verbatim_and_flagged(
        self, make_config, line, key
    ):
        # A hand-edited file is shown as is (no expansion, nothing run) and
        # flagged, so it can't be saved back until fixed.
        values = dict(OTHER_VALUES)
        del values[key]
        config = make_config(
            cfg_text(VALID_VALUES) + cfg_text(values, start=2) + line + "\n"
        )
        connections = config.read()
        assert connections[1][key] == line.split("=", 1)[1]
        [error] = TunnelConfig.validate(connections)
        assert f": {key}:" in error

    def test_rejected_newline_cannot_add_a_line(self, make_config, valid):
        config = make_config(cfg_text(VALID_VALUES))
        bad = Connection(VALID_VALUES | {"REMOTE_USER": "x\nREMOTE_PORT1=1"})
        with pytest.raises(ValidationError):
            config.write([bad])
        assert config.read() == [valid]


# --------------------------------------------------------------------------
# Rewriting an existing file
# --------------------------------------------------------------------------


class TestRewrite:
    def test_other_lines_kept_at_the_top(self, make_config, valid, other):
        config = make_config(
            "# header comment\n"
            "OTHER_KEY=keep  me   # as is\n"
            "\n"
            "NAME1=old   # inline comment on a connection key\n"
            "  # indented comment\n"
            "junk line without equals\n"
            "LOCAL_PORT1=1\n"
        )
        config.write([valid, other])

        assert config.path.read_text() == (
            "# header comment\n"
            "OTHER_KEY=keep  me   # as is\n"
            "\n"
            "  # indented comment\n"
            "junk line without equals\n"
            "\n"
            + block(1, VALID_VALUES) + "\n" + block(2, OTHER_VALUES)
        )

    def test_rewrite_is_idempotent(self, make_config, valid, other):
        config = make_config("# header\nOTHER=1\n")
        config.write([valid, other])
        first = config.path.read_text()
        config.write([valid, other])
        config.write([valid, other])
        assert config.path.read_text() == first  # no blank-line pile-up

    def test_deleting_a_connection_renumbers_the_rest(self, make_config):
        third = Connection(VALID_VALUES | {"NAME": "lab", "REMOTE_PORT": "5003"})
        config = make_config("")
        first, second = Connection(VALID_VALUES), Connection(OTHER_VALUES)
        config.write([first, second, third])

        connections = config.read()
        del connections[1]
        config.write(connections)

        text = config.path.read_text()
        assert text == (
            block(1, VALID_VALUES) + "\n"
            + block(2, VALID_VALUES | {"NAME": "lab", "REMOTE_PORT": "5003"})
        )
        assert "3=" not in text
        assert config.read() == [first, third]

    def test_deleting_all_connections_keeps_other_lines(
        self, make_config, valid
    ):
        config = make_config("# header\nOTHER=1\n\n" + block(1, VALID_VALUES))
        config.write([])
        assert config.path.read_text() == "# header\nOTHER=1\n"
        assert config.read() == []

    def test_gaps_close_up_on_write(self, make_config, valid, other):
        config = make_config(
            cfg_text(VALID_VALUES, start=3) + cfg_text(OTHER_VALUES, start=9)
        )
        config.write(config.read())
        assert config.path.read_text() == (
            block(1, VALID_VALUES) + "\n" + block(2, OTHER_VALUES)
        )

    def test_delimiter_follows_renamed_connection(self, make_config, valid):
        config = make_config("")
        config.write([valid])
        config.write([Connection(VALID_VALUES | {"NAME": "renamed"})])
        text = config.path.read_text()
        assert "# ===== Connection 1: renamed =====\n" in text
        assert "home" not in text

    def test_old_delimiters_are_not_duplicated(self, make_config, valid):
        config = make_config(
            "# ===== Connection 1: old name =====\n"
            "#=== Connection 7 whatever ===\n"
        )
        config.write([valid])
        assert config.path.read_text() == block(1, VALID_VALUES)

    def test_undecodable_bytes_in_other_lines_survive(self, cfg_path, valid):
        cfg_path.write_bytes(b"OTHER=caf\xe9\xff\n" + cfg_text(VALID_VALUES).encode())
        TunnelConfig(cfg_path).write([valid])
        assert cfg_path.read_bytes().startswith(b"OTHER=caf\xe9\xff\n")

    def test_crlf_file_is_rewritten_with_lf(self, cfg_path, valid):
        cfg_path.write_bytes(cfg_text(VALID_VALUES).replace("\n", "\r\n").encode())
        TunnelConfig(cfg_path).write([valid])
        assert b"\r" not in cfg_path.read_bytes()
        assert TunnelConfig(cfg_path).read() == [valid]

    def test_utf8_bom_file_is_rewritten_without_duplicates(
        self, cfg_path, valid
    ):
        cfg_path.write_bytes(b"\xef\xbb\xbf" + cfg_text(VALID_VALUES).encode())
        TunnelConfig(cfg_path).write([valid])
        assert cfg_path.read_text() == block(1, VALID_VALUES)

    def test_single_connection_format_keys_are_kept_as_other_keys(
        self, make_config, valid
    ):
        # Un-numbered keys of the previous one-connection format are not
        # connections; they stay in the file verbatim.
        legacy = "NAME=home\nENABLED=false\nREMOTE_USER=vasya\n"
        config = make_config(legacy)
        assert config.read() == []
        config.write([valid])
        assert config.path.read_text() == legacy + "\n" + block(1, VALID_VALUES)

    def test_original_daemon_format_ports_become_connection_1(
        self, make_config
    ):
        # The original daemon config used LOCAL_PORT1 / REMOTE_PORT1, which
        # now read as fields of connection 1; the rest is un-numbered.
        config = make_config(
            "ENABLED=false\n"
            "RUN_DAEMON_USER=username\n"
            "REMOTE_USER=vasya\n"
            "REMOTE_SERVER=vasya.com\n"
            "REMOTE_SSH_PORT=22\n"
            "LOCAL_PORT1=22\n"
            "REMOTE_PORT1=5001\n"
        )
        assert config.read() == [
            Connection({"LOCAL_PORT": "22", "REMOTE_PORT": "5001"})
        ]
