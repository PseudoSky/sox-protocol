# SPDX-License-Identifier: Apache-2.0
"""Tests for HTTP transport authentication."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.transports.http.conftest import auth_headers


@pytest.mark.asyncio
async def test_missing_auth_returns_401(client: AsyncClient) -> None:
    """POST /v1/ops/recv without Authorization returns 401."""
    resp = await client.post("/v1/ops/recv", json={})
    assert resp.status_code == 401
    data = resp.json()
    assert data["error_code"] == "missing_credential"


@pytest.mark.asyncio
async def test_valid_bearer_accepted(client: AsyncClient) -> None:
    """POST /v1/ops/recv with valid bearer token returns 200."""
    resp = await client.post(
        "/v1/ops/recv",
        json={},
        headers=auth_headers("agent-alice"),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_x_sox_agent_id_header_accepted(client: AsyncClient) -> None:
    """X-SOX-Agent-ID header is accepted as identity (conformance runner compat)."""
    resp = await client.post(
        "/v1/ops/recv",
        json={},
        headers={"X-SOX-Agent-ID": "agent-test"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sender_is_server_certified(client: AsyncClient, store) -> None:
    """The sender field in recv output is set from identity, not request body."""
    # Subscribe agent-alice
    await client.post(
        "/v1/ops/subscribe",
        json={"pattern": "test-ch"},
        headers=auth_headers("agent-alice"),
    )
    # Send as agent-alice — the body has no 'sender' field; server injects it
    await client.post(
        "/v1/ops/send",
        json={"channel": "test-ch", "body": {"text": "hello"}},
        headers=auth_headers("agent-alice"),
    )
    # Recv as agent-alice
    resp = await client.post(
        "/v1/ops/recv",
        json={},
        headers=auth_headers("agent-alice"),
    )
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "agent-alice"
