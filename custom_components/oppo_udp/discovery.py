"""OPPO player UDP multicast discovery.

UDP-20x players announce themselves on ``239.255.255.251:7624`` every ~10 s with
a small text datagram:

    Notify: OPPO Player Start
    Server Name: OPPO UDP-205
    ...

We join the group and keep a live ``{ip: OppoModel}`` map parsed from the
``Server Name`` line (keyed on the datagram's source address, which is the
player's IP). A running config entry consults it to resolve its player's exact
model — the one thing ``#QVR`` can't tell us (203 vs 205).

This is **IP-only**: a player reached over a serial transport emits nothing here
and falls back to the generic ``UDP_20X`` capabilities. One shared listener
serves every entry (a single socket on the multicast port); it is ref-counted
and torn down when the last entry unloads.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable

from homeassistant.core import HomeAssistant, callback

from .models import OppoModel, model_from_server_name

_LOGGER = logging.getLogger(__name__)

MCAST_GROUP = "239.255.255.251"
MCAST_PORT = 7624
DATA_KEY = "oppo_udp_discovery"


def _field(text: str, key: str) -> str | None:
    """Return the value of a ``Key: value`` line, case-insensitively."""
    prefix = f"{key.lower()}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            return stripped[len(prefix):].strip()
    return None


class _BeaconProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram: Callable[[bytes, tuple], None]) -> None:
        self._on_datagram = on_datagram

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        self._on_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:  # pragma: no cover - transient
        _LOGGER.debug("Discovery socket error: %s", exc)


class OppoDiscovery:
    """Shared multicast listener mapping player IP -> detected model."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._transport: asyncio.DatagramTransport | None = None
        self._models: dict[str, OppoModel] = {}
        self._subs: dict[str, list[Callable[[], None]]] = {}
        self._refcount = 0

    async def async_start(self) -> None:
        """Join the multicast group and begin listening (best-effort).

        Discovery is a convenience layer, so any failure to open the socket
        (port busy, no multicast route, a sandbox that forbids sockets) is
        swallowed: the map stays empty and everything falls back to the generic
        UDP_20X capabilities. It must never break entry setup.
        """
        if self._transport is not None:
            return
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", MCAST_PORT))
            mreq = socket.inet_aton(MCAST_GROUP) + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.setblocking(False)
            self._transport, _ = await self._hass.loop.create_datagram_endpoint(
                lambda: _BeaconProtocol(self._handle), sock=sock
            )
        except Exception as err:  # noqa: BLE001 — discovery is strictly best-effort
            _LOGGER.warning("Oppo discovery unavailable: %s", err)
            if sock is not None:
                sock.close()
            return
        _LOGGER.debug("Oppo discovery listening on %s:%s", MCAST_GROUP, MCAST_PORT)

    async def async_stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._subs.clear()

    @callback
    def _handle(self, data: bytes, addr: tuple) -> None:
        server_name = _field(data.decode(errors="replace"), "Server Name")
        if not server_name or not addr:
            return
        ip = addr[0]
        model = model_from_server_name(server_name)
        if self._models.get(ip) is model:
            return
        self._models[ip] = model
        _LOGGER.debug("Discovered %s at %s (%r)", model, ip, server_name)
        for cb in list(self._subs.get(ip, ())):
            cb()

    def model_for(self, ip: str | None) -> OppoModel | None:
        """The model last heard for ``ip``, or None if not yet seen."""
        return self._models.get(ip) if ip else None

    def subscribe(self, ip: str, callback_: Callable[[], None]) -> Callable[[], None]:
        """Call ``callback_`` when the model for ``ip`` is learned or changes.

        Fires once immediately if the model is already known. Returns an
        unsubscribe callable.
        """
        self._subs.setdefault(ip, []).append(callback_)
        if ip in self._models:
            callback_()

        def _unsub() -> None:
            subs = self._subs.get(ip)
            if subs and callback_ in subs:
                subs.remove(callback_)

        return _unsub


async def async_acquire_discovery(hass: HomeAssistant) -> OppoDiscovery:
    """Get the shared discovery listener, starting it on first use (ref-counted)."""
    disc: OppoDiscovery | None = hass.data.get(DATA_KEY)
    if disc is None:
        disc = OppoDiscovery(hass)
        hass.data[DATA_KEY] = disc
        await disc.async_start()
    disc._refcount += 1
    return disc


async def async_release_discovery(hass: HomeAssistant) -> None:
    """Release one reference; stop and drop the listener when the last goes."""
    disc: OppoDiscovery | None = hass.data.get(DATA_KEY)
    if disc is None:
        return
    disc._refcount -= 1
    if disc._refcount <= 0:
        await disc.async_stop()
        hass.data.pop(DATA_KEY, None)
