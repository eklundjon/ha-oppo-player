"""Tests for OppoController: real OppoConnection + real OppoDevice, fake socket."""
from __future__ import annotations

from unittest.mock import patch

from custom_components.oppo_player.controller import OppoController, entry_url
from custom_components.oppo_player.oppoudpsdk import OppoRemoteCode, PowerStatus
from custom_components.oppo_player.oppoudpsdk.const import EVENT_DEVICE_STATE_UPDATED
from tests.conftest import ENTRY_DATA, MOCK_HOST, MOCK_PORT
from tests.test_connection import FakeTransport, _wait_for


def _patches(transport):
    return (
        patch(
            "custom_components.oppo_player.connection.serialx.open_serial_connection",
            side_effect=transport.open,
        ),
        patch("custom_components.oppo_player.controller.SEND_INTERVAL", 0),
    )


# ── URL migration (no socket needed) ───────────────────────────────────────────

def test_entry_url_migrates_host_port(config_entry):
    assert entry_url(config_entry) == f"socket://{MOCK_HOST}:{MOCK_PORT}"


def test_entry_url_prefers_stored_url(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain="oppo_player", data={**ENTRY_DATA, "url": "rfc2217://gw:5000"}
    )
    assert entry_url(entry) == "rfc2217://gw:5000"


# ── behavior (fake transport) ──────────────────────────────────────────────────

async def test_start_pulls_initial_state(hass, config_entry):
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        controller = OppoController(hass, config_entry)
        await controller.async_start()
        await controller.disconnect()
    # async_request_update enables verbose and queries state on connect.
    assert b"#SVM" in bytes(transport.pairs[0][1].buffer)
    assert b"#QPW" in bytes(transport.pairs[0][1].buffer)


async def test_incoming_update_reaches_device_and_fires_event(hass, config_entry):
    transport = FakeTransport()
    updated: list = []

    async def on_updated(device):
        updated.append(device)

    p1, p2 = _patches(transport)
    with p1, p2:
        controller = OppoController(hass, config_entry)
        controller.add_event_handler(EVENT_DEVICE_STATE_UPDATED, on_updated)
        await controller.async_start()
        transport.reader.feed_line("@UPW 1")  # power-on push
        await _wait_for(lambda: controller.device.power_status == PowerStatus.ON)
        await controller.disconnect()
    assert controller.device.power_status == PowerStatus.ON
    assert updated  # EVENT_DEVICE_STATE_UPDATED reached the (entity-style) handler


async def test_device_command_writes_framed_bytes(hass, config_entry):
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        controller = OppoController(hass, config_entry)
        await controller.async_start()
        transport.writer.buffer.clear()  # drop the startup queries
        await controller.device.async_send_command(OppoRemoteCode.PLA)
        await _wait_for(lambda: bytes(transport.writer.buffer) == b"#PLA\r")
        await controller.disconnect()


async def test_reconnect_repulls_state(hass, config_entry):
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with (
        patch("custom_components.oppo_player.connection.RECONNECT_DELAY", 0),
        p1,
        p2,
    ):
        controller = OppoController(hass, config_entry)
        await controller.async_start()
        transport.reader.feed_eof()  # drop
        await _wait_for(lambda: transport.connect_count == 2)
        # a fresh snapshot is pulled on the new connection
        await _wait_for(lambda: b"#QPW" in bytes(transport.pairs[1][1].buffer))
        await controller.disconnect()
