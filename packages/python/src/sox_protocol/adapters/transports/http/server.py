# SPDX-License-Identifier: Apache-2.0
"""FastAPI application factory for the SOX HTTP transport.

Creates and wires together:
- Operation routes (``/v1/ops/<operation>``)
- SSE stream (``GET /v1/stream``)
- Health probe (``GET /health``)
- CORS middleware
- Identity resolver

Spec reference: ``spec/ports/transport.md §2, §4``
"""

from __future__ import annotations

import time

from fastapi import APIRouter, FastAPI

from sox_protocol.adapters.transports.http.auth import (
    IdentityResolver,
    PassthroughIdentityResolver,
)
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.cors import build_cors_middleware
from sox_protocol.adapters.transports.http.health import health_router
from sox_protocol.adapters.transports.http.liveness import LivenessStore
from sox_protocol.adapters.transports.http.routes import register_operation_routes
from sox_protocol.adapters.transports.http.sse import build_sse_router
from sox_protocol.core.ports.backing_store import BackingStore

_PROTOCOL_VERSION = "1.0"


def create_app(
    store: BackingStore,
    identity: IdentityResolver | None = None,
    config: HttpConfig | None = None,
    liveness: LivenessStore | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        store: The backing store instance.
        identity: Identity resolver (defaults to passthrough for dev).
        config: HTTP configuration (defaults to env-derived config).
        liveness: Liveness store for heartbeat tracking (defaults to new instance).

    Returns:
        A fully configured :class:`FastAPI` application.
    """
    if config is None:
        config = HttpConfig.from_env()
    if identity is None:
        identity = PassthroughIdentityResolver()
    if liveness is None:
        liveness = LivenessStore()

    app = FastAPI(
        title="SOX Protocol HTTP Transport",
        version=_PROTOCOL_VERSION,
        docs_url="/docs",
        redoc_url=None,
    )

    # CORS — must be added before routes
    cors_cls, cors_kwargs = build_cors_middleware(config.cors_origins)
    app.add_middleware(cors_cls, **cors_kwargs)  # type: ignore[arg-type]

    # Health router (no auth)
    app.include_router(health_router)

    # Operation routes
    ops_router = APIRouter()
    register_operation_routes(ops_router, store, identity)
    app.include_router(ops_router)

    # SSE stream router
    sse_router = build_sse_router(store, identity)
    app.include_router(sse_router)

    # Store references on app.state for testing / inspection
    app.state.store = store
    app.state.identity = identity
    app.state.config = config
    app.state.liveness = liveness
    app.state.started_at = time.time()

    return app


class HttpTransport:
    """Lifecycle wrapper for the SOX HTTP transport.

    Wires together the FastAPI app, uvicorn server, and backing store.

    Args:
        store: The backing store instance.
        identity: Identity resolver.
        config: HTTP configuration.
        liveness: Liveness store.
    """

    def __init__(
        self,
        store: BackingStore,
        identity: IdentityResolver | None = None,
        config: HttpConfig | None = None,
        liveness: LivenessStore | None = None,
    ) -> None:
        self._store = store
        self._identity = identity or PassthroughIdentityResolver()
        self._config = config or HttpConfig.from_env()
        self._liveness = liveness or LivenessStore()
        self._app: FastAPI | None = None

    def build(self) -> FastAPI:
        """Build the FastAPI application.

        Returns:
            The configured :class:`FastAPI` instance.
        """
        self._app = create_app(
            self._store,
            self._identity,
            self._config,
            self._liveness,
        )
        return self._app

    @property
    def app(self) -> FastAPI:
        """Return the FastAPI application, building if necessary.

        Returns:
            The configured :class:`FastAPI` instance.
        """
        if self._app is None:
            return self.build()
        return self._app

    def run(self) -> None:
        """Start the uvicorn server synchronously (blocks until shutdown).

        Raises:
            ImportError: If uvicorn is not installed.
        """
        import uvicorn

        uvicorn.run(
            self.app,
            host=self._config.host,
            port=self._config.port,
            log_level="info",
        )
