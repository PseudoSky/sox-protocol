# SPDX-License-Identifier: Apache-2.0
"""Tests for ``sox_protocol.tui.mcp_client``.

Uses an in-process echo/stub transport (asyncio pipes via
``asyncio.create_task`` + in-memory queues) instead of a real subprocess.
Covers: start/stop, send/recv/subscribe/list_channels/heartbeat/ack,
JSON-RPC framing, error response handling, and timeout on dead pipe.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sox_protocol.tui.mcp_client import McpStdioClient

# ---------------------------------------------------------------------------
# Helpers — fake bidirectional pipe
# ---------------------------------------------------------------------------


class FakePipe:
    """In-memory bidirectional pipe pair for testing JSON-RPC transports.

    ``client_reader``/``client_writer`` — the side the client reads/writes.
    ``server_reader``/``server_writer`` — the side the stub server reads/writes.
    """

    def __init__(self) -> None:
        # client → server
        c2s_r, c2s_w = self._make_pair()
        # server → client
        s2c_r, s2c_w = self._make_pair()

        self.client_reader: asyncio.StreamReader = s2c_r
        self.client_writer: asyncio.StreamWriter = c2s_w
        self.server_reader: asyncio.StreamReader = c2s_r
        self.server_writer: asyncio.StreamWriter = s2c_w

    @staticmethod
    def _make_pair() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport = _MemoryTransport(reader, protocol)
        writer = asyncio.StreamWriter(transport, protocol, reader, asyncio.get_event_loop())
        return reader, writer


class _MemoryTransport(asyncio.Transport):
    """Minimal in-memory transport that feeds data directly to a StreamReader."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        protocol: asyncio.StreamReaderProtocol,
    ) -> None:
        super().__init__()
        self._reader = reader
        self._closed = False

    def write(self, data: bytes) -> None:  # type: ignore[override]
        if not self._closed:
            self._reader.feed_data(data)

    def is_closing(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True
        self._reader.feed_eof()

    def get_write_buffer_size(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Stub server that responds to JSON-RPC
# ---------------------------------------------------------------------------


async def _stub_server(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tool_results: dict[str, Any],
    stop_event: asyncio.Event,
) -> None:
    """Minimal JSON-RPC stub that handles initialize + tools/call."""
    try:
        while not stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            except TimeoutError:
                continue
            if not line:
                break
            try:
                req = json.loads(line.decode())
            except json.JSONDecodeError:
                continue

            req_id = req.get("id")
            method = req.get("method", "")

            if method == "initialize":
                resp: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "stub", "version": "0.1"},
                    },
                }
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()

            elif method == "tools/call":
                tool_name = req.get("params", {}).get("name", "")
                tool_result = tool_results.get(tool_name, {"ok": True})
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(tool_result)}
                        ]
                    },
                }
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()

            elif method == "notifications/initialized":
                # Notification — no response
                pass

    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def pipe_client() -> AsyncIterator[tuple[McpStdioClient, asyncio.Task[None], asyncio.Event]]:
    """Yield a connected McpStdioClient backed by an in-process stub server."""
    pipe = FakePipe()
    stop_event = asyncio.Event()
    tool_results: dict[str, Any] = {
        "channels__recv": {"drained_at": 1.0, "messages": []},
        "channels__send": {"sent_at": 1.0, "message_id": "m1", "seq": 1, "backpressure": {"queue_depth": 0, "threshold": 1000, "state": "ok"}},
        "channels__subscribe": {"subscribed": ["#general"]},
        "channels__list_channels": {"channels": [], "_sox_protocol": {"server_version": "1.0"}},
        "channels__list_agents": {"agents": []},
        "channels__heartbeat": {"agent_id": "tui-user", "status": "online", "recorded_at": 1.0, "expires_at": 31.0},
        "channels__ack": {"message_id": "m1", "status": "done", "acked_at": 1.0},
        "channels__unsubscribe": {"unsubscribed": [], "pending_cleared": 0},
    }

    server_task = asyncio.create_task(
        _stub_server(
            pipe.server_reader, pipe.server_writer, tool_results, stop_event
        )
    )

    client = McpStdioClient(
        reader=pipe.client_reader,
        writer=pipe.client_writer,
        agent_id="tui-user",
    )
    await client.start()
    try:
        yield client, server_task, stop_event
    finally:
        stop_event.set()
        await client.stop()
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_starts_and_stops(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    assert client._initialized


@pytest.mark.asyncio
async def test_recv_returns_messages(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.recv()
    assert "messages" in result
    assert isinstance(result["messages"], list)


@pytest.mark.asyncio
async def test_recv_with_channel_filter(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.recv(channels=["#general"])
    assert "messages" in result


@pytest.mark.asyncio
async def test_send_returns_message_id(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.send("#general", {"text": "hello"})
    assert result["message_id"] == "m1"


@pytest.mark.asyncio
async def test_send_with_reply_to(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.send("#general", {"text": "reply"}, reply_to="parent-1")
    assert "message_id" in result


@pytest.mark.asyncio
async def test_send_with_correlation_id(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.send("#general", {"text": "msg"}, correlation_id="corr-42")
    assert "message_id" in result


@pytest.mark.asyncio
async def test_subscribe(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.subscribe("#general")
    assert "subscribed" in result


@pytest.mark.asyncio
async def test_list_channels(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.list_channels()
    assert "channels" in result


@pytest.mark.asyncio
async def test_list_agents(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.list_agents()
    assert "agents" in result


@pytest.mark.asyncio
async def test_list_agents_with_filter(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.list_agents(status_filter=["online"])
    assert "agents" in result


@pytest.mark.asyncio
async def test_heartbeat(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.heartbeat("online")
    assert result["status"] == "online"


@pytest.mark.asyncio
async def test_ack(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.ack("m1", "done")
    assert result["status"] == "done"


@pytest.mark.asyncio
async def test_ack_with_reason(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    result = await client.ack("m1", "nack", reason="bad format")
    assert "status" in result


@pytest.mark.asyncio
async def test_start_twice_raises(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    with pytest.raises(RuntimeError, match="already started"):
        await client.start()


@pytest.mark.asyncio
async def test_start_without_reader_or_process_raises() -> None:
    client = McpStdioClient()
    with pytest.raises(RuntimeError, match="requires either"):
        await client.start()


@pytest.mark.asyncio
async def test_stop_cancels_pending_futures(
    pipe_client: tuple[McpStdioClient, asyncio.Task[None], asyncio.Event],
) -> None:
    client, _, _ = pipe_client
    # Create a future that will never be resolved
    fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
    client._pending[99999] = fut
    await client.stop()
    # stop() should have cancelled/cleared pending
    assert len(client._pending) == 0


@pytest.mark.asyncio
async def test_error_response_raises_runtime_error() -> None:
    """Server returning an error JSON-RPC response should raise RuntimeError."""
    pipe = FakePipe()
    stop_event = asyncio.Event()

    async def _error_server(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        while not stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            except TimeoutError:
                continue
            if not line:
                break
            try:
                req = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "stub", "version": "0"}},
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": "tool failed"},
                }
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()

    server_task = asyncio.create_task(
        _error_server(pipe.server_reader, pipe.server_writer)
    )
    client = McpStdioClient(
        reader=pipe.client_reader,
        writer=pipe.client_writer,
    )
    await client.start()
    try:
        with pytest.raises(RuntimeError, match="tool failed"):
            await client.recv()
    finally:
        stop_event.set()
        await client.stop()
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task


@pytest.mark.asyncio
async def test_malformed_json_ignored() -> None:
    """Non-JSON lines from server should be silently ignored."""
    pipe = FakePipe()
    stop_event = asyncio.Event()

    async def _mixed_server(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        while not stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            except TimeoutError:
                continue
            if not line:
                break
            try:
                req = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                # Send garbage first
                writer.write(b"not json\n")
                await writer.drain()
                resp: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "s", "version": "0"}},
                }
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()

    server_task = asyncio.create_task(
        _mixed_server(pipe.server_reader, pipe.server_writer)
    )
    client = McpStdioClient(
        reader=pipe.client_reader,
        writer=pipe.client_writer,
    )
    await client.start()
    assert client._initialized
    stop_event.set()
    await client.stop()
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await server_task


@pytest.mark.asyncio
async def test_result_without_content_block() -> None:
    """Server returning a result without content blocks should return raw dict."""
    pipe = FakePipe()
    stop_event = asyncio.Event()

    async def _bare_result_server(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        while not stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            except TimeoutError:
                continue
            if not line:
                break
            try:
                req = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "s", "version": "0"}},
                }
            elif method == "tools/call":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"direct_key": "direct_value"},
                }
            else:
                continue
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()

    server_task = asyncio.create_task(
        _bare_result_server(pipe.server_reader, pipe.server_writer)
    )
    client = McpStdioClient(
        reader=pipe.client_reader,
        writer=pipe.client_writer,
    )
    await client.start()
    result = await client.recv()
    assert "direct_key" in result
    stop_event.set()
    await client.stop()
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await server_task


@pytest.mark.asyncio
async def test_read_loop_skips_invalid_json_lines() -> None:
    """Non-JSON lines interleaved with valid responses should be skipped (covers continue branch)."""
    pipe = FakePipe()
    stop_event = asyncio.Event()

    async def _interleaved_server(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        # Read initialize, respond with garbage then valid response
        req_count = 0
        while not stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            except TimeoutError:
                continue
            if not line:
                break
            try:
                req = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            req_count += 1
            if method == "initialize":
                resp: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "s", "version": "0"}},
                }
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
            elif method == "tools/call":
                # First send garbage, then send the valid response
                writer.write(b"!!! not json !!!\n")
                await writer.drain()
                # Then send the real response
                result_payload: dict[str, Any] = {"drained_at": 1.0, "messages": []}
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result_payload)}]
                    },
                }
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()

    server_task = asyncio.create_task(
        _interleaved_server(pipe.server_reader, pipe.server_writer)
    )
    client = McpStdioClient(
        reader=pipe.client_reader,
        writer=pipe.client_writer,
    )
    await client.start()
    # This call will see the garbage line first (triggers continue) then the valid response
    result = await client.recv()
    assert "messages" in result
    stop_event.set()
    await client.stop()
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await server_task


