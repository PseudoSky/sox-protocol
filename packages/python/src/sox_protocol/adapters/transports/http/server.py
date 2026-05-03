# SPDX-License-Identifier: Apache-2.0
"""FastAPI application factory for the SOX HTTP transport.

Creates and wires together:
- Operation routes (``/v1/ops/<operation>``)
- SSE stream (``GET /v1/stream``)
- Health probe (``GET /health``)
- CORS middleware
- Middleware pipeline (AuthMiddleware → StoreDispatchMiddleware)

Phase 03-build-http: ``create_app`` now accepts ``pipeline`` (optional; built
internally from *store* if not supplied).  ``PassthroughIdentityResolver`` and
``IdentityResolver`` removed.  ``register_operation_routes`` now receives
``pipeline`` + ``private_key`` instead of ``store`` + ``resolver``.
``build_sse_router`` receives ``store`` only (SSE is read-only in v1).

v1 transitional identity model
--------------------------------
At ``create_app`` time an ephemeral Ed25519 keypair is generated.  Agents that
arrive with a bearer token (== agent_id) are auto-registered in the in-memory
credential registry under that keypair.  ``AuthMiddleware`` then performs real
cryptographic verification of the per-request :class:`SignedRequest` envelope
built by :func:`~sox_protocol.adapters.transports.http._credential.resolve_credential`.

v1.1 will require agents to pre-register via a manifest or CLI tool and will
accept a real ``X-Sox-Signed-Request`` header alongside the bearer token.

Spec reference: ``spec/ports/transport.md §2, §4``
"""

from __future__ import annotations

import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, FastAPI

from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.cors import build_cors_middleware
from sox_protocol.adapters.transports.http.health import health_router
from sox_protocol.adapters.transports.http.liveness import LivenessStore
from sox_protocol.adapters.transports.http.routes import register_operation_routes
from sox_protocol.adapters.transports.http.sse import build_sse_router
from sox_protocol.core.identity import AuditLogWriter, InMemoryCredentialRegistry
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.middleware import Pipeline, build_default_pipeline, extend_pipeline_with_registry
from sox_protocol.core.middleware.errors import PluginStartupError
from sox_protocol.core.middleware.registry import register_middleware
from sox_protocol.core.ports.backing_store import BackingStore

_PROTOCOL_VERSION = "1.0"

# Host protocol version for plugin compatibility checks.
_HOST_PROTOCOL_VERSION = "1.0.0"


def _build_identity_stack(
    store: BackingStore,
) -> tuple[Pipeline, IdentityVerifier, InMemoryCredentialRegistry, Ed25519PrivateKey]:
    """Build the identity stack and pipeline for a given backing store.

    Generates an ephemeral Ed25519 keypair (v1 transitional; see module
    docstring).  The caller must register agents via
    :func:`ensure_agent_registered` before their first request reaches
    ``AuthMiddleware``.

    Args:
        store: The backing store to wrap in ``StoreDispatchMiddleware``.

    Returns:
        A 4-tuple ``(pipeline, verifier, registry, private_key)``.
    """
    registry = InMemoryCredentialRegistry()
    audit = AuditLogWriter()
    verifier = IdentityVerifier(registry=registry, audit=audit)
    private_seed, public_key_bytes = generate_keypair()
    private_key: Ed25519PrivateKey = Ed25519PrivateKey.from_private_bytes(private_seed)
    pipeline = build_default_pipeline(verifier=verifier, store=store)
    return pipeline, verifier, registry, private_key


