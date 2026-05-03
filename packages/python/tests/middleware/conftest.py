# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures for the middleware test suite."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest

from sox_protocol.core.identity.audit import AuditLogWriter
from sox_protocol.core.identity.envelope import SignedRequest, compute_body_hash
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.registry import InMemoryCredentialRegistry
from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.ports.backing_store import BackingStore, BackpressureInfo

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubBackingStore(BackingStore):
    """Minimal in-memory backing store for middleware tests."""

    schema_version = "1.0"

    def __init__(self) -> None:
        self._messages: list[dict[str, object]] = []
        self._subscriptions: dict[str, list[str]] = {}
        self._next_seq: int = 1

    async def send(
        self,
        channel: str,
        sender: str,
        body: dict[str, object],
        correlation_id: str | None = None,
        *,
        reply_to: str | None = None,
    ) -> tuple[str, float, int, BackpressureInfo]:
        import time

        msg_id = str(self._next_seq)
        seq = self._next_seq
        self._next_seq += 1
        sent_at = time.time()
        self._messages.append(
            {
                "message_id": msg_id,
                "channel": channel,
                "sender": sender,
                "body": body,
                "correlation_id": correlation_id,
                "sent_at": sent_at,
                "seq": seq,
                "reply_to": reply_to,
            }
        )
        return (msg_id, sent_at, seq, BackpressureInfo(queue_depth=0, threshold=1000, state="ok"))

    async def recv(
        self,
        agent_id: str,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> list[dict[str, object]]:
        return []

    async def subscribe(self, agent_id: str, pattern: str) -> list[str]:
        self._subscriptions.setdefault(agent_id, []).append(pattern)
        return []

    async def list_channels(self, since: float | None = None) -> list[dict[str, object]]:
        return []

    async def watch(self, agent_id: str) -> AsyncIterator[dict[str, object]]:
        return
        yield  # make it an async generator  # noqa: unreachable

    async def unsubscribe(self, agent_id: str, patterns: list[str]) -> tuple[list[str], int]:
        existing = self._subscriptions.get(agent_id, [])
        removed = [p for p in existing if p in patterns]
        self._subscriptions[agent_id] = [p for p in existing if p not in patterns]
        return (removed, 0)

    async def ack(self, agent_id: str, message_id: str, status: str, reason: str | None = None) -> dict[str, object]:
        import time
        return {"message_id": message_id, "status": status, "acked_at": time.time()}

    async def heartbeat(self, agent_id: str, status: str, ttl: int | None = None) -> dict[str, object]:
        import time
        now = time.time()
        return {"agent_id": agent_id, "status": status, "recorded_at": now, "expires_at": now + (ttl or 30)}

    async def list_agents(self, status_filter: list[str] | None = None, namespace: str | None = None) -> list[dict[str, object]]:
        return []

    async def replay(self, channel: str, since: int = 0, until: int | None = None, limit: int = 100) -> tuple[list[dict[str, object]], bool]:
        return ([], False)

    async def group_create(self, creator_id: str, group_id: str | None = None) -> dict[str, object]:
        import time
        return {"group_id": f"group/{group_id or 'grp'}", "created_at": time.time()}

    async def group_invite(self, inviter_id: str, group_id: str, invitee_id: str) -> dict[str, object]:
        import time
        return {"invited": True, "agent_id": invitee_id, "invited_at": time.time()}

    async def group_join(self, agent_id: str, group_id: str) -> dict[str, object]:
        import time
        return {"joined": True, "group_id": group_id, "member_count": 1, "joined_at": time.time()}

    async def group_leave(self, agent_id: str, group_id: str) -> dict[str, object]:
        import time
        return {"left": True, "group_id": group_id, "left_at": time.time()}

    async def group_list_members(self, agent_id: str, group_id: str) -> dict[str, object]:
        return {"group_id": group_id, "members": []}


class RecordingMiddleware:
    """Middleware that records calls and passes through."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()
        self.calls: list[str] = []
        self.response_calls: list[str] = []

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        self.calls.append(ctx.operation)
        response = await call_next(ctx)
        self.response_calls.append(ctx.operation)
        return response


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@pytest.fixture
def fixed_clock() -> Callable[[], float]:
    """A deterministic clock always returning the same timestamp."""
    return lambda: 1_700_000_000.0


# ---------------------------------------------------------------------------
# Backing store
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_store() -> StubBackingStore:
    """A fresh StubBackingStore per test."""
    return StubBackingStore()


# ---------------------------------------------------------------------------
# Identity fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    """Temporary audit log path."""
    return tmp_path / "identity-failures.jsonl"


@pytest.fixture
def audit_writer(audit_path: Path, fixed_clock: Callable[[], float]) -> AuditLogWriter:
    """AuditLogWriter writing to tmp path."""
    return AuditLogWriter(path=audit_path, clock=fixed_clock)


@pytest.fixture
def registry(fixed_clock: Callable[[], float]) -> InMemoryCredentialRegistry:
    """Fresh InMemoryCredentialRegistry."""
    return InMemoryCredentialRegistry(clock=fixed_clock)


@pytest.fixture
def sample_keypair() -> tuple[bytes, bytes]:
    """Freshly generated (private_seed, public_key) pair."""
    return generate_keypair()


@pytest.fixture
def verifier(
    registry: InMemoryCredentialRegistry,
    audit_writer: AuditLogWriter,
    fixed_clock: Callable[[], float],
) -> IdentityVerifier:
    """IdentityVerifier backed by tmp registry and audit writer."""
    return IdentityVerifier(
        registry,
        audit_writer,
        replay_window_seconds=300.0,
        clock=fixed_clock,
    )


@pytest.fixture
def sign_request(
    sample_keypair: tuple[bytes, bytes],
) -> Callable[..., SignedRequest]:
    """Return a helper that builds a valid SignedRequest from kwargs."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from sox_protocol.core.identity.envelope import canonical_payload

    private_seed, _pub = sample_keypair

    def _build(
        *,
        agent_id: str = "alice",
        method: str = "send",
        body: dict[str, object] | None = None,
        nonce: str | None = None,
        timestamp: float = 1_700_000_000.0,
        private_seed_override: bytes | None = None,
    ) -> SignedRequest:
        if body is None:
            body = {"channel": "test"}
        seed = private_seed_override if private_seed_override is not None else private_seed
        pk = Ed25519PrivateKey.from_private_bytes(seed)
        body_hash = compute_body_hash(body)
        actual_nonce = nonce if nonce is not None else uuid.uuid4().hex
        req = SignedRequest(
            agent_id=agent_id,
            nonce=actual_nonce,
            timestamp=timestamp,
            method=method,
            body_hash=body_hash,
            signature=b"",
        )
        payload = canonical_payload(req)
        sig = pk.sign(payload)
        return SignedRequest(
            agent_id=agent_id,
            nonce=actual_nonce,
            timestamp=timestamp,
            method=method,
            body_hash=body_hash,
            signature=sig,
        )

    return _build


# ---------------------------------------------------------------------------
# Middleware log path
# ---------------------------------------------------------------------------


@pytest.fixture
def middleware_log_path(tmp_path: Path) -> Path:
    """Temporary path for the logging middleware JSONL output."""
    return tmp_path / "middleware.jsonl"


# ---------------------------------------------------------------------------
# MiddlewareContext helper
# ---------------------------------------------------------------------------


@pytest.fixture
def make_ctx() -> Callable[..., MiddlewareContext]:
    """Return a helper for constructing MiddlewareContext instances."""

    def _build(
        *,
        operation: str = "send",
        input: dict[str, object] | None = None,
        connection_id: str = "conn-test",
    ) -> MiddlewareContext:
        return MiddlewareContext(
            operation=operation,
            input=input or {},
            connection_id=connection_id,
        )

    return _build