@pytest.mark.asyncio
async def test_non_json_text_content_block_returns_raw() -> None:
    """Content block with non-JSON text should return {'raw': text}."""
    pipe = FakePipe()
    stop_event = asyncio.Event()

    async def _non_json_server(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        while not stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            except TimeoutError:
                continue
            if not line:
                break
            try:
                req = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            req_id = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                resp: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "s", "version": "0"}},
                }
            elif method == "tools/call":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": "not valid json <<<"}
                        ]
                    },
                }
            else:
                continue
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()

    server_task = asyncio.create_task(
        _non_json_server(pipe.server_reader, pipe.server_writer)
    )
    client = McpStdioClient(
        reader=pipe.client_reader,
        writer=pipe.client_writer,
    )
    await client.start()
    result = await client.recv()
    assert result.get("raw") == "not valid json <<<"
    stop_event.set()
    await client.stop()
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await server_task


@pytest.mark.asyncio
async def test_client_with_process_mock() -> None:
    """McpStdioClient should call process.spawn() when process is given."""
    pipe = FakePipe()
    stop_event = asyncio.Event()
    tool_results: dict[str, Any] = {
        "channels__recv": {"drained_at": 1.0, "messages": []},
    }
    server_task = asyncio.create_task(
        _stub_server(pipe.server_reader, pipe.server_writer, tool_results, stop_event)
    )

    mock_process = MagicMock()
    mock_process.spawn = AsyncMock()
    mock_process.terminate = AsyncMock()
    mock_process.stdout = pipe.client_reader
    mock_process.stdin = pipe.client_writer

    client = McpStdioClient(process=mock_process, agent_id="tui-user")
    await client.start()
    mock_process.spawn.assert_awaited_once()
    assert client._initialized

    stop_event.set()
    await client.stop()
    mock_process.terminate.assert_awaited_once()
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await server_task
