"""Shared fixtures for the TunnelConfig tests."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models.tunnel_config import TunnelConfig

# A complete, valid config: the examples from config_schema.py, which are
# also the examples of the table in doc/config.md.
VALID_VALUES: dict[str, str] = {
    field.key: field.example for field in config_schema.FIELDS
}

PORT_KEYS = [
    f.key for f in config_schema.FIELDS
    if f.type is config_schema.FieldType.PORT
]
IDENTIFIER_KEYS = [
    f.key for f in config_schema.FIELDS
    if f.type is config_schema.FieldType.IDENTIFIER
]


def cfg_text(values: dict[str, str]) -> str:
    """Render ``values`` as config file text."""
    return "".join(f"{key}={value}\n" for key, value in values.items())


@pytest.fixture
def valid_values() -> dict[str, str]:
    return dict(VALID_VALUES)


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    """Path of a config file that doesn't exist yet."""
    return tmp_path / "vt-tunnel.cfg"


@pytest.fixture
def make_config(cfg_path: Path) -> Callable[[str], TunnelConfig]:
    """Write ``text`` to the config file and return a TunnelConfig for it."""

    def make(text: str) -> TunnelConfig:
        cfg_path.write_text(text, encoding="utf-8")
        return TunnelConfig(cfg_path)

    return make
