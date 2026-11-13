"""Tests for the ssh-keys discovery module."""

import os
import pwd

import pytest

from vt_tunnel_gui.models import ssh_keys

# OpenSSH 9's default private-identity names, in fallback order.
_DEFAULT_NAMES = (
    "id_rsa",
    "id_ecdsa",
    "id_ecdsa_sk",
    "id_ed25519",
    "id_ed25519_sk",
    "id_dsa",
)


def _default_candidates(home):
    return tuple(str(home / ".ssh" / name) for name in _DEFAULT_NAMES)


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def test_no_key(fake_ssh, fake_home):
    """Nothing exists and no agent keys: a falsy result with all defaults."""
    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result is not None
    assert not result
    assert result.key_files == ()
    assert result.agent_keys is False
    assert result.candidates == _default_candidates(fake_home)


def test_key_file(fake_ssh, fake_home):
    """An existing default key file is found and makes the result truthy."""
    key = _touch(fake_home / ".ssh" / "id_ed25519")

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result
    assert result.key_files == (str(key),)
    assert str(key) in result.candidates


def test_public_key_alone_is_no_key(fake_ssh, fake_home):
    """A .pub file alone is not a private key: nothing to log in with."""
    _touch(fake_home / ".ssh" / "id_ed25519.pub")

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert not result
    assert result.key_files == ()
    assert result.candidates == _default_candidates(fake_home)


def test_directory_is_not_a_key(fake_ssh, fake_home):
    """A directory at a candidate path is not a key."""
    (fake_home / ".ssh" / "id_rsa").mkdir()

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert not result
    assert result.key_files == ()
    assert str(fake_home / ".ssh" / "id_rsa") in result.candidates


def test_key_in_agent(fake_ssh, fake_home):
    """ssh-add exit 0: agent keys, truthy even with no key file."""
    fake_ssh.set_add_exit(0)

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result
    assert result.agent_keys is True
    assert result.key_files == ()


def test_agent_without_keys(fake_ssh, fake_home):
    """ssh-add exit 1 (agent alive, empty): no agent keys."""
    fake_ssh.set_add_exit(1)

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result.agent_keys is False


def test_no_ssh_add(fake_ssh, fake_home):
    """A missing ssh-add degrades silently to no agent keys."""
    fake_ssh.ssh_add_path.unlink()

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result is not None
    assert result.agent_keys is False


def test_identity_file_from_ssh_config(fake_ssh, fake_home, tmp_path):
    """ssh -G's identity-file lines contribute candidates (exit 0 only)."""
    configured = _touch(tmp_path / "keys" / "tunnel")
    fake_ssh.set_g_output(f"IdentityFile {configured}\n")

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result
    assert result.key_files == (str(configured),)
    assert result.candidates == (str(configured),)


def test_only_configured_identity_file_counts(fake_ssh, fake_home, tmp_path):
    """When ssh answers, its identity files replace the defaults entirely."""
    existing_default = _touch(fake_home / ".ssh" / "id_rsa")
    configured = _touch(tmp_path / "keys" / "tunnel")
    fake_ssh.set_g_output(f"identityfile {configured}\n")

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result.key_files == (str(configured),)
    assert str(existing_default) not in result.candidates


def test_tokens_in_identity_file(fake_ssh, fake_home):
    """ssh_config tokens expand to the local home, user and this login."""
    local = pwd.getpwuid(os.getuid()).pw_name
    expected = fake_home / ".ssh" / f"t-%-{local}-srv.example.org-2222-user"
    _touch(expected)
    fake_ssh.set_g_output("identityfile %d/.ssh/t-%%-%u-%h-%p-%r\n")

    result = ssh_keys.discover_keys("user", "srv.example.org", "2222")

    assert result.key_files == (str(expected),)


def test_ssh_asked_for_this_login(fake_ssh, fake_home):
    """The -G query names this login: the user, the server and the port."""
    ssh_keys.discover_keys("user", "srv.example.org", "2222")

    assert fake_ssh.login_argv == ["-G", "-p", "2222", "user@srv.example.org"]


def test_ssh_config_error_falls_back_to_defaults(fake_ssh, fake_home):
    """A nonzero ssh -G exit falls back to the default identity names."""
    fake_ssh.set_g_output("identityfile /opt/keys/tunnel\n")
    fake_ssh.set_g_exit(255)

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result is not None
    assert result.key_files == ()
    assert result.candidates == _default_candidates(fake_home)


def test_no_ssh_binary(fake_ssh, fake_home):
    """ssh itself cannot run: discovery returns nothing at all."""
    fake_ssh.ssh_path.unlink()

    result = ssh_keys.discover_keys("user", "srv.example.org", "22")

    assert result is None


def test_display_path(fake_home):
    """Paths under the home display in tilde form; others unchanged."""
    assert ssh_keys.display_path(str(fake_home)) == "~"
    assert ssh_keys.display_path(str(fake_home / "x" / "k")) == "~/x/k"
    assert ssh_keys.display_path("/etc/passwd") == "/etc/passwd"
    assert ssh_keys.display_path(str(fake_home) + "-other/k") == (
        str(fake_home) + "-other/k"
    )


def test_local_user_note(fake_home):
    """The mismatch note fires only for another configured run user."""
    current = ssh_keys.local_user()

    assert current is not None
    assert ssh_keys.mismatch_warning(current) is None
    assert ssh_keys.mismatch_warning("") is None
    note = ssh_keys.mismatch_warning("tunneluser")
    assert note is not None
    assert "tunneluser" in note
    assert "sudo -u" in note


def test_local_user_note_unknown_current_user(fake_home, monkeypatch):
    """No local user name: no note, and the lookup returns nothing."""

    def raise_key_error(*args, **kwargs):
        raise KeyError("no such user")

    monkeypatch.setattr(pwd, "getpwuid", raise_key_error)

    assert ssh_keys.local_user() is None
    assert ssh_keys.mismatch_warning("tunneluser") is None


def test_custom_port(fake_ssh, fake_home):
    """A custom port reaches the -G query and the %p token expansion."""
    expected = _touch(fake_home / ".ssh" / "port-2222")
    fake_ssh.set_g_output("identityfile %d/.ssh/port-%p\n")

    result = ssh_keys.discover_keys("user", "srv.example.org", "2222")

    assert fake_ssh.login_argv == ["-G", "-p", "2222", "user@srv.example.org"]
    assert result.key_files == (str(expected),)
