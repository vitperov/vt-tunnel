"""Tests of TunnelConfig: reading, validating and writing vt-tunnel.cfg.

File format and validation rules: doc/config.md and config_schema.py.
"""

import os
import stat
from pathlib import Path

import pytest

from conftest import IDENTIFIER_KEYS, PORT_KEYS, VALID_VALUES, cfg_text
from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.tunnel_config import (
    NEW_FILE_MODE,
    TunnelConfig,
    ValidationError,
)


def errors_for(values: dict[str, str]) -> dict[str, str]:
    """``{key: message}`` of the validation errors of ``values``."""
    return {
        error.split(":", 1)[0]: error for error in TunnelConfig.validate(values)
    }


def assert_only_invalid(values: dict[str, str], key: str) -> None:
    """``values`` is rejected, and ``key`` is the only offending key."""
    assert list(errors_for(values)) == [key]


def assert_write_rejected(
    config: TunnelConfig, values: dict[str, str]
) -> None:
    """Writing ``values`` raises and leaves the directory byte-identical."""
    directory = config.path.parent
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ValidationError):
        config.write(values)
    after = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert after == before  # file untouched, no temp files left behind


def schema_subset(values: dict[str, str]) -> dict[str, str]:
    """The schema keys of ``values`` (what the GUI would show and write)."""
    return {k: v for k, v in values.items() if k in config_schema.FIELD_BY_KEY}


def temp_leftovers(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


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

    def test_write_creates_missing_file(self, cfg_path, valid_values):
        TunnelConfig(cfg_path).write(valid_values)

        assert cfg_path.read_text() == cfg_text(valid_values)
        assert stat.S_IMODE(cfg_path.stat().st_mode) == NEW_FILE_MODE
        assert temp_leftovers(cfg_path.parent) == []

    def test_write_then_read_round_trip(self, cfg_path, valid_values):
        config = TunnelConfig(cfg_path)
        config.write(valid_values)
        assert config.read() == valid_values

    def test_write_existing_file_keeps_its_mode(
        self, make_config, valid_values
    ):
        config = make_config(cfg_text(valid_values))
        os.chmod(config.path, 0o600)

        config.write(valid_values | {"REMOTE_USER": "petya"})

        assert stat.S_IMODE(config.path.stat().st_mode) == 0o600
        assert config.read()["REMOTE_USER"] == "petya"

    def test_write_through_symlink_updates_target(
        self, tmp_path, valid_values
    ):
        target = tmp_path / "real.cfg"
        target.write_text(cfg_text(valid_values))
        link = tmp_path / "link.cfg"
        link.symlink_to(target)

        TunnelConfig(link).write(valid_values | {"REMOTE_USER": "petya"})

        assert link.is_symlink()
        assert TunnelConfig(target).read()["REMOTE_USER"] == "petya"

    def test_failed_write_keeps_file_and_removes_temp_file(
        self, make_config, valid_values, monkeypatch
    ):
        # Fail after the temp file was written (e.g. disk full, I/O error).
        original = cfg_text(valid_values)
        config = make_config(original)

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError, match="No space left"):
            config.write(valid_values | {"REMOTE_USER": "petya"})

        assert config.path.read_text() == original
        assert temp_leftovers(config.path.parent) == []

    def test_write_into_missing_directory_raises(self, tmp_path, valid_values):
        config = TunnelConfig(tmp_path / "no" / "such" / "dir.cfg")
        with pytest.raises(FileNotFoundError):
            config.write(valid_values)

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_write_without_permission_raises_and_keeps_file(
        self, tmp_path, valid_values
    ):
        directory = tmp_path / "ro"
        directory.mkdir()
        path = directory / "vt-tunnel.cfg"
        path.write_text("ENABLED=false\n")
        directory.chmod(0o555)
        try:
            with pytest.raises(PermissionError):
                TunnelConfig(path).write(valid_values)
            assert path.read_text() == "ENABLED=false\n"
            assert temp_leftovers(directory) == []
        finally:
            directory.chmod(0o755)


# --------------------------------------------------------------------------
# Config file with expected values
# --------------------------------------------------------------------------


DOC_EXAMPLE = """\
# vt-tunnel configuration
ENABLED=false
RUN_DAEMON_USER=username
REMOTE_USER=vasya
REMOTE_SERVER=vasya.com
REMOTE_SSH_PORT=22
LOCAL_PORT1=22
REMOTE_PORT1=5001
"""


