"""Tests of the SSH key lookup: identity files ssh would try, ssh-agent.

A fake ``ssh`` answers ``ssh -G`` and a fake ``ssh-add`` plays the agent
(fixtures in conftest); HOME is a fresh temporary directory.
"""

import getpass

import pytest

from conftest import VALID_VALUES
from vt_tunnel_gui.models import ssh_keys
from vt_tunnel_gui.models.ssh_keys import find_keys

USER = VALID_VALUES["REMOTE_USER"]
SERVER = VALID_VALUES["REMOTE_SERVER"]


class TestFindKeys:
    def test_no_key(self, fake_ssh, home):
        fake_ssh("")
        keys = find_keys(USER, SERVER)
        assert not keys
        assert keys.files == ()
        assert home / ".ssh" / "id_ed25519" in keys.searched

    def test_key_file(self, fake_ssh, key):
        fake_ssh("")
        keys = find_keys(USER, SERVER)
        assert keys
        assert keys.files == (key,)

    def test_public_key_alone_is_no_key(self, fake_ssh, home):
        (home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAA\n")
        fake_ssh("")
        assert not find_keys(USER, SERVER)

    def test_directory_is_not_a_key(self, fake_ssh, home):
        (home / ".ssh" / "id_ed25519").mkdir()
        fake_ssh("")
        assert not find_keys(USER, SERVER)

    def test_key_in_agent(self, fake_ssh):
        fake_ssh("", agent_exit=0)
        keys = find_keys(USER, SERVER)
        assert keys
        assert keys.in_agent and keys.files == ()

    @pytest.mark.parametrize("agent_exit", [1, 2])  # no keys / no agent
    def test_agent_without_keys(self, fake_ssh, agent_exit):
        fake_ssh("", agent_exit=agent_exit)
        assert not find_keys(USER, SERVER).in_agent

    def test_no_ssh_add(self, fake_ssh, tmp_path):
        fake_ssh("")
        (tmp_path / "bin" / "ssh-add").unlink()
        assert not find_keys(USER, SERVER).in_agent

    def test_identity_file_from_ssh_config(self, fake_ssh, home):
        # `IdentityFile ~/.ssh/tunnel` in ~/.ssh/config: ssh -G lists it
        (home / ".ssh" / "tunnel").write_text("key")
        fake_ssh("", g_output="identityfile ~/.ssh/tunnel\n")
        assert find_keys(USER, SERVER).files == (home / ".ssh" / "tunnel",)

    def test_only_the_configured_identity_file_counts(self, fake_ssh, key):
        # IdentityFile set: the default id_ed25519 is not what ssh uses
        fake_ssh("", g_output="identityfile ~/.ssh/tunnel\n")
        assert not find_keys(USER, SERVER)

    def test_tokens_in_identity_file(self, fake_ssh, home):
        (home / ".ssh" / f"id_{USER}_{SERVER}").write_text("key")
        fake_ssh("", g_output="identityfile %d/.ssh/id_%r_%h\n")
        assert find_keys(USER, SERVER).files == (
            home / ".ssh" / f"id_{USER}_{SERVER}",
        )

    def test_ssh_asked_for_this_login(self, fake_ssh, tmp_path):
        # -G evaluates Host/Match blocks for user@server
        fake_ssh("")
        log = tmp_path / "g-argv"
        script = tmp_path / "bin" / "ssh"
        script.write_text(
            f"#!/bin/bash\nprintf '%s\\n' \"$@\" > {log}\n"
        )
        find_keys(USER, SERVER)
        assert log.read_text().splitlines() == ["-G", f"{USER}@{SERVER}"]

    def test_ssh_config_error_falls_back_to_defaults(self, fake_ssh, key):
        fake_ssh("", g_output="", g_exit=255)
        assert find_keys(USER, SERVER).files == (key,)

    def test_no_ssh(self, tmp_path, monkeypatch, home):
        monkeypatch.setenv("PATH", str(tmp_path))
        assert find_keys(USER, SERVER) is None


class TestDisplayPath:
    def test_home_as_tilde(self, home):
        assert ssh_keys.display_path(home / ".ssh" / "id_rsa") == (
            "~/.ssh/id_rsa"
        )

    def test_outside_home(self, home):
        assert ssh_keys.display_path(ssh_keys.Path("/etc/x")) == "/etc/x"


class TestLocalUserNote:
    def test_same_user(self):
        assert ssh_keys.local_user_note(getpass.getuser()) is None

    def test_empty(self):
        assert ssh_keys.local_user_note("") is None

    def test_other_user(self):
        note = ssh_keys.local_user_note("tunnel-user")
        assert "tunnel-user" in note
        assert getpass.getuser() in note

    def test_unknown_current_user(self, monkeypatch):
        def fail():
            raise OSError("no user")

        monkeypatch.setattr(ssh_keys.getpass, "getuser", fail)
        assert ssh_keys.local_user_note("tunnel-user") is None
