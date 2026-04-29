#!/usr/bin/env python3
"""
Demo runner for two-agent-clarification (DEMO-001).

Simulates the speculative-then-reconcile pattern without a live Claude API.
Two agents share a SOX MCP server backed by SQLite:

  implementer — posts a clarification request, continues under best-guess,
                drains inbox, reconciles when the reply arrives.

  api-reviewer — subscribes to ticket:DEMO-001, drains, finds the request,
                 sends the authoritative reply.

The runner drives both agents sequentially, printing a transcript of every
SOX tool call. This is the automated stand-in for a real Claude Code session;
the demo/ folder also contains the agent system-prompt files so a real
Claude Code project can run the same scenario live.

Exit codes:
  0 — demo completed with correct reconciliation
  1 — assertion failed (unexpected behaviour)
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, AsyncIterator

# ---------------------------------------------------------------------------
# Ensure the packages/python/src tree is importable when run from the repo.
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

_DIVIDER = "-" * 72
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
    _print(f"  -> {tool}({json.dumps(args, indent=4).replace(chr(10), chr(10)+'     ')})")

def _result(label: str, data: Any) -> None:
    import json
    _print(f"  <- {label}: {json.dumps(data, indent=4).replace(chr(10), chr(10)+'     ')}")

def _note(agent: str, text: str) -> None:
    for line in textwrap.wrap(f"[{agent} NOTES] {text}", 72):
        _print(f"  {line}")

# ---------------------------------------------------------------------------
# Shared server factory (mirrors _make_server_with_store from integration tests)
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
    """Execute the full clarification demo and print a transcript."""

    _section("DEMO-001: Two-Agent Clarification (speculative-then-reconcile)")
    _print(f"  Backing store: sqlite://{db_path}")
    _print(f"  Ticket channel: ticket:DEMO-001")

    # -----------------------------------------------------------------------
    # Build two servers sharing the same SQLite database
    # -----------------------------------------------------------------------
    store_impl = SqliteStore(db_path)
    store_reviewer = SqliteStore(db_path)

    mcp_impl = await _make_server(store_impl, "implementer")
    mcp_reviewer = await _make_server(store_reviewer, "api-reviewer")

    # -----------------------------------------------------------------------
    # Phase 1: Both agents subscribe
    # -----------------------------------------------------------------------
    _section("Phase 1 — Startup: both agents subscribe to ticket:DEMO-001")

    async with Client(mcp_impl) as client_impl, Client(mcp_reviewer) as client_reviewer:

        _step("implementer", "subscribe ticket:DEMO-001")
        sub_args = {"pattern": "ticket:DEMO-001"}
        _tool("channels__subscribe", sub_args)
        sub_result = await client_impl.call_tool("channels__subscribe", sub_args)
        _result("subscribed", sub_result.data)

        _step("api-reviewer", "subscribe ticket:DEMO-001")
        _tool("channels__subscribe", sub_args)
        sub_r = await client_reviewer.call_tool("channels__subscribe", sub_args)
        _result("subscribed", sub_r.data)

        # -----------------------------------------------------------------------
        # Phase 2: Implementer discovers ambiguity, sends clarification request
        # -----------------------------------------------------------------------
        _section("Phase 2 — Implementer detects ambiguity, sends clarification request")

        _step("implementer", "spec is silent on JWT expiry — sending clarification request")
        _note("implementer", "Assuming 15-minute (900 s) expiry — standard short-lived token. Will revise if reviewer contradicts.")

        clarif_body = {
            "type": "clarification_request",
            "subject": "JWT expiry for POST /login",
            "context": "Spec §4 is silent on token lifetime.",
            "question": "Should access-token expiry be 15 min (900 s) or 24 h (86400 s)?",
            "urgency": "normal",
        }
        send_args = {
            "channel": "ticket:DEMO-001",
            "body": clarif_body,
            "correlation_id": "clarif-jwt-001",
        }
        _tool("channels__send", send_args)
        send_result = await client_impl.call_tool("channels__send", send_args)
        _result("sent", send_result.data)
        msg_id = send_result.data["message_id"]

        # -----------------------------------------------------------------------
        # Phase 3: Implementer continues working under best-guess
        # -----------------------------------------------------------------------
        _section("Phase 3 — Implementer continues under best-guess (no stalling)")

        _step("implementer", "implementing POST /login with expires_in=900")
        _print("  [simulating 3 tool-calls worth of implementation work]")
        _print("  ... write handler ...")
        _print("  ... validate credentials ...")
        _print("  ... build JWT with exp=now+900 ...")

        _step("implementer", "checkpoint drain (T=4, no reply expected yet)")
        _tool("channels__recv", {})
        recv_early = await client_impl.call_tool("channels__recv", {})
        _result("messages", recv_early.data)
        # Agents receive their own sent messages (by design); filter them out.
        peer_messages_early = [
            m for m in recv_early.data["messages"]
            if m.get("sender") != "implementer"
        ]
        assert peer_messages_early == [], (
            f"Expected no peer messages at T=4, got: {peer_messages_early}"
        )
        _note("implementer", "No peer replies yet. Assumption still pending. Proceeding with 900 s in test fixtures.")

        # -----------------------------------------------------------------------
        # Phase 4: API reviewer drains, finds request, sends reply
        # -----------------------------------------------------------------------
        _section("Phase 4 — API reviewer drains inbox, answers the clarification")

        await asyncio.sleep(0.1)  # let watch loop pick up the message

        _step("api-reviewer", "draining inbox at checkpoint")
        _tool("channels__recv", {})
        recv_reviewer = await client_reviewer.call_tool("channels__recv", {})
        _result("messages", recv_reviewer.data)

        messages = recv_reviewer.data["messages"]
        assert len(messages) == 1, f"Reviewer expected 1 message, got {len(messages)}"
        received = messages[0]
        assert received["body"]["type"] == "clarification_request"
        assert received["correlation_id"] == "clarif-jwt-001"

        _note("api-reviewer", "Clarification request received. Policy: 15 min access token per security-policy-v2 §3.1.")

        reply_body = {
            "type": "clarification_reply",
            "subject": "JWT expiry for POST /login",
            "answer": "15 minutes (900 s) for access token is correct per security-policy-v2 §3.1.",
            "policy_reference": "security-policy-v2 §3.1",
        }
        reply_args = {
            "channel": "ticket:DEMO-001",
            "body": reply_body,
            "correlation_id": "clarif-jwt-001",
        }
        _step("api-reviewer", "sending clarification reply")
        _tool("channels__send", reply_args)
        reply_result = await client_reviewer.call_tool("channels__send", reply_args)
        _result("sent", reply_result.data)
        _note("api-reviewer", "Reply sent. Continuing parallel API review work.")

        # -----------------------------------------------------------------------
        # Phase 5: Implementer drains, finds the reply, reconciles
        # -----------------------------------------------------------------------
        _section("Phase 5 — Implementer drains inbox, reconciles")

        await asyncio.sleep(0.15)  # let watch loop deliver the reply

        _step("implementer", "draining inbox before finalising (T=20)")
        _tool("channels__recv", {})
        recv_final = await client_impl.call_tool("channels__recv", {})
        _result("messages", recv_final.data)

        impl_messages = recv_final.data["messages"]
        # The implementer is subscribed to ticket:DEMO-001 and will also see
        # its own clarification request (as an undelivered message from self).
        # Filter to find only the reply from the reviewer.
        reply_messages = [
            m for m in impl_messages
            if m.get("sender") != "implementer"
            and m.get("body", {}).get("type") == "clarification_reply"
        ]
        assert len(reply_messages) == 1, (
            f"Implementer expected 1 clarification_reply, got {len(reply_messages)}: {impl_messages}"
        )
        reply = reply_messages[0]
        assert reply["body"]["type"] == "clarification_reply"
        assert reply["correlation_id"] == "clarif-jwt-001"

        answer = reply["body"]["answer"]
        _note("implementer", f"Reply received: {answer}")

        # Reconciliation logic
        assumed_expiry = 900
        confirmed_expiry = 900  # reviewer confirmed 15 min
        if "900" in answer or "15 min" in answer:
            _note("implementer", "Assumption CONFIRMED. expires_in=900 s. No rework needed.")
            reconciliation_needed = False
        else:
            _note("implementer", "Assumption CONTRADICTED. Revising implementation.")
            reconciliation_needed = True

        # -----------------------------------------------------------------------
        # Final drain: no further messages
        # -----------------------------------------------------------------------
        recv_empty = await client_impl.call_tool("channels__recv", {})
        peer_messages_final = [
            m for m in recv_empty.data["messages"]
            if m.get("sender") != "implementer"
            and m.get("body", {}).get("type") != "clarification_reply"
        ]
        assert peer_messages_final == [], (
            f"Expected no further peer messages after reconciliation, got: {peer_messages_final}"
        )

        # -----------------------------------------------------------------------
        # Summary
        # -----------------------------------------------------------------------
        _section("DEMO-001 COMPLETE")
        _print(f"  Assumption: JWT expiry = {assumed_expiry} s (15 min)")
        _print(f"  Reviewer answer: {answer}")
        _print(f"  Reconciliation required: {reconciliation_needed}")
        _print(f"  Final expires_in: {confirmed_expiry} s")
        _print(f"  Total extra tool calls: 3 (1 send + 2 recv over 20 simulated steps)")
        _print(f"\n  Pattern demonstrated: speculative-then-reconcile")
        _print(f"  - Implementer never stalled waiting for the reply")
        _print(f"  - Work continued for 19 simulated steps without blocking")
        _print(f"  - Assumption was correct; zero rework was needed")

        assert not reconciliation_needed, "Demo assertion: assumption should be confirmed for DEMO-001"

    _print(f"\n{_SECTION}")
    _print("  DEMO-001 PASSED")
    _print(_SECTION)


def main() -> None:
    import tempfile
    import os

    # Use a temp file by default; allow override via SOX_DEMO_DB
    db_path = os.environ.get("SOX_DEMO_DB", "")
    if not db_path:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, prefix="sox_demo_001_")
        db_path = tmp.name
        tmp.close()

    try:
        asyncio.run(run_demo(db_path))
    except AssertionError as exc:
        _print(f"\nDEMO FAILED: {exc}")
        sys.exit(1)
    finally:
        # Clean up temp db unless caller pinned it
        if not os.environ.get("SOX_DEMO_DB"):
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
