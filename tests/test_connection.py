"""Tests for OppoConnection using a fake transport (no real socket)."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from custom_components.oppo_player.connection import OppoConnection

MOCK_URL = "socket://192.168.1.50:23"


# ── fake transport ─────────────────────────────────────────────────────────────

class FakeWriter:
    def __init__(self):
        self.buffer = bytearray()
        self._closing = False

    def write(self, data):
        self.buffer += data

    async def drain(self):
        pass

    def is_closing(self):
        return self._closing

    def close(self):
        self._closing = True

    async def wait_closed(self):
        pass


class FakeReader:
    def __init__(self):
        self._q: asyncio.Queue = asyncio.Queue()

    def feed_line(self, text: str):
        self._q.put_nowait(text.encode() + b"\r")

    def feed_eof(self):
        self._q.put_nowait(None)

    async def readuntil(self, sep=b"\r"):
        item = await self._q.get()
        if item is None:
            raise asyncio.IncompleteReadError(partial=b"", expected=None)
        return item


class FakeTransport:
    """Hands out a fresh reader/writer per connect so reconnection works."""

    def __init__(self):
        self.pairs: list[tuple[FakeReader, FakeWriter]] = []
        self.connect_count = 0

    async def open(self, url=None, baudrate=None):
        self.connect_count += 1
        pair = (FakeReader(), FakeWriter())
        self.pairs.append(pair)
        return pair

    @property
    def reader(self) -> FakeReader:
        return self.pairs[-1][0]

    @property
    def writer(self) -> FakeWriter:
        return self.pairs[-1][1]


@pytest.fixture
def transport():
    return FakeTransport()


def _patch(transport):
    return patch(
        "custom_components.oppo_player.connection.serialx.open_serial_connection",
        side_effect=transport.open,
    )


async def _wait_for(cond, timeout=1.0):
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.01)


# ── tests ──────────────────────────────────────────────────────────────────────

async def test_start_connects_and_dispatches_messages(transport):
    got: list[str] = []
    conn = OppoConnection(MOCK_URL, on_message=got.append)
    with _patch(transport):
        await conn.start()
        assert transport.connect_count == 1
        transport.reader.feed_line("@OK ON")
        await _wait_for(lambda: got == ["@OK ON"])
        await conn.stop()


async def test_send_frames_command_with_cr(transport):
    conn = OppoConnection(MOCK_URL)
    with _patch(transport):
        await conn.start()
        await conn.send("#PLA")
        await conn.stop()
    assert transport.writer.buffer == b"#PLA\r"


async def test_query_one_returns_matching_response(transport):
    conn = OppoConnection(MOCK_URL)
    with _patch(transport):
        await conn.start()

        async def respond():
            await asyncio.sleep(0)
            transport.reader.feed_line("@QPW OK ON")

        asyncio.create_task(respond())
        result = await conn.query_one("#QPW", prefix="@QPW", timeout=1)
        await conn.stop()
    assert result == "@QPW OK ON"


async def test_query_one_times_out_to_none(transport):
    conn = OppoConnection(MOCK_URL)
    with _patch(transport):
        await conn.start()
        result = await conn.query_one("#QPW", prefix="@NOMATCH", timeout=0.1)
        await conn.stop()
    assert result is None


async def test_reconnect_after_drop_fires_callbacks(transport):
    lost = asyncio.Event()
    restored = asyncio.Event()
    conn = OppoConnection(MOCK_URL)
    conn.set_handlers(
        lambda _: None,
        on_connection_lost=lost.set,
        on_connection_restored=restored.set,
    )
    with (
        patch("custom_components.oppo_player.connection.RECONNECT_DELAY", 0),
        _patch(transport),
    ):
        await conn.start()
        transport.reader.feed_eof()  # drop the live connection
        await asyncio.wait_for(lost.wait(), 1)
        await asyncio.wait_for(restored.wait(), 1)
        await conn.stop()
    assert transport.connect_count == 2  # reopened after the drop


async def test_request_query_is_paced(transport):
    conn = OppoConnection(MOCK_URL)
    with (
        patch("custom_components.oppo_player.connection.QUERY_INTERVAL", 0),
        _patch(transport),
    ):
        await conn.start()
        conn.request_query("#QPW")
        conn.request_query("#QVL")
        await _wait_for(lambda: transport.writer.buffer == b"#QPW\r#QVL\r")
        await conn.stop()


async def test_stop_cancels_tasks(transport):
    conn = OppoConnection(MOCK_URL)
    with _patch(transport):
        await conn.start()
        await conn.stop()
    assert conn._listen_task.done()
    assert conn._query_task.done()
    assert not conn.connected
