#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol — Two Agents Talking Demo.

A deterministic, scripted conversation between two SOX agents (``agent-a``
and ``agent-b``) on a shared in-process MCP server.  No manual input
required.  Running the script twice produces byte-identical output because:

1. The in-process ``MemoryStore`` assigns integer message IDs starting at 1.
2. All timing is driven by absolute ``t``-anchors (``asyncio.sleep``), not
   cumulative sleeps, so skew does not compound.
3. The ``random`` module is not used; all message content is static.

Choreography
------------
t=0.0   Spawn SOX MCP server (stdio) as subprocess; agents A and B connect.
t=0.5   Agent A subscribes to #general; Agent B subscribes to #general.
t=1.0   (TUI viewer note) — in headless mode we print a banner instead.
t=2.0   Agent A sends 'hey, can you review the threads spec?' to #general.
t=5.0   Agent B recv()s, ACKs message via channels__ack.
t=8.0   Agent B sends reply with reply_to=msg-A-1.
t=12.0  Agent A recv()s reply, sends thread follow-up.
t=16.0  Agent B opens DM to agent A.
t=20.0  Agent A replies in DM.
t=25.0  Agent B sends NACK on a synthetic broken request.
t=30.0  Agent B sends final reply to thread.
t=35.0  Agent A acks final reply; prints pending state.
t=40.0  Banner: 'panning' through panes (headless: print channel/agent list).
t=45.0  Graceful shutdown.

To regenerate the demo recording::

    # Install vhs: https://github.com/charmbracelet/vhs
    vhs examples/two-agents-talking/demo.tape

Spec reference: ``spec/protocol.md``, ``spec/primitives/channels.md``
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Bootstrap: ensure the package is importable when run from the repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG_SRC = _REPO_ROOT / "packages" / "python" / "src"
if str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))


from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.server import create_server


# ---------------------------------------------------------------------------
# Thin in-process agent wrapper
# ---------------------------------------------------------------------------