class TestExpectedValues:
    def test_read_doc_example(self, make_config):
        config = make_config(DOC_EXAMPLE)
        assert config.read() == VALID_VALUES

    def test_doc_example_is_valid(self, make_config):
        assert TunnelConfig.validate(make_config(DOC_EXAMPLE).read()) == []

    @pytest.mark.parametrize("enabled", ["true", "false"])
    def test_enabled_values(self, valid_values, enabled):
        assert TunnelConfig.validate(valid_values | {"ENABLED": enabled}) == []

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize(
        "port", [str(config_schema.PORT_MIN), "443", str(config_schema.PORT_MAX)]
    )
    def test_port_range_boundaries_are_valid(self, valid_values, key, port):
        assert TunnelConfig.validate(valid_values | {key: port}) == []

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize(
        "value", ["a", "vasya", "VASYA_01", "my-host.example.com", "10.0.0.1"]
    )
    def test_identifier_charset_is_valid(self, valid_values, key, value):
        assert TunnelConfig.validate(valid_values | {key: value}) == []

    def test_whitespace_and_comments_are_not_part_of_values(self, make_config):
        config = make_config(
            "  # indented comment\n"
            "\n"
            "ENABLED = false\n"
            "RUN_DAEMON_USER=username   # trailing comment\n"
            "\tREMOTE_USER=vasya\t\n"
            "REMOTE_SERVER=vasya.com\n"
            "REMOTE_SSH_PORT=22#no space before comment\n"
            "LOCAL_PORT1=22\n"
            "REMOTE_PORT1=5001\n"
        )
        assert config.read() == VALID_VALUES

    def test_crlf_line_endings(self, cfg_path):
        cfg_path.write_bytes(DOC_EXAMPLE.replace("\n", "\r\n").encode())
        assert TunnelConfig(cfg_path).read() == VALID_VALUES

    def test_utf8_bom_is_ignored(self, cfg_path):
        # BOM right before the first key (not a comment line), as written
        # by some editors.
        cfg_path.write_bytes(b"\xef\xbb\xbf" + cfg_text(VALID_VALUES).encode())
        assert TunnelConfig(cfg_path).read() == VALID_VALUES

    def test_unknown_keys_are_read_too(self, make_config):
        config = make_config(DOC_EXAMPLE + "OTHER_KEY=something\n")
        assert config.read() == VALID_VALUES | {"OTHER_KEY": "something"}


# --------------------------------------------------------------------------
# Out-of-range values
# --------------------------------------------------------------------------


OUT_OF_RANGE_PORTS = [
    "0",
    "-1",
    "65536",
    "70000",
    "99999999999999999999",
]


class TestOutOfRangeValues:
    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("port", OUT_OF_RANGE_PORTS)
    def test_port_out_of_range_is_invalid(self, valid_values, key, port):
        assert_only_invalid(valid_values | {key: port}, key)

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("port", OUT_OF_RANGE_PORTS)
    def test_out_of_range_port_in_file_is_read_verbatim_and_flagged(
        self, make_config, valid_values, key, port
    ):
        # Reading never fails on bad values, so the user can see and fix
        # them; validation reports them.
        values = make_config(cfg_text(valid_values | {key: port})).read()
        assert values[key] == port
        assert_only_invalid(values, key)

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("port", OUT_OF_RANGE_PORTS)
    def test_out_of_range_port_is_not_written(
        self, make_config, valid_values, key, port
    ):
        config = make_config(cfg_text(valid_values))
        assert_write_rejected(config, valid_values | {key: port})

    def test_error_message_names_the_allowed_range(self, valid_values):
        message = errors_for(valid_values | {"LOCAL_PORT1": "0"})["LOCAL_PORT1"]
        assert "1" in message and "65535" in message

    def test_all_errors_are_reported_at_once(self, valid_values):
        values = valid_values | {
            "REMOTE_SSH_PORT": "0",
            "LOCAL_PORT1": "65536",
            "REMOTE_PORT1": "-5",
        }
        assert sorted(errors_for(values)) == sorted(PORT_KEYS)


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
            pytest.param("REMOTE_USER vasya\n", {}, id="no-equals-sign"),
            pytest.param("REMOTE_USER\n", {}, id="key-only"),
            pytest.param("=vasya\n", {}, id="empty-key"),
            pytest.param("  =vasya\n", {}, id="blank-key"),
            pytest.param("# REMOTE_USER=vasya\n", {}, id="commented-out"),
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
    def test_parse(self, make_config, text, expected):
        assert make_config(text).read() == expected

    def test_undecodable_bytes_do_not_crash_read(self, cfg_path):
        cfg_path.write_bytes(b"REMOTE_USER=caf\xe9\n")
        value = TunnelConfig(cfg_path).read()["REMOTE_USER"]
        assert value.startswith("caf")
        assert "REMOTE_USER" in errors_for(VALID_VALUES | {"REMOTE_USER": value})

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("remote_user=vasya", id="lowercase-key"),
            pytest.param("export REMOTE_USER=vasya", id="shell-export"),
            pytest.param("REMOTE USER=vasya", id="space-in-key"),
        ],
    )
    def test_misspelled_key_leaves_schema_key_missing(
        self, make_config, valid_values, line
    ):
        del valid_values["REMOTE_USER"]
        values = make_config(cfg_text(valid_values) + line + "\n").read()
        assert "REMOTE_USER" not in values
        assert_only_invalid(schema_subset(values), "REMOTE_USER")


