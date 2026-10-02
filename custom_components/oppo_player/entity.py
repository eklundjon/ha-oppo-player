"""Base Entity for the Oppo UDP-20x integration."""

import logging

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_CLIENT_CREATED, SIGNAL_CONNECTED, SIGNAL_DISCONNECTED
from .controller import OppoController
from .models import OppoModel, detect_model, display_name
from .oppoudpsdk import OppoDevice

_LOGGER = logging.getLogger(__name__)

class OppoUdpEntity(Entity):
    """
    Base class for Oppo Home Assistant entities
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, host: str, name: str, identifier: str, manager: OppoController):
        self._host = host
        self._name = name
        self._identifier = identifier
        self._manager = manager
        self._attr_unique_id = identifier

    @property
    def device(self) -> OppoDevice:
        return self._manager.device

    @property
    def available(self) -> bool:
        return self._manager.online

    @property
    def host(self):
        """Return the host name of the device."""
        return self._host

    @property
    def oppo_model(self) -> OppoModel:
        """The most specific model known for capability/name resolution.

        Prefers the discovery beacon's exact model (UDP-203/205) over the
        coarser #QVR generation (which can't tell the two apart).
        """
        discovered = getattr(self._manager, "discovered_model", None)
        if isinstance(discovered, OppoModel) and discovered is not OppoModel.UNKNOWN:
            return discovered
        device = getattr(self._manager, "device", None)
        return detect_model(device.firmware_version if device else None)

    @property
    def device_info(self) -> DeviceInfo:
        """Device info dictionary."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self._identifier)},
            name=self._manager.config_entry.title,
            manufacturer="Oppo",
            model=display_name(self.oppo_model),
        )
        firmware = self._manager.device.firmware_version if self._manager.device else None
        if firmware:
            info["sw_version"] = firmware

        return info

    async def async_added_to_hass(self):
        """Handle when an entity is about to be added to Home Assistant."""

        @callback
        def _async_connected(device):
            """Handle that a connection was made to a device."""
            self.async_device_connected(device)
            self.async_write_ha_state()

        @callback
        def _async_disconnected():
            """Handle that a connection to a device was lost."""
            self.async_device_disconnected()
            self.async_write_ha_state()

        @callback
        def _async_client_created(client):
            """Handle when a client is created (due to reconnect)."""
            self.async_client_created(client)
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_CONNECTED}_{self._identifier}", _async_connected
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_CLIENT_CREATED}_{self._identifier}", _async_client_created
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_DISCONNECTED}_{self._identifier}", _async_disconnected
            )
        )

    def async_device_connected(self, device):
        """Handle when connection is made to device."""

    def async_device_disconnected(self):
        """Handle when connection was lost to device."""

    def async_client_created(self, client):
        """Handle when a new client is created (due to reconnections)."""
