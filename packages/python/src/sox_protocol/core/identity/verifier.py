# SPDX-License-Identifier: Apache-2.0
"""Identity verifier: glues registry, envelope, replay cache, and audit log.

:class:`IdentityVerifier` is the primary callable consumed by the middleware
pipeline.  It verifies a :class:`~sox_protocol.core.identity.envelope.SignedRequest`
and either returns a :class:`~sox_protocol.core.identity.envelope.VerifiedIdentity`
or raises a typed :class:`~sox_protocol.core.identity.errors.IdentityFailure`.

After a successful verification, :meth:`IdentityVerifier.bind_for_send` rewrites
the ``sender`` field in the send-input dict with the server-certified identity,
satisfying ``spec/ports/identity.md §2`` (the server MUST overwrite the sender).

Spec reference: ``spec/ports/identity.md §2, §4, §5``
"""

from __future__ import annotations

import time as _time_module
from collections.abc import Callable

from sox_protocol.core.identity.audit import AuditLogWriter
from sox_protocol.core.identity.envelope import (
    SignedRequest,
    VerifiedIdentity,
    canonical_payload,
)
from sox_protocol.core.identity.errors import (
    IdentityFailure,
    MalformedRequestError,
    ReplayDetectedError,
    RevokedCredentialError,
    SignatureMismatchError,
    UnknownAgentError,
)
from sox_protocol.core.identity.keys import verify_signature
from sox_protocol.core.identity.registry import CredentialRegistry


