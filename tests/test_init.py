"""Setup/unload wiring: the config entry runs on an OppoController."""
from __future__ import annotations

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
