"""The Oppo UDP-20x Integration"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .controller import OppoController, entry_url
from .discovery import async_acquire_discovery, async_release_discovery

OppoConfigEntry = ConfigEntry[OppoController]

CONFIG_SCHEMA = cv.deprecated(DOMAIN)

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict):
    return True

async def async_setup_entry(hass: HomeAssistant, entry: OppoConfigEntry):
    """Set up the component."""

    controller = OppoController(hass, entry)
    entry.runtime_data = controller

    # The multicast beacon is IP-only; acquire the shared listener for native
    # socket entries so the controller can resolve its exact model (203 vs 205).
    if entry_url(entry).startswith("socket://"):
        discovery = await async_acquire_discovery(hass)
        await controller.attach_discovery(discovery)

    async def on_hass_stop(event):
        """Stop the connection when Home Assistant stops."""
        await controller.disconnect()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
    )

    async def setup_platforms():
        """Forward platforms first (so entities subscribe), then open the connection."""
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await controller.async_start()

    hass.async_create_task(setup_platforms())

    return True

async def async_unload_entry(hass: HomeAssistant, entry: OppoConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await entry.runtime_data.disconnect()
        if entry_url(entry).startswith("socket://"):
            await async_release_discovery(hass)

    return unload_ok
