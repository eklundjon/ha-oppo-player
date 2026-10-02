"""Import players configured under the integration's old domain, ``oppo_udp``.

The integration moved from ``oppo_udp`` (shared with upstream simbaja/ha_oppoudp
and other forks) to ``oppo_player``. HACS installs the new folder alongside the
old one and never removes the old one, so nothing moves on its own: the user
deletes ``custom_components/oppo_udp``, restarts, and imports the player from
this integration's config flow.

The flow only creates the new entry, carrying the old entry's id under
``CONF_LEGACY_ENTRY_ID``. The registry work happens in ``async_setup_entry``,
before any platform is forwarded, so the new entities find their moved registry
entries instead of being created fresh with "_2" entity IDs.
"""
from __future__ import annotations

import inspect
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_RESTORED
from homeassistant.core import DOMAIN as HA_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import IntegrationNotFound, async_get_integration

from .const import CONF_LEGACY_ENTRY_ID, DOMAIN, LEGACY_DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_legacy_code_installed(hass: HomeAssistant) -> bool:
    """Return True while the old integration's code is still loadable.

    Its entities must not be loaded when they're moved, so the import waits
    until the folder is gone and Home Assistant has restarted.
    """
    try:
        await async_get_integration(hass, LEGACY_DOMAIN)
    except IntegrationNotFound:
        return False
    return True


def legacy_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Old ``oppo_udp`` entries that are still waiting to be imported.

    Ignored discoveries are left out: they hold no settings to import.
    """
    return hass.config_entries.async_entries(LEGACY_DOMAIN, include_ignore=False)


async def async_migrate_legacy_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move the old entry's entities and device to ``entry``, then remove it.

    Entity IDs, names, icons, areas and the device's area are kept, and with the
    entity IDs unchanged the recorder's history and statistics carry on.
    """
    legacy_id = entry.data[CONF_LEGACY_ENTRY_ID]
    legacy = hass.config_entries.async_get_entry(legacy_id)
    if legacy is not None and legacy.domain == LEGACY_DOMAIN:
        _move_registry_entries(hass, legacy, entry)
        await hass.config_entries.async_remove(legacy.entry_id)
        _LOGGER.info("Imported %s from %s", legacy.title, LEGACY_DOMAIN)
    else:
        # Already gone, e.g. the user removed it between the flow and setup.
        _LOGGER.debug("Old %s entry %s not found; nothing to move", LEGACY_DOMAIN, legacy_id)

    data = {k: v for k, v in entry.data.items() if k != CONF_LEGACY_ENTRY_ID}
    hass.config_entries.async_update_entry(entry, data=data)

    # With the old folder gone, HA raised an "Integration oppo_udp not found"
    # repair at startup. It offers to remove the old entries, which would
    # delete what's left to import, and it stays until the next restart, so
    # clear it once nothing is left.
    if not hass.config_entries.async_entries(LEGACY_DOMAIN):
        ir.async_delete_issue(hass, HA_DOMAIN, f"integration_not_found.{LEGACY_DOMAIN}")


def _move_registry_entries(
    hass: HomeAssistant, legacy: ConfigEntry, entry: ConfigEntry
) -> None:
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, legacy.entry_id)
    # HA 2026.9 moved to one config entry per device and a direct "move"
    # (new_config_entry_id); older versions only have add/remove.
    can_move = "new_config_entry_id" in inspect.signature(
        dev_reg.async_update_device
    ).parameters

    # Moving a device off a config entry (or removing the entry from it)
    # deletes that entry's entities on it, so the entities go first. Devices
    # keep their id, and so their area and user-set name.
    if not can_move:
        # The new entry is added before the old one is removed, so the device is
        # never left without one (which deletes it).
        for device in devices:
            dev_reg.async_update_device(
                device.id,
                new_identifiers={_map_identifier(i, legacy, entry) for i in device.identifiers},
                add_config_entry_id=entry.entry_id,
            )

    for reg_entry in er.async_entries_for_config_entry(ent_reg, legacy.entry_id):
        # With the old code gone, HA holds a placeholder "unavailable" state for
        # each entity, and the registry refuses to move an entity with a state.
        state = hass.states.get(reg_entry.entity_id)
        if state is not None and state.attributes.get(ATTR_RESTORED):
            hass.states.async_remove(reg_entry.entity_id)
        # Entities are keyed on their config entry's id, so the key follows it.
        unique_id = (
            entry.entry_id if reg_entry.unique_id == legacy.entry_id else reg_entry.unique_id
        )
        ent_reg.async_update_entity_platform(
            reg_entry.entity_id,
            DOMAIN,
            new_config_entry_id=entry.entry_id,
            new_unique_id=unique_id,
        )

    for device in devices:
        if can_move:
            dev_reg.async_update_device(
                device.id,
                new_identifiers={_map_identifier(i, legacy, entry) for i in device.identifiers},
                new_config_entry_id=entry.entry_id,
            )
        else:
            # A separate call from the add above: HA 2025.x tracks config
            # subentries per device, and one call doing both leaves that
            # bookkeeping incomplete.
            dev_reg.async_update_device(device.id, remove_config_entry_id=legacy.entry_id)


def _map_identifier(
    identifier: tuple[str, str], legacy: ConfigEntry, entry: ConfigEntry
) -> tuple[str, str]:
    domain, value = identifier
    if domain != LEGACY_DOMAIN:
        return identifier
    return (DOMAIN, entry.entry_id if value == legacy.entry_id else value)
