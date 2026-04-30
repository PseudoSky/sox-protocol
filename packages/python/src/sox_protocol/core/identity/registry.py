# SPDX-License-Identifier: Apache-2.0
"""Credential registry: stores and looks up per-agent public keys.

The registry is append-only: revocation sets ``revoked_at`` but does NOT
remove the record, so that audit logs can still reference the credential
record for historical verification.

Spec reference: ``spec/ports/identity.md §3, §7``;
``docs/adr/0002-agent-identity-primitive.md §Operational/Server storage``

This module provides:

- :class:`CredentialRecord` — immutable value object for one registered agent.
- :class:`CredentialRegistry` — abstract base class (the port contract).
- :class:`InMemoryCredentialRegistry` — reference implementation for tests and
  pre-adapter wiring.  NOT a production persistence layer; use the SQLite
  adapter for durable storage.
"""

from __future__ import annotations

import asyncio
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialRecord:
    """Immutable record for one registered agent credential.

    Attributes:
        agent_id: The agent's unique identifier (bare string in v1.0).
        public_key: 32-byte raw Ed25519 public key.
        registered_at: Unix epoch seconds when the credential was first
            registered.
        revoked_at: Unix epoch seconds when the credential was revoked, or
            ``None`` if it is still active.  Set by :meth:`CredentialRegistry.revoke`;
            the record is NEVER deleted (append-only).
    """

    agent_id: str
    public_key: bytes
    registered_at: float
    revoked_at: float | None = None

    @property
    def is_revoked(self) -> bool:
        """Return ``True`` if this credential has been revoked."""
        return self.revoked_at is not None


class CredentialRegistry(ABC):
    """Abstract base class for the SOX credential registry port.

    All methods are async to allow implementations backed by remote stores
    (e.g. SQLite via aiosqlite, network key servers).

    Spec reference: ``spec/ports/identity.md §3``
    """

    @abstractmethod
    async def register(self, agent_id: str, public_key: bytes) -> CredentialRecord:
        """Register *agent_id* with *public_key*, returning the new record.

        If *agent_id* is already registered (active or revoked), the
        implementation MUST update the public key and reset ``revoked_at`` to
        ``None`` (key rotation semantics).

        Args:
            agent_id: Non-empty agent identifier.
            public_key: 32-byte raw Ed25519 public key.

        Returns:
            The newly created or updated :class:`CredentialRecord`.

        Raises:
            ValueError: If *agent_id* is empty or *public_key* is not 32 bytes.
        """

    @abstractmethod
    async def revoke(self, agent_id: str) -> None:
        """Mark *agent_id*'s credential as revoked.

        The record is NOT deleted.  Subsequent :meth:`lookup` calls still
        return the record with ``revoked_at`` set (append-only).

        Args:
            agent_id: The agent whose credential to revoke.

        Raises:
            KeyError: If *agent_id* is not registered.
        """

    @abstractmethod
    async def lookup(self, agent_id: str) -> CredentialRecord | None:
        """Return the credential record for *agent_id*, or ``None`` if unknown.

        Does NOT raise for unknown agents — callers must check the return value.

        Args:
            agent_id: The agent to look up.

        Returns:
            The :class:`CredentialRecord` if registered, ``None`` otherwise.
        """

    @abstractmethod
    async def all_records(self) -> list[CredentialRecord]:
        """Return a snapshot of all registered records (active and revoked).

        Returns:
            List of all :class:`CredentialRecord` objects in registration order.
        """


class InMemoryCredentialRegistry(CredentialRegistry):
    """In-memory reference implementation of :class:`CredentialRegistry`.

    Thread-safe for asyncio coroutines via an :class:`asyncio.Lock`.

    .. warning::
        This is a reference implementation for tests and pre-adapter wiring.
        It is NOT a production persistence layer.  Data is lost when the
        process exits.  Use the SQLite adapter for durable storage.

    Spec reference: ``spec/ports/identity.md §3``
    """

    def __init__(self, clock: object = None) -> None:
        """Initialise an empty registry.

        Args:
            clock: Optional callable ``() -> float`` returning the current
                Unix epoch seconds.  Defaults to :func:`time.time`.  Injectable
                for deterministic tests.
        """
        import time as t

        self._clock: object = clock if clock is not None else t.time
        self._records: dict[str, CredentialRecord] = {}
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        if callable(self._clock):
            result = self._clock()
            if isinstance(result, float):
                return result
            return float(result)
        return _time.time()  # pragma: no cover — clock is always callable in practice

    async def register(self, agent_id: str, public_key: bytes) -> CredentialRecord:
        """Register or update *agent_id* with *public_key*.

        Args:
            agent_id: Non-empty agent identifier.
            public_key: 32-byte raw Ed25519 public key.

        Returns:
            The new :class:`CredentialRecord`.

        Raises:
            ValueError: If *agent_id* is empty or *public_key* is not 32 bytes.
        """
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        if len(public_key) != 32:
            raise ValueError(f"public_key must be 32 bytes, got {len(public_key)}")

        record = CredentialRecord(
            agent_id=agent_id,
            public_key=public_key,
            registered_at=self._now(),
            revoked_at=None,
        )
        async with self._lock:
            self._records[agent_id] = record
        return record

    async def revoke(self, agent_id: str) -> None:
        """Mark *agent_id*'s credential revoked (append-only; record is kept).

        Args:
            agent_id: The agent to revoke.

        Raises:
            KeyError: If *agent_id* is not registered.
        """
        async with self._lock:
            if agent_id not in self._records:
                raise KeyError(agent_id)
            existing = self._records[agent_id]
            self._records[agent_id] = CredentialRecord(
                agent_id=existing.agent_id,
                public_key=existing.public_key,
                registered_at=existing.registered_at,
                revoked_at=self._now(),
            )

    async def lookup(self, agent_id: str) -> CredentialRecord | None:
        """Return the record for *agent_id*, or ``None`` if not registered.

        Args:
            agent_id: The agent to look up.

        Returns:
            :class:`CredentialRecord` or ``None``.
        """
        async with self._lock:
            return self._records.get(agent_id)

    async def all_records(self) -> list[CredentialRecord]:
        """Return a snapshot of all records.

        Returns:
            List of all records in insertion order.
        """
        async with self._lock:
            return list(self._records.values())