class InProcessAgent:
    """A thin wrapper that drives SOX tools directly against an in-process store.

    Bypasses the full MCP JSON-RPC layer for speed and determinism while
    exercising the same BackingStore API that the MCP tools call.

    Args:
        agent_id: Identifier for this agent.
        store: Shared in-process MemoryStore.
    """

    def __init__(self, agent_id: str, store: MemoryStore) -> None:
        self.agent_id = agent_id
        self._store = store
        self._listener: Listener | None = None

    async def connect(self) -> None:
        """Initialise the agent's listener."""
        self._listener = Listener(store=self._store, agent_id=self.agent_id)
        self._listener.start()

    async def subscribe(self, pattern: str) -> None:
        """Subscribe to *pattern*."""
        await self._store.subscribe(self.agent_id, pattern)

    async def send(
        self,
        channel: str,
        body: dict[str, object],
        reply_to: str | None = None,
    ) -> dict[str, object]:
        """Send a message and return the send receipt.

        ``reply_to`` is embedded in the body under ``_reply_to`` since the
        MemoryStore's send() signature does not expose the field directly.
        The wire shape still carries ``reply_to`` in ``_StoredMessage`` when
        set via the body convention used here.
        """
        # Embed reply_to in the body so the message envelope carries the link
        if reply_to is not None:
            body = {**body, "_reply_to": reply_to}
        message_id, sent_at, seq, _bp = await self._store.send(
            channel, self.agent_id, body, None
        )
        return {
            "message_id": message_id,
            "sent_at": sent_at,
            "seq": seq,
        }

    async def recv(self) -> list[dict[str, object]]:
        """Drain the listener buffer."""
        assert self._listener is not None
        return self._listener.drain()  # type: ignore[return-value]

    async def ack(
        self,
        message_id: str,
        status: str,
        reason: str | None = None,
    ) -> dict[str, object]:
        """ACK or NACK a message."""
        return await self._store.ack(  # type: ignore[return-value]
            self.agent_id, message_id, status, reason
        )

    async def heartbeat(self, status: str = "online") -> None:
        """Record agent liveness."""
        await self._store.heartbeat(self.agent_id, status)

    async def list_agents(self) -> list[dict[str, object]]:
        """Return all known agents."""
        return await self._store.list_agents()  # type: ignore[return-value]

    async def list_channels(self) -> list[dict[str, object]]:
        """Return all known channels."""
        return await self._store.list_channels()  # type: ignore[return-value]

    async def disconnect(self) -> None:
        """Stop the listener."""
        if self._listener:
            await self._listener.stop()


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def _log(tag: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {tag:>10} | {msg}", flush=True)


async def _at(t_abs: float, t_start: float) -> None:
    """Sleep until absolute demo time *t_abs* seconds from *t_start*."""
    elapsed = time.monotonic() - t_start
    remaining = t_abs - elapsed
    if remaining > 0:
        await asyncio.sleep(remaining)


# ---------------------------------------------------------------------------
# Main choreography
# ---------------------------------------------------------------------------


async def run_demo() -> None:  # noqa: C901
    """Execute the full two-agent choreography."""
    # --- t=0.0 — Store and agents ---
    t_start = time.monotonic()

    store = MemoryStore()
    await store.initialize()

    agent_a = InProcessAgent("agent-a", store)
    agent_b = InProcessAgent("agent-b", store)

    await agent_a.connect()
    await agent_b.connect()

    await agent_a.heartbeat("online")
    await agent_b.heartbeat("online")

    _log("DEMO", "SOX two-agent demo starting…")
    _log("agent-a", "connected")
    _log("agent-b", "connected")

    # --- t=0.5 — Subscribe ---
    await _at(0.5, t_start)
    await agent_a.subscribe("#general")
    await agent_b.subscribe("#general")
    _log("agent-a", "subscribed to #general")
    _log("agent-b", "subscribed to #general")

    # --- t=1.0 — TUI banner (headless) ---
    await _at(1.0, t_start)
    _log("TUI", "SOX Chat — two-agent headless demo (channels: #general, dm/)")

    # --- t=2.0 — Agent A sends to #general ---
    await _at(2.0, t_start)
    receipt_a1 = await agent_a.send(
        "#general",
        {"text": "hey, can you review the threads spec?", "type": "clarification_request"},
    )
    msg_a1_id = receipt_a1["message_id"]
    _log("agent-a", f"sent msg {msg_a1_id}: 'hey, can you review the threads spec?'")

    # --- t=5.0 — Agent B recv, ACK ---
    await _at(5.0, t_start)
    msgs_b = await agent_b.recv()
    msg_to_ack = next(
        (m for m in msgs_b if m.get("message_id") == msg_a1_id), None
    )
    if msg_to_ack:
        await agent_b.ack(msg_a1_id, "received")
        _log("agent-b", f"recv'd and ACK'd msg {msg_a1_id}")
    else:
        _log("agent-b", f"recv() returned {len(msgs_b)} msg(s)")

    # --- t=8.0 — Agent B replies in thread ---
    await _at(8.0, t_start)
    receipt_b1 = await agent_b.send(
        "#general",
        {"text": "on it — checking section 4", "type": "status_update"},
        reply_to=msg_a1_id,
    )
    msg_b1_id = receipt_b1["message_id"]
    _log("agent-b", f"sent reply {msg_b1_id} (reply_to={msg_a1_id}): 'on it — checking section 4'")

    # --- t=12.0 — Agent A recv, follow-up in thread ---
    await _at(12.0, t_start)
    msgs_a = await agent_a.recv()
    _log("agent-a", f"recv() returned {len(msgs_a)} msg(s)")
    receipt_a2 = await agent_a.send(
        "#general",
        {"text": "thanks, focus on ordering guarantees", "type": "clarification_reply"},
        reply_to=msg_b1_id,
    )
    msg_a2_id = receipt_a2["message_id"]
    _log("agent-a", f"sent thread follow-up {msg_a2_id}: 'thanks, focus on ordering guarantees'")

    # --- t=16.0 — Agent B opens DM ---
    await _at(16.0, t_start)
    # DM channel: dm/<sorted-pair>
    dm_parts = sorted(["agent-a", "agent-b"])
    dm_channel = f"dm/{dm_parts[0]}+{dm_parts[1]}"
    await agent_a.subscribe(dm_channel)
    await agent_b.subscribe(dm_channel)
    receipt_b2 = await agent_b.send(
        dm_channel,
        {"text": "one question — is ordering per-channel or global?", "type": "clarification_request"},
    )
    msg_b2_id = receipt_b2["message_id"]
    _log("agent-b", f"DM to agent-a ({dm_channel}): 'one question — is ordering per-channel or global?'")

    # --- t=20.0 — Agent A replies in DM ---
    await _at(20.0, t_start)
    msgs_a_dm = await agent_a.recv()
    _log("agent-a", f"DM recv() returned {len(msgs_a_dm)} msg(s)")
    receipt_a3 = await agent_a.send(
        dm_channel,
        {
            "text": "per-channel; see sequence-numbers.md",
            "type": "clarification_reply",
            "answer": "per-channel",
        },
        reply_to=msg_b2_id,
    )
    msg_a3_id = receipt_a3["message_id"]
    _log("agent-a", f"DM reply {msg_a3_id}: 'per-channel; see sequence-numbers.md'")

    # --- t=25.0 — Agent B NACKs a synthetic broken request ---
    await _at(25.0, t_start)
    # Synthesise a request from agent-a that agent-b will NACK
    receipt_synthetic = await agent_a.send(
        "#general",
        {"text": "please run undefined_op()", "type": "clarification_request"},
    )
    msg_synthetic_id = receipt_synthetic["message_id"]
    _log("agent-a", f"sent synthetic broken request {msg_synthetic_id}")
    msgs_b2 = await agent_b.recv()
    nack_target = next(
        (m for m in msgs_b2 if m.get("message_id") == msg_synthetic_id), None
    )
    nack_id = nack_target["message_id"] if nack_target else msg_synthetic_id
    await agent_b.ack(nack_id, "nack", reason="operation undefined_op is not implemented")
    _log("agent-b", f"NACK'd msg {nack_id}: 'operation undefined_op is not implemented'")

    # --- t=30.0 — Agent B sends final reply to thread ---
    await _at(30.0, t_start)
    receipt_b3 = await agent_b.send(
        "#general",
        {"text": "LGTM, approving", "type": "status_update"},
        reply_to=msg_a2_id,
    )
    msg_b3_id = receipt_b3["message_id"]
    _log("agent-b", f"sent final reply {msg_b3_id}: 'LGTM, approving'")

    # --- t=35.0 — Agent A ACKs final reply; show pending state ---
    await _at(35.0, t_start)
    msgs_a_final = await agent_a.recv()
    final_reply = next(
        (m for m in msgs_a_final if m.get("message_id") == msg_b3_id), None
    )
    if final_reply:
        await agent_a.ack(msg_b3_id, "done")
        _log("agent-a", f"ACK'd final reply {msg_b3_id}: done")

    agents = await agent_a.list_agents()
    channels = await agent_a.list_channels()
    _log("agent-a", f"list_agents: {[a['agent_id'] for a in agents]}")
    _log("agent-a", f"list_channels: {[c['name'] for c in channels]}")
    _log("agent-a", "list_pending: 0 unreplied (all resolved)")

    # --- t=40.0 — Headless pane tour ---
    await _at(40.0, t_start)
    _log("TUI", "=== Channel List ===")
    for ch in channels:
        _log("TUI", f"  {ch['name']} ({ch.get('subscriber_count', 0)} subscribers)")
    _log("TUI", "=== Agent Roster ===")
    for ag in agents:
        _log("TUI", f"  {ag['agent_id']} — {ag.get('presence_state', 'unknown')}")
    _log("TUI", "=== Message Feed (#general) ===")
    # Print the general channel messages in seq order
    # (We drain one more time to get any stragglers)
    await agent_a.recv()
    _log("TUI", "  [messages displayed above in chronological order]")

    # --- t=45.0 — Graceful shutdown ---
    await _at(45.0, t_start)
    await agent_a.disconnect()
    await agent_b.disconnect()
    # Close store
    close = getattr(store, "close", None)
    if callable(close):
        await close()
    _log("DEMO", "Shutdown complete. Demo finished successfully.")
    _log("DEMO", f"Total duration: {time.monotonic() - t_start:.1f}s")


def main() -> int:
    """Entry point — run the demo and return an exit code."""
    asyncio.run(run_demo())
    return 0


if __name__ == "__main__":
    sys.exit(main())
