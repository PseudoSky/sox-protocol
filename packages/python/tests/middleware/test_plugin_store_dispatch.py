# SPDX-License-Identifier: Apache-2.0
"""Tests for StoreDispatchMiddleware.

Spec reference: ``spec/ports/middleware.md §4 (store_dispatch)``
"""

from __future__ import annotations

import pytest

from sox_protocol.core.middleware.pipeline import Pipeline
from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware
from tests.middleware.conftest import StubBackingStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline(store: StubBackingStore) -> Pipeline:
    mw = StoreDispatchMiddleware(store)
    return Pipeline([mw], mw)


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_dispatch_send(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "send",
        {
            "channel": "test-ch",
            "sender": "alice",
            "body": {"type": "ping"},
            "correlation_id": "corr-1",
        },
        connection_id="c",
    )

    assert "message_id" in result
    assert result["channel"] == "test-ch"
    assert "sent_at" in result


@pytest.mark.asyncio
async def test_store_dispatch_send_without_correlation_id(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "send",
        {"channel": "ch", "sender": "alice", "body": {}},
        connection_id="c",
    )
    assert "message_id" in result


@pytest.mark.asyncio
async def test_store_dispatch_send_non_dict_body_coerced(stub_store: StubBackingStore) -> None:
    """Non-dict body is silently coerced to {}."""
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "send",
        {"channel": "ch", "sender": "alice", "body": "not-a-dict"},
        connection_id="c",
    )
    assert "message_id" in result


# ---------------------------------------------------------------------------
# recv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_dispatch_recv(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "recv",
        {"agent_id": "alice"},
        connection_id="c",
    )

    assert "drained_at" in result
    assert result["messages"] == []


@pytest.mark.asyncio
async def test_store_dispatch_recv_with_channels(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "recv",
        {"agent_id": "alice", "channels": ["ch1", "ch2"], "max_messages": 10},
        connection_id="c",
    )
    assert "messages" in result


@pytest.mark.asyncio
async def test_store_dispatch_recv_max_messages_non_numeric_defaults_to_50(
    stub_store: StubBackingStore,
) -> None:
    """Non-numeric max_messages falls back to 50."""
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "recv",
        {"agent_id": "alice", "max_messages": []},  # not int/float/str
        connection_id="c",
    )
    assert "messages" in result


@pytest.mark.asyncio
async def test_store_dispatch_recv_preserves_existing_seq(
    stub_store: StubBackingStore,
) -> None:
    """Recv does NOT overwrite seq when the backing store already provides it."""

    async def _patched_recv(
        agent_id: str,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> list[dict[str, object]]:
        return [
            {
                "channel": "ch",
                "sender": "alice",
                "body": {},
                "message_id": "1",
                "sent_at": 0.0,
                "seq": 99,
            }
        ]

    stub_store.recv = _patched_recv  # type: ignore[method-assign]

    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch("recv", {"agent_id": "alice"}, connection_id="c")
    msgs = result["messages"]
    assert isinstance(msgs, list)
    assert msgs[0]["seq"] == 99  # original seq preserved


@pytest.mark.asyncio
async def test_store_dispatch_recv_adds_seq(stub_store: StubBackingStore) -> None:
    """Recv adds seq number if backing store didn't include one."""

    async def _patched_recv(
        agent_id: str,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> list[dict[str, object]]:
        return [
            {
                "channel": "ch",
                "sender": "alice",
                "body": {},
                "message_id": "1",
                "sent_at": 0.0,
            }
        ]

    stub_store.recv = _patched_recv  # type: ignore[method-assign]

    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch("recv", {"agent_id": "alice"}, connection_id="c")
    msgs = result["messages"]
    assert isinstance(msgs, list)
    assert msgs[0]["seq"] == 1


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_dispatch_subscribe(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "subscribe",
        {"agent_id": "alice", "pattern": "test:*"},
        connection_id="c",
    )

    assert result["subscribed"] is True
    assert "matched_channels" in result


# ---------------------------------------------------------------------------
# list_channels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_dispatch_list_channels(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "list_channels",
        {},
        connection_id="c",
    )

    assert "channels" in result


@pytest.mark.asyncio
async def test_store_dispatch_list_channels_with_since(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "list_channels",
        {"since": 1_700_000_000.0},
        connection_id="c",
    )
    assert "channels" in result


# ---------------------------------------------------------------------------
# Unsupported operation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_dispatch_unsupported_operation(stub_store: StubBackingStore) -> None:
    pipeline = _make_pipeline(stub_store)
    result = await pipeline.dispatch(
        "unknown_future_op",  # not a known v1 operation
        {},
        connection_id="c",
    )
    assert result["error_code"] == "internal_error"


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def test_store_dispatch_name(stub_store: StubBackingStore) -> None:
    mw = StoreDispatchMiddleware(stub_store)
    assert mw.name == "store_dispatch"