class IdentityVerifier:
    """Verify signed requests and bind the certified identity into send inputs.

    Instantiate once (per server) and share across requests.  Internal state
    (the nonce replay cache) is protected against concurrent coroutines by
    design: each ``verify`` call is atomic from the perspective of the cache
    check-and-insert.

    Args:
        registry: The credential registry that holds ``(agent_id, public_key)``
            records.
        audit: Writer for identity-failure audit events
            (``spec/ports/identity.md §5``).
        replay_window_seconds: How long a nonce is considered "seen".  Default
            is 300 s (5 minutes) per ADR 0002 open question.  Configure via
            constructor to allow future ADR pinning without API change.
        clock: Callable returning the current Unix epoch seconds.  Defaults to
            :func:`time.time`.  Injectable for deterministic tests.
    """

    def __init__(
        self,
        registry: CredentialRegistry,
        audit: AuditLogWriter,
        *,
        replay_window_seconds: float = 300.0,
        clock: Callable[[], float] = _time_module.time,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._replay_window = replay_window_seconds
        self._clock = clock
        # Replay cache: nonce -> timestamp_seen.  TTL-pruned on every verify.
        self._seen_nonces: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune_replay_cache(self, now: float) -> None:
        """Evict expired nonces from the replay cache."""
        cutoff = now - self._replay_window
        expired = [n for n, ts in self._seen_nonces.items() if ts < cutoff]
        for n in expired:
            del self._seen_nonces[n]

    async def _fail(
        self,
        exc: IdentityFailure,
        *,
        claimed_agent_id: str | None,
        operation: str,
        connection_id: str | None,
    ) -> None:
        """Log the failure and re-raise *exc*."""
        await self._audit.record_failure(
            claimed_agent_id=claimed_agent_id,
            reason=exc.reason,
            operation=operation,
            connection_id=connection_id,
        )
        raise exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def verify(
        self,
        request: SignedRequest,
        *,
        operation: str,
        connection_id: str | None = None,
    ) -> VerifiedIdentity:
        """Verify *request* and return a :class:`VerifiedIdentity` on success.

        Verification steps (in order):

        1. Structural validation — empty ``agent_id`` or ``nonce`` are rejected.
        2. Timestamp freshness — ``|now - request.timestamp| <= replay_window``.
        3. Registry lookup — unknown agent raises :class:`UnknownAgentError`.
        4. Revocation check — revoked credential raises :class:`RevokedCredentialError`.
        5. Replay check — duplicate nonce within window raises :class:`ReplayDetectedError`.
        6. Signature verification — bad signature raises :class:`SignatureMismatchError`.

        On any failure, an audit line is written and the exception is raised.
        No partial state is mutated on failure (the replay cache is only updated
        on success).

        Args:
            request: The signed-request envelope presented by the caller.
            operation: The SOX operation name (e.g. ``"send"``).
            connection_id: Opaque connection identifier from the transport layer.

        Returns:
            A :class:`VerifiedIdentity` with the server-certified ``agent_id``.

        Raises:
            MalformedRequestError: Structurally invalid envelope.
            UnknownAgentError: Agent not in registry.
            RevokedCredentialError: Agent is revoked.
            ReplayDetectedError: Nonce seen within replay window.
            SignatureMismatchError: Signature does not verify.
        """
        now = self._clock()

        # 1. Structural validation.
        if not request.agent_id:
            exc = MalformedRequestError("agent_id must be non-empty")
            await self._fail(
                exc, claimed_agent_id=None, operation=operation, connection_id=connection_id
            )

        if not request.nonce:
            exc2 = MalformedRequestError("nonce must be non-empty")
            await self._fail(
                exc2,
                claimed_agent_id=request.agent_id,
                operation=operation,
                connection_id=connection_id,
            )

        # 2. Timestamp freshness.
        age = abs(now - request.timestamp)
        if age > self._replay_window:
            exc3 = MalformedRequestError(
                f"Request timestamp is outside replay window "
                f"(age={age:.1f}s, window={self._replay_window}s)"
            )
            await self._fail(
                exc3,
                claimed_agent_id=request.agent_id,
                operation=operation,
                connection_id=connection_id,
            )

        # 3. Registry lookup — use a neutral error message to avoid info leakage.
        record = await self._registry.lookup(request.agent_id)
        if record is None:
            exc4 = UnknownAgentError("Identity verification failed")
            await self._fail(
                exc4,
                claimed_agent_id=request.agent_id,
                operation=operation,
                connection_id=connection_id,
            )
            raise exc4  # pragma: no cover — _fail always raises

        # 4. Revocation.
        if record.is_revoked:
            exc5 = RevokedCredentialError("Identity verification failed")
            await self._fail(
                exc5,
                claimed_agent_id=request.agent_id,
                operation=operation,
                connection_id=connection_id,
            )
            raise exc5  # pragma: no cover — _fail always raises

        # 5. Replay check (prune first to clean up stale entries).
        self._prune_replay_cache(now)
        if request.nonce in self._seen_nonces:
            exc6 = ReplayDetectedError("Duplicate nonce within replay window")
            await self._fail(
                exc6,
                claimed_agent_id=request.agent_id,
                operation=operation,
                connection_id=connection_id,
            )
            raise exc6  # pragma: no cover — _fail always raises

        # 6. Signature verification.
        payload = canonical_payload(request)
        if not verify_signature(record.public_key, payload, request.signature):
            exc7 = SignatureMismatchError("Identity verification failed")
            await self._fail(
                exc7,
                claimed_agent_id=request.agent_id,
                operation=operation,
                connection_id=connection_id,
            )
            raise exc7  # pragma: no cover — _fail always raises

        # All checks passed — record the nonce and return.
        self._seen_nonces[request.nonce] = now
        return VerifiedIdentity(
            agent_id=record.agent_id,
            verified_at=now,
            connection_id=connection_id,
            origin_server=None,  # always None in v1.0; reserved for federation (spec §7)
        )

    async def bind_for_send(
        self,
        request: SignedRequest,
        send_input: dict[str, object],
    ) -> dict[str, object]:
        """Verify *request* and overwrite ``send_input["sender"]`` with the certified identity.

        This satisfies ``spec/ports/identity.md §2``: the server MUST assign
        ``sender`` from its credential registry, NOT from any client-supplied value.

        The ``agent_id`` field is NOT required in *send_input* — it is injected
        by the server.  Any ``sender`` field already present is overwritten.

        Args:
            request: The signed-request envelope.
            send_input: The mutable send-operation input dict.

        Returns:
            A new dict with ``sender`` set to the verified ``agent_id``.
            The original *send_input* is NOT mutated.

        Raises:
            IdentityFailure: Any verification failure (see :meth:`verify`).
        """
        identity = await self.verify(request, operation="send")
        return {
            **send_input,
            "sender": identity.agent_id,
            "origin_server": identity.origin_server,  # None in v1.0 (spec §7 12-field envelope)
        }
