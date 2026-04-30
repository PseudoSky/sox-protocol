# SPDX-License-Identifier: Apache-2.0
"""Tests for sox_protocol.core.identity.registry.

Spec reference: spec/ports/identity.md §7
"""

from __future__ import annotations

import pytest

from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.registry import InMemoryCredentialRegistry


@pytest.fixture
def reg() -> InMemoryCredentialRegistry:
    return InMemoryCredentialRegistry()


@pytest.fixture
def keypair() -> tuple[bytes, bytes]:
    return generate_keypair()


# ---------------------------------------------------------------------------
# CredentialRecord shape
# ---------------------------------------------------------------------------

async def test_registry_records_required_columns(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """CredentialRecord exposes agent_id, public_key, registered_at, revoked_at."""
    _, pub = keypair
    record = await reg.register("alice", pub)
    assert record.agent_id == "alice"
    assert record.public_key == pub
    assert isinstance(record.registered_at, float)
    assert record.revoked_at is None


async def test_record_is_not_revoked_initially(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """A freshly registered agent is not revoked."""
    _, pub = keypair
    record = await reg.register("alice", pub)
    assert record.is_revoked is False


# ---------------------------------------------------------------------------
# Append-only semantics
# ---------------------------------------------------------------------------

async def test_registry_is_append_only(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """revoke() sets revoked_at but does not remove the record."""
    _, pub = keypair
    await reg.register("alice", pub)
    await reg.revoke("alice")
    record = await reg.lookup("alice")
    assert record is not None
    assert record.revoked_at is not None
    assert record.agent_id == "alice"


async def test_all_records_includes_revoked(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """all_records() includes revoked agents."""
    _, pub = keypair
    await reg.register("alice", pub)
    await reg.revoke("alice")
    records = await reg.all_records()
    assert any(r.agent_id == "alice" for r in records)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

async def test_lookup_returns_none_for_unknown(
    reg: InMemoryCredentialRegistry,
) -> None:
    """lookup() returns None for an unregistered agent (does not raise)."""
    result = await reg.lookup("unknown-agent")
    assert result is None


async def test_lookup_returns_record_for_known(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """lookup() returns the CredentialRecord for a registered agent."""
    _, pub = keypair
    await reg.register("bob", pub)
    record = await reg.lookup("bob")
    assert record is not None
    assert record.agent_id == "bob"


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------

async def test_revoke_sets_revoked_at(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """revoke() sets a non-None revoked_at timestamp."""
    _, pub = keypair
    await reg.register("alice", pub)
    await reg.revoke("alice")
    record = await reg.lookup("alice")
    assert record is not None
    assert isinstance(record.revoked_at, float)


async def test_revoke_unknown_agent_raises_key_error(
    reg: InMemoryCredentialRegistry,
) -> None:
    """revoke() raises KeyError for an unknown agent."""
    with pytest.raises(KeyError):
        await reg.revoke("nobody")


# ---------------------------------------------------------------------------
# Register validation
# ---------------------------------------------------------------------------

async def test_register_rejects_empty_agent_id(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """register() raises ValueError for empty agent_id."""
    _, pub = keypair
    with pytest.raises(ValueError, match="agent_id"):
        await reg.register("", pub)


async def test_register_rejects_wrong_key_size(
    reg: InMemoryCredentialRegistry,
) -> None:
    """register() raises ValueError when public_key is not 32 bytes."""
    with pytest.raises(ValueError, match="32 bytes"):
        await reg.register("alice", b"short")


# ---------------------------------------------------------------------------
# Key rotation (re-register)
# ---------------------------------------------------------------------------

async def test_reregister_updates_public_key(
    reg: InMemoryCredentialRegistry,
) -> None:
    """Re-registering an agent updates the public key (rotation semantics)."""
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    await reg.register("alice", pub1)
    await reg.register("alice", pub2)
    record = await reg.lookup("alice")
    assert record is not None
    assert record.public_key == pub2
    assert record.revoked_at is None


async def test_all_records_returns_list(
    reg: InMemoryCredentialRegistry, keypair: tuple[bytes, bytes]
) -> None:
    """all_records() returns a list."""
    _, pub = keypair
    await reg.register("alice", pub)
    records = await reg.all_records()
    assert isinstance(records, list)
    assert len(records) >= 1


async def test_registry_int_clock_converted_to_float() -> None:
    """Registry with a clock returning int converts it to float without error."""
    _, pub = generate_keypair()
    reg = InMemoryCredentialRegistry(clock=lambda: 12345)  # type: ignore[arg-type]
    record = await reg.register("agent", pub)
    assert isinstance(record.registered_at, float)
    assert record.registered_at == 12345.0