class TestMissingKeys:
    @pytest.mark.parametrize("key", list(VALID_VALUES))
    def test_missing_key_is_absent_from_read(
        self, make_config, valid_values, key
    ):
        del valid_values[key]
        values = make_config(cfg_text(valid_values)).read()
        assert key not in values
        assert errors_for(values) == {key: f"{key}: missing"}

    def test_empty_file_misses_every_key(self, make_config):
        values = make_config("").read()
        assert sorted(errors_for(values)) == sorted(VALID_VALUES)

    @pytest.mark.parametrize("key", list(VALID_VALUES))
    def test_write_with_missing_key_is_rejected(
        self, make_config, valid_values, key
    ):
        config = make_config(cfg_text(valid_values))
        del valid_values[key]
        assert_write_rejected(config, valid_values)

    def test_write_unknown_key_is_rejected(self, cfg_path, valid_values):
        values = valid_values | {"EXTRA_KEY": "x"}
        assert list(errors_for(values)) == ["'EXTRA_KEY'"]
        with pytest.raises(ValidationError):
            TunnelConfig(cfg_path).write(values)
        assert not cfg_path.exists()


class TestMissingValues:
    @pytest.mark.parametrize("key", PORT_KEYS + IDENTIFIER_KEYS)
    @pytest.mark.parametrize(
        "line_value",
        [
            pytest.param("", id="empty"),
            pytest.param("   ", id="blank"),
            pytest.param(" # comment", id="comment-only"),
        ],
    )
    def test_empty_value_is_read_as_empty_and_invalid(
        self, make_config, valid_values, key, line_value
    ):
        values = make_config(
            cfg_text(valid_values | {key: line_value})
        ).read()
        assert values[key] == ""
        assert_only_invalid(values, key)

    @pytest.mark.parametrize("key", PORT_KEYS + IDENTIFIER_KEYS)
    def test_empty_value_is_not_written(self, make_config, valid_values, key):
        config = make_config(cfg_text(valid_values))
        assert_write_rejected(config, valid_values | {key: ""})

    def test_enabled_has_no_value_rules(self, valid_values):
        # Dead key (see config_schema.ENABLED): any storable value is OK.
        for value in ["", "yes", "0"]:
            assert TunnelConfig.validate(valid_values | {"ENABLED": value}) == []


# --------------------------------------------------------------------------
# Values that could break or inject into the ssh command line
# --------------------------------------------------------------------------
#
#   ExecStart=/usr/bin/sudo su -s /bin/bash -c 'autossh -N
#       -p${REMOTE_SSH_PORT} ${REMOTE_USER}@${REMOTE_SERVER}
#       -R ${REMOTE_PORT1}:localhost:${LOCAL_PORT1}' ${RUN_DAEMON_USER}


