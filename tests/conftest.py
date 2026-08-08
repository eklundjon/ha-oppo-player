"""Shared fixtures for oppo_udp tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make custom_components importable from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.oppo_udp.const import DOMAIN  # noqa: E402

MOCK_HOST = "192.168.1.50"
MOCK_PORT = 23
ENTRY_DATA = {"host": MOCK_HOST, "port": MOCK_PORT}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow the custom component to load during tests (HA 2021.6+)."""
    yield


@pytest.fixture
def mock_device():
    """A real OppoDevice wired to a mocked client.

    Using a real instance (not a bare MagicMock) makes attribute reads and
    method lookups behave like production: calling a method that does not exist
    on OppoDevice raises AttributeError — precisely the class of bug
    (async_set_repeat_mode, async_set_position) that reached hardware. Every
    device set-method delegates to client.async_send_command, so mocking that
    one method lets the whole command path run.
    """
    from custom_components.oppo_udp.oppoudpsdk import OppoDevice

    client = MagicMock()
    client.async_send_command = AsyncMock()
    client.async_event = AsyncMock()
    device = OppoDevice(client)
    # Default the test device to a UDP-20x (the full-capability model), the way
    # a QVR reply would; per-model behavior is exercised in test_models.py.
    device.firmware_version = "UDP20X-54-1127"
    return device


@pytest.fixture
def mock_manager(mock_device):
    """A stand-in OppoController exposing what entities read from it."""
    manager = MagicMock()
    manager.device = mock_device
    manager.online = True
    manager.config_entry = MagicMock()
    manager.config_entry.title = f"Oppo UDP-20x {MOCK_HOST}"
    return manager


@pytest.fixture
def config_entry(hass):
    """A MockConfigEntry added to hass."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Oppo UDP-20x {MOCK_HOST}",
        data=ENTRY_DATA,
        options={},
    )
    entry.add_to_hass(hass)
    return entry
