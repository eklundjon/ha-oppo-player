"""Tests for the Oppo UDP-20x config and reconfigure flows.

The flow is a transport menu (socket / rfc2217 / esphome / serial); each choice
becomes a serialx URL stored as CONF_URL. The device probe is patched out so
these exercise flow logic, not the connection.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.oppo_player.config_flow import _parse_url
from custom_components.oppo_player.const import DEFAULT_BAUDRATE, DOMAIN
from custom_components.oppo_player.controller import entry_url
from custom_components.oppo_player.exceptions import HaCannotConnect
from custom_components.oppo_player.models import OppoModel
from tests.conftest import ENTRY_DATA, MOCK_HOST, MOCK_PORT

_MENU = {"socket", "rfc2217", "esphome", "serial"}


def _patch_probe(error=None):
    """Patch the device probe so no real transport is opened."""
    return patch(
        "custom_components.oppo_player.config_flow._probe", AsyncMock(side_effect=error)
    )


def _patch_setup():
    """A CREATE_ENTRY (or reconfigure reload) would build a real controller and
    open a transport; stub setup so flow tests stay offline."""
    return patch(
        "custom_components.oppo_player.async_setup_entry", AsyncMock(return_value=True)
    )


async def _select(hass, step, *, source="user", entry_id=None):
    """Open the flow, pick a transport from the menu, return the sub-step form."""
    context = {"source": source}
    if entry_id is not None:
        context["entry_id"] = entry_id
    result = await hass.config_entries.flow.async_init(DOMAIN, context=context)
    assert result["type"] == FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


# ── menu ────────────────────────────────────────────────────────────────────

async def test_user_menu_lists_all_transports(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.MENU
    assert set(result["menu_options"]) == _MENU


# ── successful adds ───────────────────────────────────────────────────────────

async def test_socket_success(hass):
    form = await _select(hass, "socket")
    assert form["step_id"] == "socket"
    with _patch_probe(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"host": MOCK_HOST, "port": MOCK_PORT}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_HOST
    assert result["data"] == {
        "url": f"socket://{MOCK_HOST}:{MOCK_PORT}",
        "baudrate": DEFAULT_BAUDRATE,
    }


@pytest.mark.parametrize(
    ("step", "user_input", "expected_url"),
    [
        ("rfc2217", {"host": "gw.local", "port": 5000}, "rfc2217://gw.local:5000"),
        ("esphome", {"host": "proxy.local", "port": 6638}, "esphome://proxy.local:6638"),
    ],
)
async def test_network_scheme_builds_url(hass, step, user_input, expected_url):
    form = await _select(hass, step)
    with _patch_probe(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], user_input
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["url"] == expected_url


async def test_serial_success(hass):
    form = await _select(hass, "serial")
    assert form["step_id"] == "serial"
    with _patch_probe(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"device": "/dev/ttyUSB0", "baudrate": 9600}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "/dev/ttyUSB0"
    assert result["data"] == {"url": "/dev/ttyUSB0", "baudrate": 9600}


# ── validation failures re-show the sub-step form ─────────────────────────────

async def test_socket_cannot_connect(hass):
    form = await _select(hass, "socket")
    with _patch_probe(error=HaCannotConnect()):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"host": MOCK_HOST, "port": MOCK_PORT}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_socket_invalid_host(hass):
    form = await _select(hass, "socket")
    # An invalid host is rejected before any probe is attempted.
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"host": "not a host!", "port": MOCK_PORT}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["host"] == "invalid_host"


async def test_duplicate_connection(hass):
    # A legacy host/port entry resolves to the same socket:// URL, so re-adding
    # it is a duplicate — caught before the probe.
    MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA).add_to_hass(hass)
    form = await _select(hass, "socket")
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"host": MOCK_HOST, "port": MOCK_PORT}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "already_configured"


# ── reconfigure ───────────────────────────────────────────────────────────────

async def test_reconfigure_switches_transport_and_replaces_data(hass, config_entry):
    # config_entry is a legacy host/port entry; move it to a new socket host and
    # confirm the data is replaced with a URL (legacy keys gone).
    new_host = "192.168.1.99"
    form = await _select(
        hass, "socket", source="reconfigure", entry_id=config_entry.entry_id
    )
    assert form["step_id"] == "socket"
    with _patch_probe(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"host": new_host, "port": MOCK_PORT}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["url"] == f"socket://{new_host}:{MOCK_PORT}"
    assert "host" not in config_entry.data


# ── URL helpers / legacy migration ────────────────────────────────────────────

@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("socket://h:23", ("socket", "h", 23, "")),
        ("rfc2217://gw:5000", ("rfc2217", "gw", 5000, "")),
        ("esphome://p:6638", ("esphome", "p", 6638, "")),
        ("/dev/ttyUSB0", ("serial", "", None, "/dev/ttyUSB0")),
    ],
)
def test_parse_url(url, expected):
    assert _parse_url(url) == expected


def test_entry_url_migrates_legacy_host_port():
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    assert entry_url(entry) == f"socket://{MOCK_HOST}:{MOCK_PORT}"


def test_entry_url_prefers_stored_url():
    entry = MockConfigEntry(
        domain=DOMAIN, data={"url": "rfc2217://gw:5000", "baudrate": 9600}
    )
    assert entry_url(entry) == "rfc2217://gw:5000"


# ── discovery (dhcp + beacon) ─────────────────────────────────────────────────

async def test_dhcp_discovery_confirm_creates_socket_entry(hass):
    info = DhcpServiceInfo(
        ip="192.168.1.60", hostname="oppo-203", macaddress="aabbcc112233"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "dhcp"}, data=info
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    with _patch_probe(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    # DHCP doesn't know the variant; title stays generic, URL is native socket.
    assert result["data"]["url"] == "socket://192.168.1.60:23"
    assert result["title"] == "OPPO UDP-20x (192.168.1.60)"


async def test_integration_discovery_titles_by_model(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={"host": "192.168.1.61", "port": MOCK_PORT, "model": OppoModel.UDP_205},
    )
    assert result["step_id"] == "discovery_confirm"
    with _patch_probe(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "OPPO UDP-205"  # beacon knew the exact model
    assert result["data"]["url"] == "socket://192.168.1.61:23"


async def test_discovery_aborts_if_already_configured(hass):
    # A legacy host/port entry resolves to socket://MOCK_HOST:23 — a beacon for
    # the same player must not offer it again.
    MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={"host": MOCK_HOST, "port": MOCK_PORT},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_discovery_cannot_connect_reshows_confirm(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={"host": "192.168.1.62", "port": MOCK_PORT, "model": OppoModel.UDP_203},
    )
    with _patch_probe(error=HaCannotConnect()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["errors"]["base"] == "cannot_connect"


def test_manifest_dhcp_matches_oppo_oui():
    # DHCP discovery hinges on the OPPO Digital OUI (00:22:DE) — guard it so a
    # manifest edit can't silently disable auto-discovery.
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).parent.parent
         / "custom_components" / "oppo_player" / "manifest.json").read_text()
    )
    matchers = {m.get("macaddress") for m in manifest.get("dhcp", [])}
    assert "0022DE*" in matchers
