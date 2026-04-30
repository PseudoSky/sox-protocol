# SPDX-License-Identifier: Apache-2.0
"""Tests for GET /health endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /health returns 200 with protocol_version field."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["protocol_version"] == "1.0"
    assert data["store_ok"] is True
    assert isinstance(data["uptime_s"], float)


@pytest.mark.asyncio
async def test_health_no_auth_required(client: AsyncClient) -> None:
    """GET /health does not require an Authorization header."""
    resp = await client.get("/health")
    assert resp.status_code == 200
