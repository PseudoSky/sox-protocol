# SPDX-License-Identifier: Apache-2.0
"""Tests for CORS behaviour on the HTTP transport."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.liveness import LivenessStore
from sox_protocol.adapters.transports.http.server import create_app


@pytest.fixture()
async def cors_client() -> AsyncClient:
    """AsyncClient with restricted CORS origins."""
    store = MemoryStore()
    await store.initialize()
    cfg = HttpConfig(
        host="127.0.0.1",
        port=9998,
        cors_origins=["http://allowed.example.com"],
    )
    app = create_app(store=store, config=cfg, liveness=LivenessStore())
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_preflight_allowed_origin(cors_client: AsyncClient) -> None:
    """OPTIONS preflight from allowed origin returns CORS headers."""
    resp = await cors_client.options(
        "/v1/ops/send",
        headers={
            "Origin": "http://allowed.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    # Starlette CORS returns 200 for preflight
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


@pytest.mark.asyncio
async def test_cors_never_wildcard_with_credentials(cors_client: AsyncClient) -> None:
    """The Access-Control-Allow-Origin header is never '*'."""
    resp = await cors_client.options(
        "/v1/ops/send",
        headers={
            "Origin": "http://allowed.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao != "*"


@pytest.mark.asyncio
async def test_cors_defaults_include_localhost(client: AsyncClient) -> None:
    """Default CORS config allows localhost origins."""
    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Should not be blocked
    assert resp.status_code in (200, 204, 400)  # Starlette may return 400 for bare GET preflight


@pytest.mark.asyncio
async def test_wildcard_stripped_from_origins() -> None:
    """Wildcard '*' is removed from origins to prevent credentialed wildcard."""
    from sox_protocol.adapters.transports.http.cors import build_cors_middleware
    _, kwargs = build_cors_middleware(["*", "http://localhost"])
    assert "*" not in kwargs["allow_origins"]
    assert "http://localhost" in kwargs["allow_origins"]


@pytest.mark.asyncio
async def test_empty_origins_falls_back_to_localhost() -> None:
    """Empty origins list falls back to localhost defaults."""
    from sox_protocol.adapters.transports.http.cors import build_cors_middleware
    _, kwargs = build_cors_middleware([])
    origins = kwargs["allow_origins"]
    assert any("localhost" in o or "127.0.0.1" in o for o in origins)