def create_app(
    store: BackingStore,
    pipeline: Pipeline | None = None,
    *,
    config: HttpConfig | None = None,
    liveness: LivenessStore | None = None,
    # Deprecated in 03-build-http — ignored if present, kept for call-site
    # backward compatibility during the test migration window.
    identity: object | None = None,
    # Plugin discovery parameters (phase 04-bootstrap-integration).
    # Defaults preserve existing behaviour when not supplied (dev mode,
    # no explicit allowlist, discovery enabled).
    allowlist: list[str] | None = None,
    env: str = "dev",
    no_discovery: bool = False,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        store: The backing store instance.
        pipeline: Optional pre-built pipeline.  If ``None``, one is built
            internally via ``build_default_pipeline`` with a freshly generated
            ephemeral Ed25519 keypair and an in-memory credential registry.
        config: HTTP configuration (defaults to env-derived config).
        liveness: Liveness store for heartbeat tracking (defaults to new instance).
        identity: Deprecated — ignored.  Kept for call-site backward
            compatibility during the test migration window; will be removed in
            v1.1.  Pass ``pipeline`` instead.
        allowlist: Plugin ids that are permitted to load.  ``None`` means
            "no explicit allowlist provided" (dev: load all; production:
            refuse all).  When ``None``, ``SOX_ALLOWED_PLUGINS`` env var is
            also consulted so that the CLI path (which sets env vars before
            calling ``create_app``) works transparently.
        env: Runtime environment string.  ``"production"`` activates strict
            allowlist enforcement.  Defaults to ``"dev"``.  Also reads
            ``SOX_ENV`` env var when left at its default.
        no_discovery: When ``True``, skip all plugin discovery.  Also reads
            ``SOX_NO_DISCOVERY`` env var when left at its default (``False``).

    Returns:
        A fully configured :class:`FastAPI` application.
    """
    if config is None:
        config = HttpConfig.from_env()
    if liveness is None:
        liveness = LivenessStore()

    # Build identity stack + pipeline if caller didn't supply one.
    built_pipeline: Pipeline
    built_registry: InMemoryCredentialRegistry
    built_private_key: Ed25519PrivateKey
    if pipeline is None:
        built_pipeline, _verifier, built_registry, built_private_key = (
            _build_identity_stack(store)
        )
    else:
        # Caller supplied a pre-built pipeline.  We still need a fresh identity
        # stack (registry + private_key) for per-request credential signing and
        # auto-registration, but we DISCARD the pipeline from _build_identity_stack
        # and use the caller-supplied one.  The caller's pipeline must use a
        # verifier whose registry accepts registrations from *built_registry* —
        # this is the caller's responsibility.  For test scenarios that supply a
        # custom pipeline, the auto-registration ensures callers using the default
        # bearer-token path can still complete auth successfully.
        _, _verifier2, built_registry, built_private_key = _build_identity_stack(store)
        built_pipeline = pipeline

    # 4b. Discover and load out-of-tree plugins, then extend the pipeline.
    #     Resolve env/allowlist/no_discovery from kwargs first, falling back
    #     to env vars written by cli/serve.py _resolve_plugin_env.
    import os as _os  # noqa: PLC0415 (deferred to avoid top-level os import conflict)

    _resolved_env = env if env != "dev" else _os.environ.get("SOX_ENV", "dev")
    _raw_allowlist = _os.environ.get("SOX_ALLOWED_PLUGINS", "")
    _resolved_allowlist: list[str] | None = allowlist
    if _resolved_allowlist is None and _raw_allowlist:
        _resolved_allowlist = [p for p in _raw_allowlist.split(",") if p]
    _resolved_no_discovery = no_discovery or (_os.environ.get("SOX_NO_DISCOVERY", "") == "1")

    try:
        register_middleware.load_plugins(
            allowlist=_resolved_allowlist,
            env=_resolved_env,
            host_protocol_version=_HOST_PROTOCOL_VERSION,
            no_discovery=_resolved_no_discovery,
        )
    except PluginStartupError as _exc:
        import sys as _sys  # noqa: PLC0415
        import logging as _logging  # noqa: PLC0415
        _plog = _logging.getLogger(__name__)
        _envelope = _exc.to_envelope()
        _plog.error(
            "[sox] HTTP plugin startup failed: %s",
            _envelope,
            extra={"sox_error_envelope": _envelope},
        )
        print(
            f"[sox] ERROR: HTTP plugin startup failed — {_envelope}",
            file=_sys.stderr,
        )
        raise

    if register_middleware.resolved_order:
        from sox_protocol.core.middleware.default_chain import _StoreTerminal  # noqa: PLC0415
        from sox_protocol.core.middleware.plugins.store_dispatch import (  # noqa: PLC0415
            StoreDispatchMiddleware,
        )
        import logging as _logging2  # noqa: PLC0415
        _plog2 = _logging2.getLogger(__name__)
        _store_terminal = _StoreTerminal(StoreDispatchMiddleware(store))
        built_pipeline = extend_pipeline_with_registry(
            built_pipeline, register_middleware, _store_terminal
        )
        _plog2.info(
            "[sox] HTTP pipeline extended with %d plugin(s): %s",
            len(register_middleware.resolved_order),
            list(register_middleware.resolved_order),
        )

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

    # Pre-registration via env var (per analysis §7.8 v1 deferred decision):
    # If SOX_PRE_REGISTERED_AGENTS is set in the environment AT ALL (even
    # empty value), strict mode is enabled: the listed agents are
    # pre-registered with the server's keypair and auto-registration is
    # DISABLED. Unknown bearer tokens fall through to AuthMiddleware unmapped
    # → identity_failure envelope. This is how the conformance harness
    # achieves server-side rejection of unknown-credential fixtures without
    # client-side substitution. Production deploys SHOULD set this in
    # production; absence means dev-mode auto-register-on-arrival (legacy v1
    # bearer-as-agent-id behavior).
    import os as _os
    auto_register = True
    if "SOX_PRE_REGISTERED_AGENTS" in _os.environ:
        auto_register = False
        _pre_reg = _os.environ["SOX_PRE_REGISTERED_AGENTS"].strip()
        if _pre_reg:
            # Synchronous registration via a temporary event loop, since
            # InMemoryCredentialRegistry.register is async. All agents share
            # the server's public key — same as the auto-register path — so
            # AuthMiddleware verification is unchanged; only the *gate* on
            # who-can-be-an-agent moves from "any token" to "this allowlist".
            import asyncio as _asyncio
            _public_key_bytes = built_private_key.public_key().public_bytes_raw()
            async def _bootstrap_registry() -> None:
                for _agent_id in (a.strip() for a in _pre_reg.split(",") if a.strip()):
                    await built_registry.register(_agent_id, _public_key_bytes)
            _asyncio.run(_bootstrap_registry())

    # Operation routes — dispatched through pipeline
    ops_router = APIRouter()
    register_operation_routes(
        ops_router, built_pipeline, built_private_key, built_registry,
        auto_register=auto_register,
    )
    app.include_router(ops_router)

    # SSE stream router — read-only, uses store.watch directly
    sse_router = build_sse_router(store)
    app.include_router(sse_router)

    # Store references on app.state for testing / inspection
    app.state.store = store
    app.state.pipeline = built_pipeline
    app.state.registry = built_registry
    app.state._private_key = built_private_key
    app.state.config = config
    app.state.liveness = liveness
    app.state.started_at = time.time()

    return app


# Back-compat alias (per implementation-plan.json §P1 outputs).
build_app = create_app


class HttpTransport:
    """Lifecycle wrapper for the SOX HTTP transport.

    Wires together the FastAPI app, uvicorn server, and backing store.

    Args:
        store: The backing store instance.
        pipeline: Optional pre-built pipeline.  If ``None``, one is built
            internally at :meth:`build` time.
        config: HTTP configuration.
        liveness: Liveness store.
        identity: Deprecated — ignored.  Kept for call-site backward
            compatibility during the test migration window.
    """

    def __init__(
        self,
        store: BackingStore,
        pipeline: Pipeline | None = None,
        *,
        config: HttpConfig | None = None,
        liveness: LivenessStore | None = None,
        # Deprecated — ignored.
        identity: object | None = None,
    ) -> None:
        self._store = store
        self._pipeline = pipeline
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
            self._pipeline,
            config=self._config,
            liveness=self._liveness,
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