DANGEROUS_IDENTIFIERS = [
    pytest.param("vasya smith", id="space"),
    pytest.param("vasya\tx", id="tab"),
    pytest.param(" vasya", id="leading-space"),
    pytest.param("$USER", id="dollar-var"),
    pytest.param("${USER}", id="dollar-brace"),
    pytest.param("$(reboot)", id="command-subst"),
    pytest.param("`reboot`", id="backticks"),
    pytest.param("vasya;reboot", id="semicolon"),
    pytest.param("vasya&&reboot", id="and"),
    pytest.param("vasya&", id="background"),
    pytest.param("vasya|nc", id="pipe"),
    pytest.param("vasya>/etc/passwd", id="redirect-out"),
    pytest.param("vasya</etc/shadow", id="redirect-in"),
    pytest.param("va'sya", id="single-quote-closes-bash-c"),
    pytest.param('va"sya', id="double-quote"),
    pytest.param("va\\sya", id="backslash"),
    pytest.param("vasya*", id="glob-star"),
    pytest.param("vasy?", id="glob-question"),
    pytest.param("[ab]", id="glob-class"),
    pytest.param("{a,b}", id="brace-expansion"),
    pytest.param("~root", id="tilde"),
    pytest.param("vasya!", id="history"),
    pytest.param("(vasya)", id="subshell"),
    pytest.param("vasya@evil.com", id="at-redirects-host"),
    pytest.param("evil.com:2222", id="colon"),
    pytest.param("-oProxyCommand=reboot", id="ssh-option-with-equals"),
    pytest.param("a/b", id="slash"),
    pytest.param("a,b", id="comma"),
    pytest.param("vasya#x", id="hash-comment"),
    pytest.param("vasya\nREMOTE_PORT1=1", id="newline-injects-key"),
    pytest.param("vasya\r", id="carriage-return"),
    pytest.param("vasya\x00", id="nul"),
    pytest.param("v\u0430sya", id="cyrillic-homoglyph"),
    pytest.param("vasy\u0430.com", id="cyrillic-a-in-host"),
    pytest.param("", id="empty"),
]

LEADING_DASH_IDENTIFIERS = [
    pytest.param("-F.evil", id="ssh-config-option"),
    pytest.param("-v", id="short-option"),
    pytest.param("--", id="end-of-options"),
    pytest.param("-", id="dash-only"),
    pytest.param("-oProxyCommand", id="ssh-o-option"),
    pytest.param("--login", id="su-long-option"),
]

DANGEROUS_PORTS = [
    pytest.param("22 -oProxyCommand=reboot", id="space-option"),
    pytest.param("22;reboot", id="semicolon"),
    pytest.param("$PORT", id="dollar-var"),
    pytest.param("${PORT}", id="dollar-brace"),
    pytest.param("$(echo 22)", id="command-subst"),
    pytest.param("`echo 22`", id="backticks"),
    pytest.param("22|nc", id="pipe"),
    pytest.param("22&", id="background"),
    pytest.param("22'", id="single-quote"),
    pytest.param("22:localhost:23", id="colon-changes-forward"),
    pytest.param("22\nLOCAL_PORT1=1", id="newline-injects-key"),
    pytest.param(" 22", id="leading-space"),
    pytest.param("22 ", id="trailing-space"),
    pytest.param("2 2", id="inner-space"),
    pytest.param("+22", id="plus-sign"),
    pytest.param("-22", id="minus-sign"),
    pytest.param("22.0", id="decimal"),
    pytest.param("2_2", id="underscore"),
    pytest.param("0x16", id="hex"),
    pytest.param("1e3", id="exponent"),
    pytest.param("\uff12\uff12", id="fullwidth-digits"),
    pytest.param("\u0662\u0662", id="arabic-indic-digits"),
    pytest.param("twenty-two", id="letters"),
]


