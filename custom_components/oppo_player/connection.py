"""Transport-agnostic connection to an Oppo UDP-20x player.

The Phase 4 lifecycle layer (see docs/ARCHITECTURE.md): a single serialx-based
transport with one supervised reconnect loop and a push read loop, modeled on
ha-anthemav-serial's AnthemClient. serialx dispatches on the URL scheme, so the
same code path serves IP (``socket://host:23``), native RS-232
(``/dev/ttyUSB0``) and serial-over-IP (``rfc2217://`` / ``esphome://``).

This module is a pure addition — it is not yet wired into the entities (that is
a later Phase 4 step). It deals in raw protocol lines; parsing and device-state
updates are layered on top when it replaces OppoUdpManager. Messages are framed
by carriage return (0x0d), and commands are written the same way.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import serialx

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
RECONNECT_DELAY = 5
# The Oppo caps commands at ~25 bytes and asks callers to "allow time for
# processing" (docs/PROTOCOL.md), so a burst of queued state queries is paced
# out one per interval rather than fired all at once.
QUERY_INTERVAL = 0.1
# Both directions are terminated by CR, not newline.
TERMINATOR = b"\r"


class OppoConnection:
    """Owns the transport, the read loop, and reconnection for one player."""

    def __init__(
        self,
        url: str,
        baudrate: int = 9600,
        on_message: Callable[[str], None] | None = None,
        on_connection_lost: Callable[[], None] | None = None,
    ) -> None:
        # url is any serialx URL: socket://host:23, rfc2217://host:port,
        # esphome://host:port, or a native device path like /dev/ttyUSB0.
        # baudrate only matters for native serial (9600 8N1 for the Oppo);
        # serialx requires it but ignores it for the TCP-based schemes.
        self.url = url
        self.baudrate = baudrate
        self._on_message: Callable[[str], None] = on_message or (lambda _: None)
        self._on_connection_lost = on_connection_lost
        self._on_connection_restored: Callable[[], None] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._listen_task: asyncio.Task | None = None
        self._query_task: asyncio.Task | None = None
        self._query_queue: asyncio.Queue[str] = asyncio.Queue()
        self._running = False
        self.last_command: str = ""
        # Each pending query is a (matcher, future) pair; the first received
        # line for which matcher(line) is True resolves the future.
        self._pending_queries: list[tuple[Callable[[str], bool], asyncio.Future[str]]] = []

    def set_handlers(
        self,
        on_message: Callable[[str], None],
        on_connection_lost: Callable[[], None] | None = None,
        on_connection_restored: Callable[[], None] | None = None,
    ) -> None:
        """Wire the message / connection handlers after construction.

        on_connection_restored fires after the listener reconnects following a
        drop, so callers can re-query state (the device only pushes on change).
        """
        self._on_message = on_message
        if on_connection_lost is not None:
            self._on_connection_lost = on_connection_lost
        if on_connection_restored is not None:
            self._on_connection_restored = on_connection_restored

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        # serialx.open_serial_connection mirrors asyncio.open_connection and
        # returns the same (StreamReader, StreamWriter), dispatching on the URL
        # scheme. The lock serializes a lazy reconnect in send() against the
        # supervisor so only one transport is ever opened.
        async with self._connect_lock:
            if self.connected:
                return
            self._reader, self._writer = await asyncio.wait_for(
                serialx.open_serial_connection(url=self.url, baudrate=self.baudrate),
                timeout=CONNECT_TIMEOUT,
            )
            _LOGGER.debug("Connected to %s", self.url)

    async def start(self) -> None:
        """Connect and begin listening for pushed messages."""
        self._running = True
        await self.connect()
        self._listen_task = asyncio.create_task(self._supervise())
        self._query_task = asyncio.create_task(self._drain_queries())

    async def stop(self) -> None:
        """Disconnect and stop the listener/query tasks."""
        self._running = False
        for task in (self._listen_task, self._query_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError as err:
                # Teardown is best-effort: wait_closed() re-raises whatever
                # closed the transport (e.g. a single-client serial gateway
                # dropping us). Not a failure to act on.
                _LOGGER.debug("Ignoring error closing %s: %s", self.url, err)
            self._writer = None
            self._reader = None

    async def send(self, command: str) -> None:
        """Send a command line (e.g. ``#PLA``). Responses arrive via on_message."""
        async with self._lock:
            if not self.connected:
                await self.connect()
            self._writer.write(command.encode() + TERMINATOR)
            await self._writer.drain()
            self.last_command = command
            _LOGGER.debug("Sent: %s", command)

    async def send_bytes(self, data: bytes) -> None:
        """Write pre-framed command bytes as-is (e.g. an SDK command's encode()).

        Writes under the same lock as send() so command writes never interleave.
        """
        async with self._lock:
            if not self.connected:
                await self.connect()
            self._writer.write(data)
            await self._writer.drain()
            _LOGGER.debug("Sent bytes: %r", data)

    async def query_one(
        self,
        command: str,
        *,
        match: Callable[[str], bool] | None = None,
        prefix: str = "",
        timeout: float = 3.0,
    ) -> str | None:
        """Send a command and return the first response that matches.

        By default a response matches when it starts with ``prefix``. Pass an
        explicit ``match`` predicate for finer control.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        matcher = match if match is not None else (lambda msg: msg.startswith(prefix))
        entry = (matcher, fut)
        self._pending_queries.append(entry)
        try:
            await self.send(command)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except TimeoutError:
            return None
        finally:
            if entry in self._pending_queries:
                self._pending_queries.remove(entry)

    def request_query(self, command: str) -> None:
        """Enqueue a state query to be sent paced (one per QUERY_INTERVAL)."""
        self._query_queue.put_nowait(command)

    async def _drain_queries(self) -> None:
        """Send queued state queries one at a time, paced for the device buffer."""
        while True:
            command = await self._query_queue.get()
            try:
                await self.send(command)
            except Exception as err:  # noqa: BLE001 — one bad query must not stop the pump
                _LOGGER.debug("Paced query %r failed: %s", command, err)
            finally:
                self._query_queue.task_done()
            await asyncio.sleep(QUERY_INTERVAL)

    async def _supervise(self) -> None:
        """Run the read loop, reconnecting after drops until stopped."""
        while self._running:
            await self._listen()  # returns on disconnect (fires on_connection_lost)
            if not self._running:
                break
            await self._reconnect()
            if self._running and self._on_connection_restored:
                self._on_connection_restored()

    async def _reconnect(self) -> None:
        """Retry connect() every RECONNECT_DELAY until it succeeds or we stop."""
        # Tear down the dead transport so `connected` reports False and a fresh
        # connection is actually opened (a half-open socket can still look open).
        if self._writer is not None:
            self._writer.close()
            self._writer = None
            self._reader = None
        while self._running:
            try:
                await self.connect()
                _LOGGER.info("Reconnected to %s", self.url)
                return
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Reconnect to %s failed: %s; retrying in %ds",
                    self.url, err, RECONNECT_DELAY,
                )
                await asyncio.sleep(RECONNECT_DELAY)

    async def _listen(self) -> None:
        """Read CR-terminated lines and dispatch until the connection drops."""
        while self._running:
            try:
                data = await self._reader.readuntil(TERMINATOR)
            except asyncio.IncompleteReadError:
                # Peer closed before sending a terminator: treat as disconnect.
                _LOGGER.warning("Connection closed by %s", self.url)
                break
            except asyncio.CancelledError:
                # Propagate so the supervisor task actually dies when cancelled
                # (e.g. on HA shutdown), rather than looping forever.
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Error reading from %s: %s", self.url, err)
                break

            message = data.decode(errors="replace").strip()
            if not message:
                continue
            _LOGGER.debug("Received: %s", message)
            for matcher, fut in list(self._pending_queries):
                if not fut.done() and matcher(message):
                    fut.set_result(message)
            self._on_message(message)

        if self._running and self._on_connection_lost:
            self._on_connection_lost()
