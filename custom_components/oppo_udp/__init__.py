"""The Oppo UDP-20x Integration"""

import logging

from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigEntry,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery_flow

from .const import DEFAULT_PORT, DOMAIN, PLATFORMS
from .controller import OppoController, entry_url
from .discovery import (
    DATA_KEY,
    OppoDiscovery,
    async_acquire_discovery,
    async_release_discovery,
)

OppoConfigEntry = ConfigEntry[OppoController]

CONFIG_SCHEMA = cv.deprecated(DOMAIN)

# Set once the beacon->flow trigger is registered, so it happens a single time
# across all entries and can be torn down with the shared listener.
FLOW_TRIGGER_KEY = "oppo_udp_discovery_flow_trigger"

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
        _ensure_flow_trigger(hass, discovery)

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
            # The trigger lives on the shared listener; drop it once that's gone.
            if hass.data.get(DATA_KEY) is None:
                hass.data.pop(FLOW_TRIGGER_KEY, None)

    return unload_ok


@callback
def _ensure_flow_trigger(hass: HomeAssistant, discovery: OppoDiscovery) -> None:
    """Register a one-time listener that offers newly-seen players for onboarding."""
    if hass.data.get(FLOW_TRIGGER_KEY):
        return

    @callback
    def _on_device(host: str, model) -> None:
        # Already-configured players abort in the flow (unique_id / URL check);
        # this just surfaces unconfigured ones in Settings -> Devices.
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={"host": host, "port": DEFAULT_PORT, "model": model},
        )

    hass.data[FLOW_TRIGGER_KEY] = discovery.add_device_listener(_on_device)
