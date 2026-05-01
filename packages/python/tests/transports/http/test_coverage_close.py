# SPDX-License-Identifier: Apache-2.0
"""HTTP route validation_error path tests for coverage closure.

Companion to tests/test_coverage_close.py. These tests live here so they
inherit the http conftest fixtures (auth + ASGI client).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.transports.http.conftest import auth_headers


@pytest.mark.asyncio
async def test_route_recv_validation_error(client: AsyncClient) -> None:
    """routes.py line 259: recv invalid body → validation_error."""
    resp = await client.post(
        "/v1/ops/recv",
        json={"max_messages": "not-an-int"},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_route_subscribe_wildcard_rejected(client: AsyncClient) -> None:
    """routes.py line 295: wildcard pattern returns validation_error."""
    resp = await client.post(
        "/v1/ops/subscribe",
        json={"pattern": "dm/*"},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_route_list_channels_validation_error(client: AsyncClient) -> None:
    """routes.py line 359: list_channels invalid body → validation_error."""
    resp = await client.post(
        "/v1/ops/list_channels",
        json={"since": "not-a-float"},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_route_list_agents_validation_error(client: AsyncClient) -> None:
    """routes.py line 535: list_agents invalid body → validation_error."""
    resp = await client.post(
        "/v1/ops/list_agents",
        json={"status_filter": "should-be-a-list"},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_route_group_create_validation_error(client: AsyncClient) -> None:
    """routes.py line 563: group_create invalid body → validation_error."""
    resp = await client.post(
        "/v1/ops/group_create",
        json={"group_id": 123},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "validation_error"
