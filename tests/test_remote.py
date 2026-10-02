"""Tests for the Oppo UDP-20x remote entity."""
from __future__ import annotations

from homeassistant.components.remote import ATTR_DELAY_SECS, ATTR_NUM_REPEATS

from custom_components.oppo_player.const import DOMAIN
from custom_components.oppo_player.oppoudpsdk import PowerStatus
from custom_components.oppo_player.remote import OppoUdpRemote
from tests.conftest import MOCK_HOST


def _remote(manager):
    return OppoUdpRemote(MOCK_HOST, DOMAIN, "entry_id", manager)


def test_is_on(mock_manager):
    mock_manager.device.power_status = PowerStatus.ON
    assert _remote(mock_manager).is_on is True
    mock_manager.device.power_status = PowerStatus.OFF
    assert _remote(mock_manager).is_on is False


async def test_turn_on_off_send_commands(mock_manager):
    remote = _remote(mock_manager)
    client = mock_manager.device._client
    await remote.async_turn_on()
    await remote.async_turn_off()
    assert client.async_send_command.await_count == 2


async def test_send_command_iterates(mock_manager):
    remote = _remote(mock_manager)
    client = mock_manager.device._client
    await remote.async_send_command(
        ["PLA", "STP"], **{ATTR_NUM_REPEATS: 1, ATTR_DELAY_SECS: 0}
    )
    # One SDK send per command in the list.
    assert client.async_send_command.await_count == 2
