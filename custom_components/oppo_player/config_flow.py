"""Config flow for the Oppo UDP-20x integration.

The device speaks the same protocol over native IP control and RS-232, so the
flow lets the user pick a transport and then collects only that transport's
details. Each choice is turned into a serialx URL — ``socket://`` for IP,
``rfc2217://`` / ``esphome://`` for a network serial gateway, and a bare
``/dev/tty…`` path for a locally attached adapter — which is what the rest of
the integration connects with (see connection.OppoConnection / entry_url).

Legacy entries that predate the transport menu keep their host/port data and
are migrated to ``socket://host:port`` at read time, so they need no re-add.
"""
from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .connection import OppoConnection
from .const import (
    CONF_BAUDRATE,
    CONF_LEGACY_ENTRY_ID,
    CONF_URL,
    DEFAULT_BAUDRATE,
    DEFAULT_GATEWAY_PORT,
    DEFAULT_PORT,
    DEFAULT_SERIAL_DEVICE,
    DOMAIN,
)
from .controller import entry_url, socket_host
from .exceptions import HaCannotConnect
from .migration import async_legacy_code_installed, legacy_entries
from .models import OppoModel, display_name

_LOGGER = logging.getLogger(__name__)

# serialx URL schemes we build. socket:// is the Oppo's native IP control port;
# rfc2217/esphome reach the RS-232 port through a network serial gateway;
# "serial" is a locally attached device path. Menu option ids == step ids.
_NETWORK_SCHEMES = ("socket", "rfc2217", "esphome")
_MENU_OPTIONS = ["socket", "rfc2217", "esphome", "serial"]


def host_valid(host: str) -> bool:
    """Return True if hostname or IP address is valid."""
    try:
        if ipaddress.ip_address(host).version in (4, 6):
            return True
    except ValueError:
        pass
    if len(host) > 253:
        return False
    allowed = re.compile(r"(?!-)[A-Z\d\-\_]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in host.split("."))


def _network_schema(host: str = "", port: int = DEFAULT_PORT) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): int,
        }
    )


def _serial_schema(
    device: str = DEFAULT_SERIAL_DEVICE, baudrate: int = DEFAULT_BAUDRATE
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_DEVICE, default=device): str,
            vol.Required(CONF_BAUDRATE, default=baudrate): int,
        }
    )


def _parse_url(url: str) -> tuple[str, str, int | None, str]:
    """Split a serialx URL into (kind, host, port, device).

    kind is one of the menu options. Network URLs yield host/port; anything
    without a known scheme is treated as a local serial device path.
    """
    for scheme in _NETWORK_SCHEMES:
        prefix = f"{scheme}://"
        if url.startswith(prefix):
            host, _, port = url[len(prefix):].partition(":")
            return scheme, host, (int(port) if port.isdigit() else None), ""
    return "serial", "", None, url


async def _probe(url: str, baudrate: int) -> None:
    """Open the transport and confirm a live Oppo answers.

    Raises TimeoutError/OSError if the transport can't be opened, or
    HaCannotConnect if it opens but the device never replies (a bare TCP
    gateway may accept the connection with nothing attached). A direct #QVR
    query is answered regardless of the device's verbose-push mode.
    """
    conn = OppoConnection(url, baudrate=baudrate)
    try:
        await conn.start()
        reply = await conn.query_one("#QVR", prefix="@")
    finally:
        await conn.stop()
    if reply is None:
        raise HaCannotConnect


class OppoUdpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Oppo UDP-20x."""

    VERSION = 1

    # Filled in by the discovery steps (dhcp / integration_discovery).
    _discovered_host: str | None = None
    _discovered_port: int = DEFAULT_PORT
    _discovered_model: OppoModel | None = None
    # The old oppo_udp entry being imported (see migration.py).
    _legacy_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a connection type, then collect its details in a sub-step.

        If players are still configured under the old oppo_udp domain, offer to
        import them first, so they keep their entities and history.
        """
        options = list(_MENU_OPTIONS)
        if legacy_entries(self.hass):
            options.insert(0, "import_legacy")
        return self.async_show_menu(step_id="user", menu_options=options)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-pick the connection type — e.g. to move to a serial gateway."""
        return self.async_show_menu(step_id="reconfigure", menu_options=_MENU_OPTIONS)

    # ── Discovery: a confirm step, not the transport menu ──────────────────────
    # A discovered player arrives with its address (and, from the beacon, its
    # model), so it bypasses the transport picker and always uses socket://.

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Player seen on the network (DHCP). Model is filled in later by QVR/beacon."""
        return await self._async_discovered(discovery_info.ip, DEFAULT_PORT, None)

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Player heard on the multicast beacon; carries the exact model."""
        return await self._async_discovered(
            discovery_info["host"],
            discovery_info.get("port", DEFAULT_PORT),
            discovery_info.get("model"),
        )

    async def _async_discovered(
        self, host: str, port: int, model: OppoModel | None
    ) -> ConfigFlowResult:
        # No stable hardware id exists in the protocol, so key discovery on the
        # IP (consistent with how entries are keyed) — this also dedups repeated
        # beacon/DHCP announcements while a flow is in progress.
        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()
        # A player still configured under the old domain is imported, not added
        # a second time.
        for legacy in legacy_entries(self.hass):
            if socket_host(entry_url(legacy)) == host:
                self._legacy_entry = legacy
                self.context["title_placeholders"] = {"name": legacy.title}
                return await self.async_step_import_legacy_confirm()
        if self._url_configured(f"socket://{host}:{port}"):
            return self.async_abort(reason="already_configured")
        self._discovered_host = host
        self._discovered_port = port
        self._discovered_model = model if isinstance(model, OppoModel) else None
        self.context["title_placeholders"] = {"name": self._discovered_title()}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered player, then probe + create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = f"socket://{self._discovered_host}:{self._discovered_port}"
            result = await self._async_validate_and_finish(
                url, DEFAULT_BAUDRATE, errors, title=self._discovered_title()
            )
            if result is not None:
                return result
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            errors=errors,
            description_placeholders={
                "name": self._discovered_title(),
                "host": self._discovered_host,
            },
        )

    # ── Import from the old oppo_udp domain ────────────────────────────────────

    async def async_step_import_legacy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which old oppo_udp player to import (skipped if there's one)."""
        entries = {e.entry_id: e for e in legacy_entries(self.hass)}
        if not entries:
            return self.async_abort(reason="no_legacy_entries")
        if user_input is not None:
            self._legacy_entry = entries[user_input["entry"]]
            return await self.async_step_import_legacy_confirm()
        if len(entries) == 1:
            self._legacy_entry = next(iter(entries.values()))
            return await self.async_step_import_legacy_confirm()
        return self.async_show_form(
            step_id="import_legacy",
            data_schema=vol.Schema(
                {vol.Required("entry"): vol.In({k: e.title for k, e in entries.items()})}
            ),
        )

    async def async_step_import_legacy_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm importing the chosen player, then create its new entry."""
        legacy = self._legacy_entry
        assert legacy is not None
        # Its entities can only be moved once the old code is gone.
        if await async_legacy_code_installed(self.hass):
            if self.source == SOURCE_USER:
                return self.async_abort(reason="legacy_still_installed")
            # Discovered: stay under Discovered as a reminder that the player
            # is still on the old code (HACS only updates oppo_player now).
            return await self.async_step_import_legacy_remove_old()
        if user_input is None:
            self._set_confirm_only()
            return self.async_show_form(
                step_id="import_legacy_confirm",
                description_placeholders={"name": legacy.title},
            )

        url = entry_url(legacy)
        if legacy.unique_id:
            await self.async_set_unique_id(legacy.unique_id, raise_on_progress=False)
            self._abort_if_unique_id_configured()
        if self._url_configured(url):
            return self.async_abort(reason="already_configured")
        # No probe: the player may be off, and it was working under the old
        # domain. Setup moves the registry entries (migration.py).
        return self.async_create_entry(
            title=legacy.title,
            data={
                CONF_URL: url,
                CONF_BAUDRATE: legacy.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                CONF_LEGACY_ENTRY_ID: legacy.entry_id,
            },
        )

    async def async_step_import_legacy_remove_old(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain the delete-and-restart a discovered old player needs first.

        Nothing can change until Home Assistant restarts, and the player is
        discovered again then, so confirming just closes the card.
        """
        if user_input is not None:
            return self.async_abort(reason="legacy_still_installed")
        assert self._legacy_entry is not None
        self._set_confirm_only()
        return self.async_show_form(
            step_id="import_legacy_remove_old",
            description_placeholders={"name": self._legacy_entry.title},
        )

    def _discovered_title(self) -> str:
        """Friendly entry title for a discovered player (uses the model if known)."""
        if self._discovered_model and self._discovered_model is not OppoModel.UNKNOWN:
            return f"OPPO {display_name(self._discovered_model)}"
        return f"OPPO UDP-20x ({self._discovered_host})"

    # ── Per-scheme connection steps (shared by add + reconfigure) ──────────────

    async def async_step_socket(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_network_step("socket", user_input)

    async def async_step_rfc2217(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_network_step("rfc2217", user_input)

    async def async_step_esphome(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_network_step("esphome", user_input)

    async def _async_network_step(
        self, scheme: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host, port = user_input[CONF_HOST], user_input[CONF_PORT]
            if not host_valid(host):
                errors[CONF_HOST] = "invalid_host"
            else:
                url = f"{scheme}://{host}:{port}"
                result = await self._async_validate_and_finish(
                    url, DEFAULT_BAUDRATE, errors
                )
                if result is not None:
                    return result
        else:
            host, port = self._network_defaults(scheme)
        return self.async_show_form(
            step_id=scheme, data_schema=_network_schema(host, port), errors=errors
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device, baudrate = user_input[CONF_DEVICE], user_input[CONF_BAUDRATE]
            result = await self._async_validate_and_finish(device, baudrate, errors)
            if result is not None:
                return result
        else:
            device, baudrate = self._serial_defaults()
        return self.async_show_form(
            step_id="serial",
            data_schema=_serial_schema(device, baudrate),
            errors=errors,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _reconfigure_entry(self) -> ConfigEntry | None:
        if self.source != SOURCE_RECONFIGURE:
            return None
        return self._get_reconfigure_entry()

    def _network_defaults(self, scheme: str) -> tuple[str, int]:
        default_port = DEFAULT_PORT if scheme == "socket" else DEFAULT_GATEWAY_PORT
        if entry := self._reconfigure_entry():
            kind, host, port, _ = _parse_url(entry_url(entry))
            if kind == scheme:
                return host, port or default_port
        return "", default_port

    def _serial_defaults(self) -> tuple[str, int]:
        if entry := self._reconfigure_entry():
            kind, _, _, device = _parse_url(entry_url(entry))
            if kind == "serial":
                return device, entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
        return DEFAULT_SERIAL_DEVICE, DEFAULT_BAUDRATE

    def _url_configured(self, url: str, ignore_entry_id: str | None = None) -> bool:
        """Return True if another entry already resolves to this URL."""
        return any(
            entry_url(entry) == url
            for entry in self._async_current_entries()
            if entry.entry_id != ignore_entry_id
        )

    async def _async_validate_and_finish(
        self, url: str, baudrate: int, errors: dict[str, str], *, title: str | None = None
    ) -> ConfigFlowResult | None:
        """Dedup + probe; on success create/update the entry, else fill errors.

        ``title`` overrides the default host-derived title (discovery passes a
        friendly model-based name).
        """
        entry = self._reconfigure_entry()
        if self._url_configured(url, entry.entry_id if entry else None):
            errors["base"] = "already_configured"
            return None
        try:
            await _probe(url, baudrate)
        except (TimeoutError, OSError, HaCannotConnect) as err:
            _LOGGER.debug("Probe of %s failed: %s", url, err)
            errors["base"] = "cannot_connect"
            return None
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error probing %s", url)
            errors["base"] = "unknown"
            return None

        data = {CONF_URL: url, CONF_BAUDRATE: baudrate}
        resolved_title = title or self._title_for(url)
        if entry:
            return self.async_update_reload_and_abort(
                entry, title=resolved_title, data=data
            )
        return self.async_create_entry(title=resolved_title, data=data)

    @staticmethod
    def _title_for(url: str) -> str:
        _, host, _, device = _parse_url(url)
        return host or device or url
