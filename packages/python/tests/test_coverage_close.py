# SPDX-License-Identifier: Apache-2.0
"""Targeted tests closing the last 1% coverage gap (non-HTTP-route part).

Each test pins a specific uncovered line. Cross-references to source line
numbers are documented inline. If a referenced line moves, update both.

HTTP-route validation tests live at tests/transports/http/test_coverage_close.py
because they need the http conftest fixtures (auth, ASGI client).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from sox_protocol.adapters.backing_stores.filesystem.store import FilesystemStore
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore
from sox_protocol.adapters.transports.http.liveness import AgentRecord, LivenessStore
from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.default_chain import _StoreTerminal
from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware


# ---------------------------------------------------------------------------
# adapter list_agents presence-state branches
# ---------------------------------------------------------------------------


def _seed_liveness(store: Any, *, now: float) -> None:
    """Inject three records: online, offline (reported), stale (expired)."""
    store._liveness = {
        "agent-online": {
            "namespace": None,
            "expires_at": now + 60.0,
            "status": "online",
            "recorded_at": now,
        },
        "agent-offline": {
            "namespace": None,
            "expires_at": now + 60.0,
            "status": "offline",  # → presence = "offline" branch
            "recorded_at": now,
        },
        "agent-stale": {
            "namespace": None,
            "expires_at": now - 60.0,  # expired → presence = "stale" branch
            "status": "online",
            "recorded_at": now - 120.0,
        },
    }


@pytest.mark.asyncio
async def test_memory_list_agents_offline_and_stale_branches() -> None:
    """memory/store.py line 361: presence = 'stale' branch."""
    store = MemoryStore()
    await store.initialize()
    _seed_liveness(store, now=time.time())
    out = await store.list_agents()
    by_id = {r["agent_id"]: r for r in out}
    assert by_id["agent-offline"]["presence_state"] == "offline"
    assert by_id["agent-stale"]["presence_state"] == "stale"


@pytest.mark.asyncio
async def test_sqlite_list_agents_offline_and_stale_branches(tmp_path: Path) -> None:
    """sqlite/store.py lines 569, 571: presence = 'offline' / 'stale' branches."""
    store = SqliteStore(str(tmp_path / "sqlite.db"))
    await store.initialize()
    _seed_liveness(store, now=time.time())
    out = await store.list_agents()
    by_id = {r["agent_id"]: r for r in out}
    assert by_id["agent-offline"]["presence_state"] == "offline"
    assert by_id["agent-stale"]["presence_state"] == "stale"
    await store.close()


@pytest.mark.asyncio
async def test_filesystem_list_agents_offline_and_stale_branches(tmp_path: Path) -> None:
    """filesystem/store.py lines 534, 536: presence = 'offline' / 'stale' branches."""
    store = FilesystemStore(str(tmp_path))
    await store.initialize()
    _seed_liveness(store, now=time.time())
    out = await store.list_agents()
    by_id = {r["agent_id"]: r for r in out}
    assert by_id["agent-offline"]["presence_state"] == "offline"
    assert by_id["agent-stale"]["presence_state"] == "stale"


# ---------------------------------------------------------------------------
# filesystem recv with already-delivered file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filesystem_recv_skips_already_delivered(tmp_path: Path) -> None:
    """filesystem/store.py lines 414-415: skip files already in delivered set."""
    store = FilesystemStore(str(tmp_path))
    await store.initialize()
    await store.subscribe("agent-a", "ch:test")
    await store.send("ch:test", "agent-b", {"x": 1})
    msgs1 = await store.recv("agent-a", ["ch:test"])
    assert len(msgs1) == 1
    # Second recv: file is now in delivered set; loop must hit `seen.add; continue`.
    msgs2 = await store.recv("agent-a", ["ch:test"])
    assert msgs2 == []


# ---------------------------------------------------------------------------
# liveness.py status_filter exclusion
# ---------------------------------------------------------------------------


def test_liveness_list_agents_status_filter_excludes() -> None:
    """liveness.py line 139: status_filter exclusion `continue`."""
    livestore = LivenessStore()
    now_ns = time.time_ns()
    livestore._records = {
        "agent-1": AgentRecord(
            agent_id="agent-1",
            last_heartbeat_at_ns=now_ns,
            reported_status="online",
            namespace=None,
        ),
        "agent-2": AgentRecord(
            agent_id="agent-2",
            last_heartbeat_at_ns=now_ns,
            reported_status="busy",
            namespace=None,
        ),
    }
    out = livestore.list_agents(status_filter=["busy"])
    ids = [r["agent_id"] for r in out]
    assert ids == ["agent-2"]


# ---------------------------------------------------------------------------
# default_chain._StoreTerminal._noop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_terminal_noop_branch() -> None:
    """default_chain.py line 58: _StoreTerminal's inner _noop returns {}."""
    store = MemoryStore()
    await store.initialize()
    inner = StoreDispatchMiddleware(store)
    terminal = _StoreTerminal(inner)
    ctx = MiddlewareContext(
        operation="list_channels",
        input={},
        connection_id="conn-terminal-test",
    )
    ctx.agent_id = "agent-x"
    out = await terminal(ctx)
    assert isinstance(out, dict)


# ---------------------------------------------------------------------------
# store_dispatch channels_collect path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_dispatch_channels_collect_path() -> None:
    """store_dispatch.py lines 182-183: channels_collect drains and seq-stamps messages."""
    store = MemoryStore()
    await store.initialize()
    await store.subscribe("agent-x", "ch:c1")
    await store.send("ch:c1", "agent-y", {"n": 1})
    await store.send("ch:c1", "agent-y", {"n": 2})
    mw = StoreDispatchMiddleware(store)
    ctx = MiddlewareContext(
        operation="channels_collect",
        input={"channels": ["ch:c1"], "max_messages": 10},
        connection_id="conn-collect",
    )
    ctx.agent_id = "agent-x"

    async def _terminal(_c: MiddlewareContext) -> dict[str, object]:
        return {}

    out = await mw(ctx, _terminal)
    assert "messages" in out
    msgs = out["messages"]
    assert isinstance(msgs, list)
    assert len(msgs) == 2
    seqs = [m.get("seq") for m in msgs]
    assert all(s is not None for s in seqs)
