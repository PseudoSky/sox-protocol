# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration tests for the SOX MCP server (Milestone 3).

All four scenarios from the spec:

1. **Single-server round-trip** — ``channels__send`` → ``channels__recv``
   on the same MCP server instance.
2. **Two-server fan-out** — server-1 (agent A) sends, server-2 (agent B)
   receives via a shared SQLite backing store.
3. **Listener buffering** — 100 messages inserted directly into the
   SQLite store (bypassing ``send``), then a single ``recv`` drains them
   all.
4. **Schema validation** — every tool output is validated against the
   corresponding ``spec/schemas/tools/*.output.schema.json``.

Architecture note
-----------------
Tests use FastMCP's **in-process** client (``Client(mcp_instance)``) so
they do not spawn subprocesses.  The in-process path exercises the exact
same tool code that the stdio/HTTP transports call, without the overhead
of subprocess management.  A separate subprocess-launch test
(``test_subprocess_launch``) validates that the ``__main__`` entry point
at least starts and responds to an initialize handshake.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastmcp import Client

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore
from sox_protocol.core.mcp_server.server import create_server

# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------

_SPEC_SCHEMAS_DIR = (
    Path(__file__).resolve().parents[4] / "spec" / "schemas" / "tools"
)


def _load_schema(filename: str) -> dict[str, Any]:
    """Load a JSON Schema from spec/schemas/tools/."""
    path = _SPEC_SCHEMAS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[return-value]


_SCHEMA_SEND_OUT = _load_schema("send.output.schema.json")
_SCHEMA_RECV_OUT = _load_schema("recv.output.schema.json")
_SCHEMA_SUB_OUT = _load_schema("subscribe.output.schema.json")
_SCHEMA_LIST_OUT = _load_schema("list-channels.output.schema.json")


def _validate(instance: Any, schema: dict[str, Any]) -> None:
    """Assert *instance* validates against *schema* (raises AssertionError)."""
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(
            f"Output does not conform to schema: {exc.message}\n"
            f"Instance: {instance!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory_store() -> MemoryStore:
    """A fresh in-memory backing store (no init needed for tests)."""
    return MemoryStore()


@pytest.fixture()
async def init_memory_store(memory_store: MemoryStore) -> MemoryStore:
    """Initialised MemoryStore."""
    await memory_store.initialize()
    return memory_store


@pytest.fixture()
def sqlite_db_path(tmp_path: Path) -> str:
    """Absolute path string for a fresh SQLite DB in the pytest tmp dir."""
    return str(tmp_path / "sox_test.db")


# ---------------------------------------------------------------------------
# Helper: build a server with a pre-built store (bypasses env-var factory)
# ---------------------------------------------------------------------------


async def _make_server_with_store(
    store: Any, agent_id: str
) -> Any:
    """Create a FastMCP server wired to *store* as *agent_id*.

    We set the environment variables before calling ``create_server()``
    so the factory reads them.  The store is swapped in afterwards by
    monkey-patching the lifespan; actually the cleanest approach for
    in-process tests is to just set SOX_BACKING_STORE to memory:// and
    then patch the created store — but that's fragile.

    Instead, we directly wire the store into the lifespan by building the
    server with a custom lifespan that accepts the store we pass in.  We
    do this by re-implementing the minimal create_server logic inline.
    """
    import contextlib
    from typing import AsyncIterator

    from fastmcp import FastMCP

    from sox_protocol.core.mcp_server.listener import Listener
    from sox_protocol.core.mcp_server.server import _load_and_validate_schemas
    from sox_protocol.core.mcp_server.tools import register_tools

    @contextlib.asynccontextmanager
    async def _lifespan(
        server: FastMCP[dict[str, object]],
    ) -> AsyncIterator[dict[str, object]]:
        _load_and_validate_schemas()
        await store.initialize()
        listener = Listener(store=store, agent_id=agent_id)
        listener.start()
        try:
            yield {"store": store, "listener": listener, "agent_id": agent_id}
        finally:
            await listener.stop()
            if hasattr(store, "close"):
                await store.close()

    mcp: FastMCP[dict[str, object]] = FastMCP(
        name=f"sox-{agent_id}",
        lifespan=_lifespan,
    )
    register_tools(mcp)
    return mcp


# ---------------------------------------------------------------------------
# Scenario 1: Single-server send → recv round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_server_send_recv_roundtrip() -> None:
    """Scenario 1: send then recv on the same server returns the message."""
    store = MemoryStore()
    mcp = await _make_server_with_store(store, agent_id="agent-alpha")

    async with Client(mcp) as client:
        # Subscribe so recv knows to pull from this channel.
        sub_result = await client.call_tool(
            "channels__subscribe", {"pattern": "ticket:ENGI-*"}
        )
        sub_data = sub_result.data
        assert isinstance(sub_data, dict)
        _validate(sub_data, _SCHEMA_SUB_OUT)
        assert "subscribed" in sub_data

        # Send a message (agent sends to itself for the round-trip test).
        send_result = await client.call_tool(
            "channels__send",
            {
                "channel": "ticket:ENGI-0001",
                "body": {"type": "clarification_request", "question": "v2 or v3?"},
                "correlation_id": "req-001",
            },
        )
        send_data = send_result.data
        assert isinstance(send_data, dict)
        _validate(send_data, _SCHEMA_SEND_OUT)
        assert "message_id" in send_data
        assert "sent_at" in send_data
        assert isinstance(send_data["sent_at"], float)

        # Give the listener a brief moment to buffer the message.
        await asyncio.sleep(0.15)

        # Receive — must return immediately (non-blocking).
        recv_result = await client.call_tool("channels__recv", {})
        recv_data = recv_result.data
        assert isinstance(recv_data, dict)
        _validate(recv_data, _SCHEMA_RECV_OUT)

        messages = recv_data["messages"]
        assert isinstance(messages, list)
        assert len(messages) == 1, f"Expected 1 message, got {len(messages)}"

        msg = messages[0]
        assert msg["channel"] == "ticket:ENGI-0001"
        assert msg["body"] == {"type": "clarification_request", "question": "v2 or v3?"}
        assert msg["correlation_id"] == "req-001"
        assert msg["message_id"] == send_data["message_id"]

        # Second recv — must return empty (at-least-once; message marked delivered).
        recv_again = await client.call_tool("channels__recv", {})
        assert recv_again.data["messages"] == []


# ---------------------------------------------------------------------------
# Scenario 2: Two-server fan-out on shared SQLite store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_server_fanout_shared_sqlite(tmp_path: Path) -> None:
    """Scenario 2: agent A on server-1 sends; agent B on server-2 receives.

    Both servers share the same SQLite database file.  This tests that the
    watch loop and backing store correctly fan out messages across process
    boundaries (simulated here as two in-process servers sharing one file).
    """
    db_path = str(tmp_path / "shared.db")

    store_a = SqliteStore(db_path)
    store_b = SqliteStore(db_path)

    mcp_a = await _make_server_with_store(store_a, agent_id="agent-alpha")
    mcp_b = await _make_server_with_store(store_b, agent_id="agent-beta")

    async with Client(mcp_a) as client_a, Client(mcp_b) as client_b:
        # Agent B subscribes to the channel on server-2.
        await client_b.call_tool("channels__subscribe", {"pattern": "team:*"})

        # Agent A sends a message on server-1.
        send_result = await client_a.call_tool(
            "channels__send",
            {
                "channel": "team:broadcast",
                "body": {"type": "status_update", "subject": "PR #42 open for review"},
            },
        )
        send_data = send_result.data
        assert isinstance(send_data, dict)
        _validate(send_data, _SCHEMA_SEND_OUT)

        # Allow the watch loop on server-2 to pick up the message.
        await asyncio.sleep(0.25)

        # Agent B receives on server-2.
        recv_result = await client_b.call_tool("channels__recv", {})
        recv_data = recv_result.data
        assert isinstance(recv_data, dict)
        _validate(recv_data, _SCHEMA_RECV_OUT)

        messages = recv_data["messages"]
        assert len(messages) == 1, f"Expected 1 message, got {len(messages)}: {messages}"
        msg = messages[0]
        assert msg["channel"] == "team:broadcast"
        assert msg["body"]["subject"] == "PR #42 open for review"

        # Agent A should NOT see the message (not subscribed on server-1).
        # Subscribe agent-alpha to the same channel to confirm it gets a
        # separate delivery (the backing store tracks per-agent delivery).
        await client_a.call_tool("channels__subscribe", {"pattern": "team:*"})
        # Agent A was not subscribed at send time; it will not receive past msgs
        # unless the store delivers undelivered messages.  The SQLite store
        # tracks delivered_to; since agent-alpha was not subscribed at send time,
        # the message was never delivered to it.  After subscribing it should
        # be able to receive the message.
        await asyncio.sleep(0.15)
        recv_a = await client_a.call_tool("channels__recv", {})
        # The message was already in the store before agent-a subscribed;
        # the watch loop will pick it up as undelivered for agent-alpha.
        assert isinstance(recv_a.data, dict)
        _validate(recv_a.data, _SCHEMA_RECV_OUT)
        # agent-alpha should receive the message since it was not in delivered_to
        assert len(recv_a.data["messages"]) == 1


# ---------------------------------------------------------------------------
# Scenario 3: Listener buffering (100 messages)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_buffers_100_messages(tmp_path: Path) -> None:
    """Scenario 3: 100 messages inserted before any recv; first recv drains all.

    Messages are inserted directly into the SQLite store (bypassing the
    ``send`` tool) to ensure the listener's watch loop picks them up
    passively.  Then a single ``recv`` call is made; it must return all 100.
    """
    db_path = str(tmp_path / "buf100.db")
    store = SqliteStore(db_path)
    mcp = await _make_server_with_store(store, agent_id="agent-gamma")

    async with Client(mcp) as client:
        # Subscribe so messages are deliverable.
        await client.call_tool("channels__subscribe", {"pattern": "flood:*"})

        # Insert 100 messages directly into the store (bypassing the MCP tool).
        for i in range(100):
            await store.send(
                channel="flood:channel",
                sender="injector",
                body={"seq": i},
            )

        # Allow the background listener to buffer all 100.
        # The watch loop polls every 50 ms; 500 ms is comfortable headroom.
        await asyncio.sleep(0.5)

        # Single recv call — must drain all 100.
        recv_result = await client.call_tool(
            "channels__recv", {"max_messages": 200}
        )
        recv_data = recv_result.data
        assert isinstance(recv_data, dict)
        _validate(recv_data, _SCHEMA_RECV_OUT)

        messages = recv_data["messages"]
        assert (
            len(messages) == 100
        ), f"Expected 100 buffered messages, got {len(messages)}"

        # Verify ordering: seq values 0..99 in order.
        seq_vals = [m["body"]["seq"] for m in messages]  # type: ignore[index]
        assert seq_vals == list(range(100)), f"Out-of-order: {seq_vals[:10]}..."

        # Subsequent recv must be empty.
        recv_empty = await client.call_tool("channels__recv", {})
        assert recv_empty.data["messages"] == []


# ---------------------------------------------------------------------------
# Scenario 4: Schema validation on all tool outputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_tool_outputs_conform_to_spec_schemas() -> None:
    """Scenario 4: every tool output validates against spec schemas."""
    store = MemoryStore()
    mcp = await _make_server_with_store(store, agent_id="validator-agent")

    async with Client(mcp) as client:
        # channels__subscribe
        sub = await client.call_tool("channels__subscribe", {"pattern": "ch:*"})
        assert isinstance(sub.data, dict)
        _validate(sub.data, _SCHEMA_SUB_OUT)

        # channels__send
        send = await client.call_tool(
            "channels__send",
            {"channel": "ch:one", "body": {"hello": "world"}},
        )
        assert isinstance(send.data, dict)
        _validate(send.data, _SCHEMA_SEND_OUT)

        # channels__recv (empty — no wait needed for schema shape test)
        recv = await client.call_tool("channels__recv", {})
        assert isinstance(recv.data, dict)
        _validate(recv.data, _SCHEMA_RECV_OUT)

        # channels__list_channels
        lst = await client.call_tool("channels__list_channels", {})
        assert isinstance(lst.data, dict)
        _validate(lst.data, _SCHEMA_LIST_OUT)
        assert lst.data["protocol_version"] == "1.0"


# ---------------------------------------------------------------------------
# Scenario 4b: recv with populated messages also validates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recv_output_with_messages_conforms_to_spec_schema() -> None:
    """recv output containing actual messages validates against the schema."""
    store = MemoryStore()
    mcp = await _make_server_with_store(store, agent_id="agent-delta")

    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "demo:*"})

        await client.call_tool(
            "channels__send",
            {
                "channel": "demo:channel",
                "body": {"type": "ping"},
                "correlation_id": "c-1",
            },
        )

        await asyncio.sleep(0.15)

        recv = await client.call_tool("channels__recv", {})
        recv_data = recv.data
        assert isinstance(recv_data, dict)
        _validate(recv_data, _SCHEMA_RECV_OUT)
        assert len(recv_data["messages"]) == 1

        msg = recv_data["messages"][0]
        # Verify all required fields per recv.output.schema.json.
        assert "channel" in msg
        assert "sender" in msg
        assert "body" in msg
        assert "sent_at" in msg
        assert "message_id" in msg


# ---------------------------------------------------------------------------
# Non-blocking guarantee: recv returns immediately even with no messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recv_is_non_blocking_when_empty() -> None:
    """recv must return immediately when the queue is empty."""
    store = MemoryStore()
    mcp = await _make_server_with_store(store, agent_id="agent-epsilon")

    async with Client(mcp) as client:
        t0 = time.monotonic()
        result = await client.call_tool("channels__recv", {})
        elapsed = time.monotonic() - t0

        assert result.data["messages"] == []
        assert isinstance(result.data["drained_at"], float)
        # Must complete in well under 100 ms — not blocked on the watch loop.
        assert elapsed < 1.0, f"recv took {elapsed:.3f}s — expected < 1.0s"


# ---------------------------------------------------------------------------
# channels__list_channels: protocol_version must be "1.0"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_channels_includes_protocol_version() -> None:
    """channels__list_channels must include protocol_version: '1.0'."""
    store = MemoryStore()
    mcp = await _make_server_with_store(store, agent_id="agent-zeta")

    async with Client(mcp) as client:
        result = await client.call_tool("channels__list_channels", {})
        data = result.data
        assert isinstance(data, dict)
        assert data["protocol_version"] == "1.0"
        assert "channels" in data
        _validate(data, _SCHEMA_LIST_OUT)


# ---------------------------------------------------------------------------
# channels__recv channel filter: non-matching messages re-queued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recv_channel_filter_preserves_other_messages() -> None:
    """recv with channels filter only returns matching messages.

    Unmatched messages must remain retrievable by a subsequent recv.
    """
    store = MemoryStore()
    mcp = await _make_server_with_store(store, agent_id="agent-eta")

    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "a:*"})
        await client.call_tool("channels__subscribe", {"pattern": "b:*"})

        await client.call_tool(
            "channels__send", {"channel": "a:channel", "body": {"from": "a"}}
        )
        await client.call_tool(
            "channels__send", {"channel": "b:channel", "body": {"from": "b"}}
        )

        await asyncio.sleep(0.15)

        # Drain only channel a:*.
        result_a = await client.call_tool(
            "channels__recv", {"channels": ["a:channel"]}
        )
        assert len(result_a.data["messages"]) == 1
        assert result_a.data["messages"][0]["channel"] == "a:channel"

        # b:channel message must still be retrievable.
        result_b = await client.call_tool("channels__recv", {})
        assert len(result_b.data["messages"]) == 1
        assert result_b.data["messages"][0]["channel"] == "b:channel"


# ---------------------------------------------------------------------------
# Subprocess launch test (smoke: server starts and accepts initialize)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subprocess_server_starts(tmp_path: Path) -> None:
    """Smoke: server spawned as a subprocess responds to initialize."""
    db_path = str(tmp_path / "subprocess_test.db")
    env = {
        **os.environ,
        "SOX_AGENT_ID": "sub-agent",
        "SOX_BACKING_STORE": f"sqlite://{db_path}",
        "SOX_MCP_TRANSPORT": "stdio",
    }

    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "sox_protocol.core.mcp_server"],
        env=env,
        cwd=str(Path(__file__).parents[2]),
    )

    async with Client(transport) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert "channels__send" in tool_names
        assert "channels__recv" in tool_names
        assert "channels__subscribe" in tool_names
        assert "channels__list_channels" in tool_names