class TestShellBreakingValues:
    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_IDENTIFIERS)
    def test_dangerous_identifier_is_invalid(self, valid_values, key, value):
        assert_only_invalid(valid_values | {key: value}, key)

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_IDENTIFIERS)
    def test_dangerous_identifier_is_not_written(
        self, make_config, valid_values, key, value
    ):
        config = make_config(cfg_text(valid_values))
        assert_write_rejected(config, valid_values | {key: value})

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_PORTS)
    def test_dangerous_port_is_invalid(self, valid_values, key, value):
        assert_only_invalid(valid_values | {key: value}, key)

    @pytest.mark.parametrize("key", PORT_KEYS)
    @pytest.mark.parametrize("value", DANGEROUS_PORTS)
    def test_dangerous_port_is_not_written(
        self, make_config, valid_values, key, value
    ):
        config = make_config(cfg_text(valid_values))
        assert_write_rejected(config, valid_values | {key: value})

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("true\nREMOTE_USER=x", id="newline-injects-key"),
            pytest.param("true # x", id="hash-comment"),
            pytest.param("true\r", id="carriage-return"),
            pytest.param("true\x00", id="nul"),
            pytest.param(" true", id="leading-space"),
        ],
    )
    def test_enabled_cannot_break_the_file(
        self, make_config, valid_values, value
    ):
        assert_only_invalid(valid_values | {"ENABLED": value}, "ENABLED")
        assert_write_rejected(
            make_config(cfg_text(valid_values)), valid_values | {"ENABLED": value}
        )

    @pytest.mark.parametrize(
        "line, key",
        [
            ("REMOTE_USER=$(reboot)", "REMOTE_USER"),
            ("REMOTE_SERVER=vasya.com;reboot", "REMOTE_SERVER"),
            ("RUN_DAEMON_USER=root' -c 'reboot", "RUN_DAEMON_USER"),
            ("REMOTE_SSH_PORT=22 -oProxyCommand=reboot", "REMOTE_SSH_PORT"),
            ("LOCAL_PORT1=`reboot`", "LOCAL_PORT1"),
        ],
    )
    def test_hand_edited_injection_is_read_verbatim_and_flagged(
        self, make_config, valid_values, line, key
    ):
        # A hand-edited file is shown as is (no expansion, nothing run) and
        # flagged, so it can't be saved back until fixed.
        del valid_values[key]
        values = make_config(cfg_text(valid_values) + line + "\n").read()
        assert values[key] == line.split("=", 1)[1]
        assert_only_invalid(values, key)

    def test_rejected_newline_cannot_add_a_line(self, make_config, valid_values):
        config = make_config(cfg_text(valid_values))
        with pytest.raises(ValidationError):
            config.write(valid_values | {"REMOTE_USER": "x\nREMOTE_PORT1=1"})
        assert config.read()["REMOTE_PORT1"] == valid_values["REMOTE_PORT1"]

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize("value", LEADING_DASH_IDENTIFIERS)
    def test_leading_dash_is_invalid(self, valid_values, key, value):
        # ssh/su would parse the value as a command-line option.
        assert_only_invalid(valid_values | {key: value}, key)

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize("value", LEADING_DASH_IDENTIFIERS)
    def test_leading_dash_is_not_written(
        self, make_config, valid_values, key, value
    ):
        config = make_config(cfg_text(valid_values))
        assert_write_rejected(config, valid_values | {key: value})

    @pytest.mark.parametrize("key", IDENTIFIER_KEYS)
    @pytest.mark.parametrize(
        "value", ["my-host", "vasya-", "a-b-c", "_svc", ".local", "9-lives"]
    )
    def test_dash_after_first_char_is_valid(self, valid_values, key, value):
        assert TunnelConfig.validate(valid_values | {key: value}) == []


# --------------------------------------------------------------------------
# Rewriting an existing file
# --------------------------------------------------------------------------


class TestRewritePreservesFile:
    def test_other_lines_kept_verbatim(self, make_config, valid_values):
        config = make_config(
            "# header comment\n"
            "\n"
            "ENABLED=true\n"
            "REMOTE_USER=old   # inline comment\n"
            "  # indented comment\n"
            "OTHER_KEY=keep  me   # as is\n"
            "REMOTE_USER=duplicate\n"
            "junk line without equals\n"
        )
        config.write(valid_values)

        assert config.path.read_text() == (
            "# header comment\n"
            "\n"
            "ENABLED=false\n"
            "REMOTE_USER=vasya\n"
            "  # indented comment\n"
            "OTHER_KEY=keep  me   # as is\n"
            "junk line without equals\n"
            "RUN_DAEMON_USER=username\n"
            "REMOTE_SERVER=vasya.com\n"
            "REMOTE_SSH_PORT=22\n"
            "LOCAL_PORT1=22\n"
            "REMOTE_PORT1=5001\n"
        )

    def test_undecodable_bytes_in_other_lines_survive(
        self, cfg_path, valid_values
    ):
        cfg_path.write_bytes(b"OTHER=caf\xe9\xff\n" + cfg_text(valid_values).encode())
        TunnelConfig(cfg_path).write(valid_values)
        assert cfg_path.read_bytes().startswith(b"OTHER=caf\xe9\xff\n")

    def test_crlf_file_is_rewritten_with_lf(self, cfg_path, valid_values):
        cfg_path.write_bytes(cfg_text(valid_values).replace("\n", "\r\n").encode())
        TunnelConfig(cfg_path).write(valid_values)
        assert b"\r" not in cfg_path.read_bytes()
        assert TunnelConfig(cfg_path).read() == valid_values

    def test_utf8_bom_file_is_rewritten_without_duplicates(
        self, cfg_path, valid_values
    ):
        cfg_path.write_bytes(b"\xef\xbb\xbf" + cfg_text(valid_values).encode())
        TunnelConfig(cfg_path).write(valid_values | {"ENABLED": "true"})
        assert cfg_path.read_text() == cfg_text(valid_values | {"ENABLED": "true"})
