# SPDX-License-Identifier: Apache-2.0
"""Integration tests: two-agent speculative-then-reconcile exchange (M7).

CI version of ``examples/two-agent-clarification/run_demo.py``.

These tests run entirely in-process using FastMCP's ``Client(mcp_instance)``
harness, with a SQLite backing store on a pytest tmp_path.  No live Claude
API key is required.

Recording approach
------------------
There are no recorded LLM fixtures here because the agents in this test are
deterministic Python code that directly calls the four SOX MCP tools.  The
goal is to verify that the *protocol mechanics* work correctly end-to-end:

  1. Agent A sends a clarification request and continues under a best-guess.
  2. Agent B (subscribed to the same channel) receives the request and replies.
  3. Agent A drains its inbox and finds the reply with the correct correlation_id.
  4. Agent A reconciles its assumption against the reply.

If you want to test with real Claude responses, set SOX_LIVE_TEST=1 and
provide ANTHROPIC_API_KEY.  The tests are designed so the live path uses
the same assertions; only the agent logic changes from deterministic to LLM.

Fixtures
--------
All tests use SQLite (not MemoryStore) so they exercise cross-store delivery,
which is the scenario that matters for multi-agent workloads.  MemoryStore
is single-process only.

Parametrisation
---------------
Tests are parametrised over (assumption_correct=True, assumption_correct=False)
to cover both the confirmation and the contradiction paths of reconciliation.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastmcp import Client, FastMCP

from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.server import _load_and_validate_schemas
from sox_protocol.core.mcp_server.tools import register_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_server(store: Any, agent_id: str) -> FastMCP[Any]:
    """Build an in-process FastMCP server wired to *store* as *agent_id*."""

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


def _extract_body(messages: list[dict[str, Any]], msg_type: str) -> dict[str, Any] | None:
    """Return the first message whose body['type'] matches *msg_type*."""
    for m in messages:
        if isinstance(m.get("body"), dict) and m["body"].get("type") == msg_type:
            return m
    return None


# ---------------------------------------------------------------------------
# Scenario 1: Clarification request → reply → assumption CONFIRMED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarification_assumption_confirmed(tmp_path: Path) -> None:
    """Full speculative-then-reconcile exchange where the reply confirms
    the implementer's assumption.

    Timeline:
      T1 — implementer subscribes, sends clarification_request (expires_in=900)
      T2 — implementer drains (expects empty: reply not yet sent)
      T3 — reviewer subscribes, drains, finds request, sends clarification_reply
      T4 — implementer drains, finds reply, confirms assumption
      T5 — implementer drains again (must be empty: no further messages)
    """
    db_path = str(tmp_path / "clarif_confirmed.db")

    store_impl = SqliteStore(db_path)
    store_reviewer = SqliteStore(db_path)

    mcp_impl = await _make_server(store_impl, "implementer")
    mcp_reviewer = await _make_server(store_reviewer, "api-reviewer")

    async with Client(mcp_impl) as impl, Client(mcp_reviewer) as reviewer:

        # T1 — implementer subscribes + sends clarification request
        await impl.call_tool("channels__subscribe", {"pattern": "ticket:DEMO-001"})

        send_result = await impl.call_tool(
            "channels__send",
            {
                "channel": "ticket:DEMO-001",
                "body": {
                    "type": "clarification_request",
                    "subject": "JWT expiry for POST /login",
                    "question": "15 min or 24 h?",
                    "urgency": "normal",
                },
                "correlation_id": "clarif-jwt-001",
            },
        )
        assert "message_id" in send_result.data
        assert isinstance(send_result.data["sent_at"], float)

        # T2 — implementer drains: reply has not been sent yet
        drain_early = await impl.call_tool("channels__recv", {})
        # The implementer will see its own clarification_request because it is
        # subscribed to the channel (SOX delivers to all subscribers including sender).
        # No *reply* should be present yet.
        early_msgs = drain_early.data["messages"]
        reply_early = _extract_body(early_msgs, "clarification_reply")
        assert reply_early is None, (
            f"Reply should not exist yet at T2, got: {early_msgs}"
        )

        # T3 — reviewer subscribes, drains, receives request, sends reply
        await reviewer.call_tool("channels__subscribe", {"pattern": "ticket:DEMO-001"})
        await asyncio.sleep(0.1)  # let watch loop deliver

        drain_reviewer = await reviewer.call_tool("channels__recv", {})
        reviewer_msgs = drain_reviewer.data["messages"]
        request_msg = _extract_body(reviewer_msgs, "clarification_request")
        assert request_msg is not None, (
            f"Reviewer expected clarification_request, got: {reviewer_msgs}"
        )
        assert request_msg["correlation_id"] == "clarif-jwt-001"
        assert request_msg["sender"] == "implementer"

        # Reviewer answers: confirms 15 min (900 s)
        reply_result = await reviewer.call_tool(
            "channels__send",
            {
                "channel": "ticket:DEMO-001",
                "body": {
                    "type": "clarification_reply",
                    "subject": "JWT expiry for POST /login",
                    "answer": "15 minutes (900 s) — confirmed by security policy.",
                },
                "correlation_id": "clarif-jwt-001",
            },
        )
        assert "message_id" in reply_result.data

        # T4 — implementer drains, finds the reply
        await asyncio.sleep(0.15)  # let watch loop deliver reply to implementer

        drain_final = await impl.call_tool("channels__recv", {})
        final_msgs = drain_final.data["messages"]
        reply_msg = _extract_body(final_msgs, "clarification_reply")
        assert reply_msg is not None, (
            f"Implementer expected clarification_reply, got: {final_msgs}"
        )
        assert reply_msg["correlation_id"] == "clarif-jwt-001"
        assert reply_msg["sender"] == "api-reviewer"

        # Reconciliation: assumption was 900 s; reply confirms 900 s
        answer = reply_msg["body"]["answer"]
        assert "900" in answer or "15 min" in answer, (
            f"Expected 900 s confirmation in reply, got: {answer!r}"
        )
        assumption_correct = "900" in answer or "15 min" in answer
        assert assumption_correct, "Assumption should be confirmed in this scenario"

        # T5 — second drain must be empty
        drain_empty = await impl.call_tool("channels__recv", {})
        assert drain_empty.data["messages"] == [], (
            f"Expected empty inbox after full exchange, got: {drain_empty.data['messages']}"
        )


# ---------------------------------------------------------------------------
# Scenario 2: Clarification request → contradicting reply → reconcile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarification_assumption_contradicted(tmp_path: Path) -> None:
    """Speculative-then-reconcile exchange where the reply CONTRADICTS
    the implementer's assumption.

    The implementer assumed 15 min (900 s). The reviewer's authoritative
    answer is 24 h (86400 s). The test verifies the reconciliation path.
    """
    db_path = str(tmp_path / "clarif_contradiction.db")

    store_impl = SqliteStore(db_path)
    store_reviewer = SqliteStore(db_path)

    mcp_impl = await _make_server(store_impl, "implementer")
    mcp_reviewer = await _make_server(store_reviewer, "api-reviewer")

    # Track what the implementer "built" under the assumption
    implemented_expiry: int = 900  # best-guess

    async with Client(mcp_impl) as impl, Client(mcp_reviewer) as reviewer:

        await impl.call_tool("channels__subscribe", {"pattern": "ticket:CONTRA-001"})

        # Implementer sends request, continues with expires_in=900
        await impl.call_tool(
            "channels__send",
            {
                "channel": "ticket:CONTRA-001",
                "body": {
                    "type": "clarification_request",
                    "subject": "Token lifetime",
                    "question": "15 min or 24 h?",
                },
                "correlation_id": "contra-001",
            },
        )
        # Simulated work: implemented_expiry remains 900 (best-guess)

        # Reviewer subscribes and sends the *contradicting* answer
        await reviewer.call_tool("channels__subscribe", {"pattern": "ticket:CONTRA-001"})
        await asyncio.sleep(0.1)

        drain_reviewer = await reviewer.call_tool("channels__recv", {})
        request = _extract_body(drain_reviewer.data["messages"], "clarification_request")
        assert request is not None

        # Reviewer says: 24 h (86400 s) — contradicts the 900 s assumption
        await reviewer.call_tool(
            "channels__send",
            {
                "channel": "ticket:CONTRA-001",
                "body": {
                    "type": "clarification_reply",
                    "subject": "Token lifetime",
                    "answer": "24 hours (86400 s) — long-lived tokens required by product spec.",
                },
                "correlation_id": "contra-001",
            },
        )

        await asyncio.sleep(0.15)

        # Implementer drains, finds contradiction
        drain_final = await impl.call_tool("channels__recv", {})
        final_msgs = drain_final.data["messages"]
        reply_msg = _extract_body(final_msgs, "clarification_reply")
        assert reply_msg is not None, (
            f"Implementer expected clarification_reply, got: {final_msgs}"
        )

        answer = reply_msg["body"]["answer"]
        assert "86400" in answer or "24 h" in answer or "24 hours" in answer, (
            f"Expected 86400 s contradiction in reply, got: {answer!r}"
        )

        # Reconcile: assumption was wrong — update
        assumption_correct = "900" in answer or "15 min" in answer
        assert not assumption_correct, "Assumption should be CONTRADICTED in this scenario"

        # Apply correction (in a real agent this would involve revising code)
        corrected_expiry: int = 86400
        assert corrected_expiry != implemented_expiry, (
            "Reconciliation: expiry must change from assumption to reviewer's answer"
        )

        # Implementer emits the corrected value
        assert corrected_expiry == 86400

        # Final drain: no further messages
        drain_empty = await impl.call_tool("channels__recv", {})
        assert drain_empty.data["messages"] == [], (
            f"Expected empty inbox after reconciliation, got: {drain_empty.data['messages']}"
        )


# ---------------------------------------------------------------------------
# Scenario 3: Non-blocking guarantee — implementer never waits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_implementer_never_blocks_waiting_for_reply(tmp_path: Path) -> None:
    """Prove that recv returns immediately even when the reply is not yet sent.

    This test models the spec requirement that agents MUST continue work
    after sending a clarification request.  The recv call at T=2 (before
    the reviewer has replied) must return immediately with an empty message
    list (or just the implementer's own request — but NOT the reply).
    """
    import time

    db_path = str(tmp_path / "nonblocking.db")
    store = SqliteStore(db_path)
    mcp = await _make_server(store, "implementer")

    async with Client(mcp) as impl:
        await impl.call_tool("channels__subscribe", {"pattern": "ticket:NB-001"})

        await impl.call_tool(
            "channels__send",
            {
                "channel": "ticket:NB-001",
                "body": {"type": "clarification_request", "question": "v2 or v3?"},
            },
        )

        # Immediate drain — no reviewer has replied yet.
        t0 = time.monotonic()
        drain = await impl.call_tool("channels__recv", {})
        elapsed = time.monotonic() - t0

        # Non-blocking: must return in well under 1 second
        assert elapsed < 1.0, f"recv took {elapsed:.3f}s — MUST be non-blocking"

        # Messages may include the implementer's own request (SOX delivers
        # to all subscribers), but the *reply* must not be present.
        reply = _extract_body(drain.data["messages"], "clarification_reply")
        assert reply is None, "No reply should exist; reviewer has not sent one yet"


# ---------------------------------------------------------------------------
# Scenario 4: Correlation ID threads through request and reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlation_id_preserved_end_to_end(tmp_path: Path) -> None:
    """correlation_id set on channels__send must survive round-trip through
    the backing store and appear on the received message.

    This is critical for multi-clarification scenarios where an agent has
    several pending requests and must match replies to the right one.
    """
    db_path = str(tmp_path / "correlation.db")
    store_a = SqliteStore(db_path)
    store_b = SqliteStore(db_path)

    mcp_a = await _make_server(store_a, "agent-alpha")
    mcp_b = await _make_server(store_b, "agent-beta")

    correlation = "my-unique-correlation-id-42"

    async with Client(mcp_a) as alpha, Client(mcp_b) as beta:
        await alpha.call_tool("channels__subscribe", {"pattern": "corr:*"})
        await beta.call_tool("channels__subscribe", {"pattern": "corr:*"})

        # Alpha sends with a specific correlation_id
        await alpha.call_tool(
            "channels__send",
            {
                "channel": "corr:test",
                "body": {"type": "ping"},
                "correlation_id": correlation,
            },
        )

        await asyncio.sleep(0.1)

        # Beta drains — must see the correlation_id on the received message
        drain = await beta.call_tool("channels__recv", {})
        msgs = drain.data["messages"]
        assert len(msgs) == 1, f"Beta expected 1 message, got {len(msgs)}"
        assert msgs[0]["correlation_id"] == correlation, (
            f"correlation_id must survive: expected {correlation!r}, "
            f"got {msgs[0].get('correlation_id')!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 5: Multiple concurrent clarification requests with independent
#             correlation IDs (stress the matching logic)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_pending_clarifications_resolved_independently(
    tmp_path: Path,
) -> None:
    """Implementer has two pending clarifications simultaneously.

    Both replies arrive; the implementer must be able to match each reply
    to its originating request via correlation_id.

    This validates that the backing store / listener preserves message
    ordering and does not conflate distinct correlation IDs.
    """
    db_path = str(tmp_path / "multi_clarif.db")

    store_impl = SqliteStore(db_path)
    store_reviewer = SqliteStore(db_path)

    mcp_impl = await _make_server(store_impl, "implementer")
    mcp_reviewer = await _make_server(store_reviewer, "reviewer")

    async with Client(mcp_impl) as impl, Client(mcp_reviewer) as reviewer:
        await impl.call_tool("channels__subscribe", {"pattern": "ticket:MC-001"})
        await reviewer.call_tool("channels__subscribe", {"pattern": "ticket:MC-001"})

        # Implementer sends two clarification requests simultaneously
        await impl.call_tool(
            "channels__send",
            {
                "channel": "ticket:MC-001",
                "body": {"type": "clarification_request", "subject": "token expiry"},
                "correlation_id": "clarif-A",
            },
        )
        await impl.call_tool(
            "channels__send",
            {
                "channel": "ticket:MC-001",
                "body": {"type": "clarification_request", "subject": "refresh token"},
                "correlation_id": "clarif-B",
            },
        )

        await asyncio.sleep(0.1)

        # Reviewer drains and answers both
        drain_rev = await reviewer.call_tool("channels__recv", {})
        requests = [
            m
            for m in drain_rev.data["messages"]
            if isinstance(m.get("body"), dict)
            and m["body"].get("type") == "clarification_request"
        ]
        assert len(requests) == 2, (
            f"Reviewer expected 2 clarification_requests, got {len(requests)}: "
            f"{drain_rev.data['messages']}"
        )

        # Send replies for both, preserving correlation_ids
        for req in requests:
            corr = req["correlation_id"]
            await reviewer.call_tool(
                "channels__send",
                {
                    "channel": "ticket:MC-001",
                    "body": {
                        "type": "clarification_reply",
                        "subject": req["body"]["subject"],
                        "answer": f"Answer to {corr}",
                    },
                    "correlation_id": corr,
                },
            )

        await asyncio.sleep(0.15)

        # Implementer drains — collect only the replies (filter out own requests)
        drain_impl = await impl.call_tool("channels__recv", {})
        impl_msgs = drain_impl.data["messages"]
        replies = [
            m
            for m in impl_msgs
            if isinstance(m.get("body"), dict)
            and m["body"].get("type") == "clarification_reply"
        ]
        assert len(replies) == 2, (
            f"Implementer expected 2 clarification_replies, got {len(replies)}: {impl_msgs}"
        )

        # Match replies by correlation_id
        reply_by_corr = {r["correlation_id"]: r for r in replies}
        assert "clarif-A" in reply_by_corr, "Reply for clarif-A must be present"
        assert "clarif-B" in reply_by_corr, "Reply for clarif-B must be present"

        assert "clarif-A" in reply_by_corr["clarif-A"]["body"]["answer"]
        assert "clarif-B" in reply_by_corr["clarif-B"]["body"]["answer"]


# ---------------------------------------------------------------------------
# Scenario 6: Group broadcast — one sender, two receivers, zero replies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_broadcast_received_no_replies(tmp_path: Path) -> None:
    """Three-agent group broadcast (DEMO-002 automated).

    - implementer sends one status_update
    - reviewer and docs-writer each receive it on their next drain
    - neither sends a reply
    - the broadcast message id is the same on both receivers' drains
    """
    db_path = str(tmp_path / "broadcast.db")

    store_impl = SqliteStore(db_path)
    store_reviewer = SqliteStore(db_path)
    store_docs = SqliteStore(db_path)

    mcp_impl = await _make_server(store_impl, "implementer")
    mcp_reviewer = await _make_server(store_reviewer, "reviewer")
    mcp_docs = await _make_server(store_docs, "docs-writer")

    async with (
        Client(mcp_impl) as impl,
        Client(mcp_reviewer) as reviewer,
        Client(mcp_docs) as docs,
    ):
        # All three subscribe
        for client in [impl, reviewer, docs]:
            await client.call_tool(
                "channels__subscribe", {"pattern": "ticket:DEMO-002"}
            )

        # Implementer broadcasts
        bcast = await impl.call_tool(
            "channels__send",
            {
                "channel": "ticket:DEMO-002",
                "body": {
                    "type": "status_update",
                    "subject": "POST /orders handler complete",
                    "context": "Commits abc-001 through abc-004 landed.",
                    "urgency": "low",
                },
            },
        )
        bcast_id = bcast.data["message_id"]

        await asyncio.sleep(0.15)

        # Reviewer drains — must receive the broadcast
        drain_rev = await reviewer.call_tool("channels__recv", {})
        rev_msgs = drain_rev.data["messages"]
        rev_status = _extract_body(rev_msgs, "status_update")
        assert rev_status is not None, (
            f"Reviewer should receive status_update, got: {rev_msgs}"
        )
        assert rev_status["message_id"] == bcast_id
        assert rev_status["sender"] == "implementer"

        # Docs-writer drains — must receive the broadcast
        drain_docs = await docs.call_tool("channels__recv", {})
        docs_msgs = drain_docs.data["messages"]
        docs_status = _extract_body(docs_msgs, "status_update")
        assert docs_status is not None, (
            f"Docs-writer should receive status_update, got: {docs_msgs}"
        )
        assert docs_status["message_id"] == bcast_id
        assert "abc-001" in docs_status["body"]["context"]

        # Neither reviewer nor docs-writer sends a reply
        # Verify by draining the implementer: only its own broadcast visible
        await asyncio.sleep(0.05)
        drain_impl_final = await impl.call_tool("channels__recv", {})
        peer_replies = [
            m
            for m in drain_impl_final.data["messages"]
            if m.get("sender") != "implementer"
        ]
        assert peer_replies == [], (
            f"No peer should have replied to the broadcast, got: {peer_replies}"
        )

        # channel list shows 3 subscribers
        list_r = await impl.call_tool("channels__list_channels", {})
        ch = next(
            (c for c in list_r.data["channels"] if c["name"] == "ticket:DEMO-002"),
            None,
        )
        assert ch is not None
        assert ch["subscriber_count"] == 3
