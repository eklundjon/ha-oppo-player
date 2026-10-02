"""Importing a player configured under the old ``oppo_udp`` domain.

The flow creates the new entry; setup moves the old entry's entities and device
to it (keeping entity IDs, user-set names and areas) and removes the old entry.
The old integration isn't installed in tests, which is the state the import
requires: its folder deleted and Home Assistant restarted.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.oppo_player.const import (
    CONF_LEGACY_ENTRY_ID,
    DOMAIN,
    LEGACY_DOMAIN,
)
from tests.conftest import ENTRY_DATA, MOCK_HOST, MOCK_PORT
from tests.test_connection import FakeTransport
from tests.test_init import _patches

LEGACY_TITLE = "Living Room OPPO"
PLAYER_ID = "media_player.living_room_oppo"
REMOTE_ID = "remote.living_room_oppo_remote"


def _legacy_player(hass, *, title=LEGACY_TITLE, data=ENTRY_DATA, object_id="living_room_oppo"):
    """An old oppo_udp entry with its device and both entities registered, the
    way they're left after the old folder is deleted: entities hold HA's
    placeholder "unavailable" state."""
    legacy = MockConfigEntry(domain=LEGACY_DOMAIN, title=title, data=data)
    legacy.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    area = ar.async_get(hass).async_get_or_create("Theater")
    device = dev_reg.async_get_or_create(
        config_entry_id=legacy.entry_id,
        identifiers={(LEGACY_DOMAIN, legacy.entry_id)},
        manufacturer="Oppo",
        name=title,
    )
    dev_reg.async_update_device(device.id, area_id=area.id)
    for domain, suffix in (("media_player", ""), ("remote", "_remote")):
        entity = ent_reg.async_get_or_create(
            domain,
            LEGACY_DOMAIN,
            legacy.entry_id,
            config_entry=legacy,
            device_id=device.id,
            suggested_object_id=f"{object_id}{suffix}",
        )
        hass.states.async_set(entity.entity_id, "unavailable", {"restored": True})
    ent_reg.async_update_entity(f"media_player.{object_id}", name="Big OPPO")
    return legacy, device, area


def _raise_not_found_repair(hass):
    """The repair HA raises at startup once the old folder is gone."""
    ir.async_create_issue(
        hass,
        "homeassistant",
        f"integration_not_found.{LEGACY_DOMAIN}",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="integration_not_found",
        translation_placeholders={"domain": LEGACY_DOMAIN},
    )


def _not_found_repair(hass):
    return ir.async_get(hass).async_get_issue(
        "homeassistant", f"integration_not_found.{LEGACY_DOMAIN}"
    )


async def _open_import(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.MENU
    assert result["menu_options"][0] == "import_legacy"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_legacy"}
    )


async def test_import_moves_entities_and_device(hass):
    legacy, device, area = _legacy_player(hass)
    _raise_not_found_repair(hass)

    form = await _open_import(hass)
    assert form["type"] == FlowResultType.FORM
    assert form["step_id"] == "import_legacy_confirm"

    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
        await hass.async_block_till_done()
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == LEGACY_TITLE
        entry = result["result"]

        # The old entry is gone and the marker is cleared once setup has run.
        assert hass.config_entries.async_get_entry(legacy.entry_id) is None
        assert entry.data == {
            "url": f"socket://{MOCK_HOST}:{MOCK_PORT}",
            "baudrate": 9600,
        }

        # Same entity IDs, now owned by the new entry, user-set name kept.
        ent_reg = er.async_get(hass)
        for entity_id in (PLAYER_ID, REMOTE_ID):
            reg_entry = ent_reg.async_get(entity_id)
            assert reg_entry.platform == DOMAIN
            assert reg_entry.config_entry_id == entry.entry_id
            assert reg_entry.unique_id == entry.entry_id
            assert reg_entry.device_id == device.id
        assert ent_reg.async_get(PLAYER_ID).name == "Big OPPO"

        # The device kept its id and area and changed hands.
        moved = dr.async_get(hass).async_get(device.id)
        assert moved.identifiers == {(DOMAIN, entry.entry_id)}
        # HA 2026.9+ has one config entry per device; older versions keep a set.
        owner = getattr(moved, "config_entry_id", None)
        assert (owner == entry.entry_id) if owner else (moved.config_entries == {entry.entry_id})
        assert moved.area_id == area.id

        # The live entities took over the moved registry entries: no "_2" copies.
        entity_ids = {state.entity_id for state in hass.states.async_all()}
        assert {PLAYER_ID, REMOTE_ID} <= entity_ids
        assert not any(eid.endswith("_2") for eid in entity_ids)

        # Nothing is left to import, so HA's "not found" repair, whose fix
        # would remove old entries, is cleared.
        assert _not_found_repair(hass) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_import_keeps_a_stored_connection_url(hass):
    _legacy_player(
        hass, data={"url": "rfc2217://gw.local:5000", "baudrate": 9600}
    )
    form = await _open_import(hass)
    with patch(
        "custom_components.oppo_player.async_setup_entry", AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
    assert result["data"]["url"] == "rfc2217://gw.local:5000"
    assert result["data"][CONF_LEGACY_ENTRY_ID]


async def test_import_waits_for_the_old_code_to_be_removed(hass):
    legacy, _, _ = _legacy_player(hass)
    with patch(
        "custom_components.oppo_player.config_flow.async_legacy_code_installed",
        AsyncMock(return_value=True),
    ):
        result = await _open_import(hass)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "legacy_still_installed"
    # Nothing was touched.
    assert hass.config_entries.async_get_entry(legacy.entry_id) is not None
    assert er.async_get(hass).async_get(PLAYER_ID).platform == LEGACY_DOMAIN


async def test_import_asks_which_player_when_there_are_several(hass):
    first, _, _ = _legacy_player(hass)
    second, _, _ = _legacy_player(
        hass,
        title="Bedroom OPPO",
        data={"host": "192.168.1.51", "port": 23},
        object_id="bedroom_oppo",
    )
    form = await _open_import(hass)
    assert form["step_id"] == "import_legacy"
    confirm = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"entry": second.entry_id}
    )
    assert confirm["step_id"] == "import_legacy_confirm"
    assert confirm["description_placeholders"] == {"name": "Bedroom OPPO"}


async def test_discovering_an_old_player_offers_the_import(hass):
    _legacy_player(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "dhcp"},
        data=DhcpServiceInfo(ip=MOCK_HOST, hostname="oppo", macaddress="0022de123456"),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "import_legacy_confirm"


async def test_repair_stays_while_other_players_wait(hass):
    first, _, _ = _legacy_player(hass)
    _legacy_player(
        hass,
        title="Bedroom OPPO",
        data={"host": "192.168.1.51", "port": 23},
        object_id="bedroom_oppo",
    )
    _raise_not_found_repair(hass)
    form = await _open_import(hass)
    form = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"entry": first.entry_id}
    )
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        result = await hass.config_entries.flow.async_configure(form["flow_id"], {})
        await hass.async_block_till_done()
        assert hass.config_entries.async_get_entry(first.entry_id) is None
        assert _not_found_repair(hass) is not None
        assert await hass.config_entries.async_unload(result["result"].entry_id)
        await hass.async_block_till_done()


async def test_discovered_old_player_reminds_while_old_code_installed(hass):
    """After the HACS update the old code is still there; discovery leaves a
    card under Discovered explaining how to move the player."""
    legacy, _, _ = _legacy_player(hass)
    with patch(
        "custom_components.oppo_player.config_flow.async_legacy_code_installed",
        AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "dhcp"},
            data=DhcpServiceInfo(ip=MOCK_HOST, hostname="oppo", macaddress="0022de123456"),
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "import_legacy_remove_old"
        assert result["description_placeholders"] == {"name": LEGACY_TITLE}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "legacy_still_installed"
    # Nothing was touched.
    assert hass.config_entries.async_get_entry(legacy.entry_id) is not None
    assert er.async_get(hass).async_get(PLAYER_ID).platform == LEGACY_DOMAIN


async def test_ignored_old_discoveries_are_not_offered(hass):
    """An ignored oppo_udp discovery holds no settings, so there's nothing to import."""
    MockConfigEntry(
        domain=LEGACY_DOMAIN, source="ignore", unique_id=MOCK_HOST, data={}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.MENU
    assert "import_legacy" not in result["menu_options"]


async def test_setup_without_the_old_entry_just_clears_the_marker(hass):
    """The old entry can vanish between the flow and setup; setup carries on."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=LEGACY_TITLE,
        data={**ENTRY_DATA, CONF_LEGACY_ENTRY_ID: "gone"},
    )
    entry.add_to_hass(hass)
    transport = FakeTransport()
    p1, p2 = _patches(transport)
    with p1, p2:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert CONF_LEGACY_ENTRY_ID not in entry.data
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
