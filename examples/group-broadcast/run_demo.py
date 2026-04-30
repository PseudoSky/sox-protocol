#!/usr/bin/env python3
"""
Demo runner for group-broadcast (DEMO-002).

Simulates a three-agent group broadcast scenario without a live Claude API.
Three agents share a SOX MCP server backed by SQLite:

  implementer — broadcasts a status_update to ticket:DEMO-002 after
                completing the POST /orders handler.

  reviewer    — drains inbox at checkpoint, updates review queue,
                sends NO reply.

  docs-writer — drains inbox at checkpoint, extracts commit refs,
                starts writing orders docs, sends NO reply.

The runner drives all three agents, printing a transcript of every SOX
tool call, and asserts that:
  - Exactly 1 broadcast was sent.
  - Both reviewer and docs-writer received it.
  - Neither reviewer nor docs-writer sent a reply.

Exit codes:
  0 — demo completed correctly
  1 — assertion failed
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import textwrap
from pathlib import Path
from typing import Any, AsyncIterator

# ---------------------------------------------------------------------------
# Ensure packages/python/src is importable when run from the repo
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_SRC = _REPO_ROOT / "packages" / "python" / "src"
if str(_PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(_PYTHON_SRC))

from fastmcp import Client, FastMCP  # noqa: E402

from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore  # noqa: E402
from sox_protocol.core.mcp_server.listener import Listener  # noqa: E402
from sox_protocol.core.mcp_server.server import _load_and_validate_schemas  # noqa: E402
from sox_protocol.core.mcp_server.tools import register_tools  # noqa: E402

# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------

_SECTION = "=" * 72


def _print(msg: str) -> None:
    print(msg, flush=True)


def _section(title: str) -> None:
    _print(f"\n{_SECTION}")
    _print(f"  {title}")
    _print(_SECTION)


def _step(agent: str, action: str) -> None:
    _print(f"\n[{agent}] {action}")


def _tool(tool: str, args: dict[str, Any]) -> None:
    import json
    _print(f"  -> {tool}({json.dumps(args, indent=4).replace(chr(10), chr(10) + '     ')})")


def _result(label: str, data: Any) -> None:
    import json
    _print(f"  <- {label}: {json.dumps(data, indent=4).replace(chr(10), chr(10) + '     ')}")


def _note(agent: str, text: str) -> None:
    for line in textwrap.wrap(f"[{agent} NOTES] {text}", 72):
        _print(f"  {line}")


# ---------------------------------------------------------------------------
# Shared server factory
# ---------------------------------------------------------------------------

async def _make_server(store: Any, agent_id: str) -> FastMCP[Any]:
    @contextlib.asynccontextmanager
    async def _lifespan(server: FastMCP[Any]) -> AsyncIterator[dict[str, object]]:
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

    mcp: FastMCP[Any] = FastMCP(name=f"sox-{agent_id}", lifespan=_lifespan)
    register_tools(mcp)
    return mcp


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def run_demo(db_path: str) -> None:
    """Execute the full broadcast demo and print a transcript."""

    _section("DEMO-002: Group Broadcast (three-agent status update)")
    _print(f"  Backing store: sqlite://{db_path}")
    _print(f"  Ticket channel: ticket:DEMO-002")
    _print(f"  Agents: implementer, reviewer, docs-writer")

    # Build three servers sharing the same SQLite database
    store_impl = SqliteStore(db_path)
    store_reviewer = SqliteStore(db_path)
    store_docs = SqliteStore(db_path)

    mcp_impl = await _make_server(store_impl, "implementer")
    mcp_reviewer = await _make_server(store_reviewer, "reviewer")
    mcp_docs = await _make_server(store_docs, "docs-writer")

    # -----------------------------------------------------------------------
    # Phase 1: All three agents subscribe
    # -----------------------------------------------------------------------
    _section("Phase 1 — Startup: all three agents subscribe to ticket:DEMO-002")

    async with (
        Client(mcp_impl) as client_impl,
        Client(mcp_reviewer) as client_reviewer,
        Client(mcp_docs) as client_docs,
    ):
        for name, client in [
            ("implementer", client_impl),
            ("reviewer", client_reviewer),
            ("docs-writer", client_docs),
        ]:
            _step(name, "subscribe ticket:DEMO-002")
            _tool("channels__subscribe", {"pattern": "ticket:DEMO-002"})
            sub_r = await client.call_tool(
                "channels__subscribe", {"pattern": "ticket:DEMO-002"}
            )
            _result("subscribed", sub_r.data)

        # -----------------------------------------------------------------------
        # Phase 2: Reviewer and docs-writer do their own parallel work
        # -----------------------------------------------------------------------
        _section("Phase 2 — Reviewer and docs-writer working in parallel")

        _step("reviewer", "reviewing earlier commits (pre-existing work queue)")
        _print("  [simulating review of commit set alpha-001..alpha-010]")

        _step("docs-writer", "drafting authentication section (no orders handler yet)")
        _print("  [simulating doc drafting: auth section complete]")

        # Early drain: inbox should be empty
        _step("reviewer", "checkpoint drain (pre-broadcast, expected empty)")
        _tool("channels__recv", {})
        drain_early = await client_reviewer.call_tool("channels__recv", {})
        _result("messages", drain_early.data)
        assert drain_early.data["messages"] == [], "Reviewer inbox should be empty before broadcast"

        # -----------------------------------------------------------------------
        # Phase 3: Implementer completes handler and broadcasts
        # -----------------------------------------------------------------------
        _section("Phase 3 — Implementer completes POST /orders handler, broadcasts")

        _step("implementer", "completing POST /orders handler")
        _print("  [simulating implementation: handler + domain model + auth middleware]")
        _print("  Commits: abc-001, abc-002, abc-003, abc-004")

        broadcast_body = {
            "type": "status_update",
            "subject": "POST /orders handler complete",
            "context": (
                "POST /orders handler and domain model landed in commits "
                "abc-001 through abc-004. Auth middleware wired. "
                "Tests not yet written."
            ),
            "urgency": "low",
        }
        broadcast_args = {
            "channel": "ticket:DEMO-002",
            "body": broadcast_body,
        }
        _step("implementer", "broadcasting status update")
        _tool("channels__send", broadcast_args)
        bcast_result = await client_impl.call_tool("channels__send", broadcast_args)
        _result("sent", bcast_result.data)
        bcast_msg_id = bcast_result.data["message_id"]

        _step("implementer", "returning immediately to write tests (no wait for ack)")
        _print("  [simulating test writing: POST /orders unit tests]")

        # -----------------------------------------------------------------------
        # Phase 4: Reviewer drains, receives broadcast, updates queue
        # -----------------------------------------------------------------------
        _section("Phase 4 — Reviewer drains inbox, processes broadcast")

        await asyncio.sleep(0.15)  # let watch loops pick up the message

        _step("reviewer", "checkpoint drain before next review batch")
        _tool("channels__recv", {})
        recv_reviewer = await client_reviewer.call_tool("channels__recv", {})
        _result("messages", recv_reviewer.data)

        reviewer_msgs = recv_reviewer.data["messages"]
        assert len(reviewer_msgs) == 1, (
            f"Reviewer expected 1 broadcast, got {len(reviewer_msgs)}"
        )
        bcast_recv = reviewer_msgs[0]
        assert bcast_recv["body"]["type"] == "status_update"
        assert "abc-001" in bcast_recv["body"]["context"]

        _note("reviewer", (
            f"Broadcast received: '{bcast_recv['body']['subject']}'. "
            "Queuing review of commits abc-001 through abc-004. "
            "NO reply sent — this is a status_update, not a question."
        ))

        # Verify reviewer does NOT send a reply
        reviewer_reply_count = 0  # will check channel at end

        # -----------------------------------------------------------------------
        # Phase 5: Docs-writer drains, receives broadcast, starts orders docs
        # -----------------------------------------------------------------------
        _section("Phase 5 — Docs-writer drains inbox, processes broadcast")

        _step("docs-writer", "checkpoint drain before starting orders section")
        _tool("channels__recv", {})
        recv_docs = await client_docs.call_tool("channels__recv", {})
        _result("messages", recv_docs.data)

        docs_msgs = recv_docs.data["messages"]
        assert len(docs_msgs) == 1, (
            f"Docs-writer expected 1 broadcast, got {len(docs_msgs)}"
        )
        bcast_docs = docs_msgs[0]
        assert bcast_docs["body"]["type"] == "status_update"

        # Extract commit refs from broadcast
        context_text = bcast_docs["body"]["context"]
        assert "abc-001" in context_text
        commit_refs = "abc-001 through abc-004"

        _note("docs-writer", (
            f"Broadcast received. Handler exists — commit refs: {commit_refs}. "
            "Starting orders endpoint documentation. "
            "NO reply sent — informational update."
        ))
        _print(f"  [simulating doc writing: POST /orders section with refs {commit_refs}]")

        # -----------------------------------------------------------------------
        # Phase 6: Implementer drains its own inbox after broadcast
        # -----------------------------------------------------------------------
        _section("Phase 6 — Implementer drains own inbox (expects no replies)")

        await asyncio.sleep(0.1)

        _step("implementer", "final inbox drain (should be empty — no replies expected)")
        _tool("channels__recv", {})
        recv_impl_final = await client_impl.call_tool("channels__recv", {})
        _result("messages", recv_impl_final.data)

        impl_inbox = recv_impl_final.data["messages"]
        # The implementer is subscribed and may see its own broadcast.
        # Per SOX semantics, the implementer will see the broadcast it sent
        # (it is subscribed to ticket:DEMO-002). That's expected — it's its
        # own message. Filter it to check no *peer* replied.
        non_self_msgs = [
            m for m in impl_inbox
            if m.get("sender") != "implementer"
        ]
        assert non_self_msgs == [], (
            f"Implementer should receive no peer replies, got: {non_self_msgs}"
        )
        _note("implementer", (
            f"Inbox has {len(impl_inbox)} message(s) (own broadcast visible to self). "
            "No peer replies received — correct broadcast-only behaviour."
        ))

        # -----------------------------------------------------------------------
        # Verify channel state
        # -----------------------------------------------------------------------
        _section("Phase 7 — Channel introspection")

        _step("implementer", "list channels")
        _tool("channels__list_channels", {})
        list_r = await client_impl.call_tool("channels__list_channels", {})
        _result("channels", list_r.data)
        channels_data = list_r.data["channels"]
        demo_ch = next((c for c in channels_data if c["name"] == "ticket:DEMO-002"), None)
        assert demo_ch is not None, "ticket:DEMO-002 should appear in channel list"
        assert demo_ch["subscriber_count"] == 3, (
            f"Expected 3 subscribers, got {demo_ch['subscriber_count']}"
        )

        # -----------------------------------------------------------------------
        # Summary
        # -----------------------------------------------------------------------
        _section("DEMO-002 COMPLETE")
        _print("  Implementer: 1 status_update broadcast sent")
        _print("  Reviewer:    1 broadcast received, review queue updated, 0 replies sent")
        _print("  Docs-writer: 1 broadcast received, orders docs started, 0 replies sent")
        _print(f"  Channel ticket:DEMO-002: {demo_ch['subscriber_count']} subscribers")
        _print("")
        _print("  Pattern demonstrated: group broadcast without reply")
        _print("  - Single send reached all 3 subscribers")
        _print("  - Receivers updated state on their own drain schedule")
        _print("  - status_update messages require no reply")

    _print(f"\n{_SECTION}")
    _print("  DEMO-002 PASSED")
    _print(_SECTION)


def main() -> None:
    import os
    import tempfile

    db_path = os.environ.get("SOX_DEMO_DB", "")
    if not db_path:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, prefix="sox_demo_002_")
        db_path = tmp.name
        tmp.close()

    try:
        asyncio.run(run_demo(db_path))
    except AssertionError as exc:
        _print(f"\nDEMO FAILED: {exc}")
        sys.exit(1)
    finally:
        if not os.environ.get("SOX_DEMO_DB"):
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
