"""Setup/unload wiring: the config entry runs on an OppoController."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from custom_components.oppo_player.controller import OppoController
from tests.test_connection import FakeTransport


def _patches(transport):
    return (
        patch(
            "custom_components.oppo_player.connection.serialx.open_serial_connection",
            side_effect=transport.open,
        ),
        patch("custom_components.oppo_player.controller.SEND_INTERVAL", 0),
    )


async def test_setup_wires_controller_and_entities(hass, config_entry):
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # runtime_data now holds the controller, and the transport is open.
        assert isinstance(config_entry.runtime_data, OppoController)
        assert transport.connect_count == 1

        # both platforms produced an entity.
        domains = {state.domain for state in hass.states.async_all()}
        assert "media_player" in domains
        assert "remote" in domains

        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

    # connection torn down on unload.
    assert transport.writer.is_closing()


async def test_musicbrainz_user_agent_names_this_integration(hass, config_entry):
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2, patch(
        "custom_components.oppo_player.media_player.musicbrainzngs.set_useragent"
    ) as set_useragent:
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        manifest_path = Path(__file__).parent.parent / "custom_components/oppo_player/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        set_useragent.assert_called_once_with(
            "ha-oppo-player", manifest["version"], manifest["documentation"]
        )
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


async def test_url_only_entry_creates_entities(hass):
    """Entries made by the connection menu store only a URL (no host key); both
    platforms must still set up."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.oppo_player.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN, title="OPPO", data={"url": "socket://192.168.1.50:23", "baudrate": 9600}
    )
    entry.add_to_hass(hass)
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        domains = {state.domain for state in hass.states.async_all()}
        assert {"media_player", "remote"} <= domains
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_device_page_gets_the_model_once_known(hass, config_entry):
    """HA reads device_info only when entities are added, before the player has
    answered QVR; a later state update must still reach the device registry."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.oppo_player.oppoudpsdk import EVENT_DEVICE_STATE_UPDATED

    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        registry = dr.async_get(hass)
        # (async_get_device by identifiers is deprecated in HA 2026.9+.)
        (device,) = dr.async_entries_for_config_entry(registry, config_entry.entry_id)
        assert device.model == "OPPO Player"  # nothing known yet

        controller = config_entry.runtime_data
        controller.device.firmware_version = "UDP20X-54-1127"
        await controller.async_event(EVENT_DEVICE_STATE_UPDATED, controller.device)
        await hass.async_block_till_done()

        device = registry.async_get(device.id)
        assert device.model == "UDP-20x"
        assert device.sw_version == "UDP20X-54-1127"

        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
