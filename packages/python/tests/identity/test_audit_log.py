# SPDX-License-Identifier: Apache-2.0
"""Tests for sox_protocol.core.identity.audit.

Spec reference: spec/ports/identity.md §5 (SHOULD log)
"""

from __future__ import annotations

import json
from pathlib import Path

from sox_protocol.core.identity.audit import AuditLogWriter, default_audit_path

# ---------------------------------------------------------------------------
# default_audit_path
# ---------------------------------------------------------------------------

def test_audit_path_default() -> None:
    """default_audit_path() resolves to ~/.sox/logs/identity-failures.jsonl."""
    expected = Path.home() / ".sox" / "logs" / "identity-failures.jsonl"
    assert default_audit_path() == expected


# ---------------------------------------------------------------------------
# record_failure writes exactly one JSONL line
# ---------------------------------------------------------------------------

async def test_rejection_writes_one_audit_line(tmp_path: Path) -> None:
    """record_failure() writes exactly one JSONL line per call."""
    log_path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path=log_path)
    await writer.record_failure(
        claimed_agent_id="alice",
        reason="test failure",
        operation="send",
        connection_id="conn-1",
    )
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1


async def test_multiple_failures_write_multiple_lines(tmp_path: Path) -> None:
    """Three record_failure() calls produce three distinct JSONL lines."""
    log_path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path=log_path)
    for i in range(3):
        await writer.record_failure(
            claimed_agent_id=f"agent-{i}",
            reason="reason",
            operation="recv",
            connection_id=None,
        )
    lines = [ln for ln in log_path.read_text().strip().split("\n") if ln]
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

async def test_audit_line_has_required_fields(tmp_path: Path) -> None:
    """Audit line contains ts, claimed_agent_id, reason, operation, connection_id."""
    log_path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path=log_path)
    await writer.record_failure(
        claimed_agent_id="alice",
        reason="bad sig",
        operation="subscribe",
        connection_id="conn-42",
    )
    record = json.loads(log_path.read_text().strip())
    assert "ts" in record
    assert record["claimed_agent_id"] == "alice"
    assert record["reason"] == "bad sig"
    assert record["operation"] == "subscribe"
    assert record["connection_id"] == "conn-42"


async def test_audit_ts_is_float(tmp_path: Path) -> None:
    """The ts field in the audit line is a float."""
    log_path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path=log_path)
    await writer.record_failure(
        claimed_agent_id="bob",
        reason="unknown",
        operation="send",
        connection_id=None,
    )
    record = json.loads(log_path.read_text().strip())
    assert isinstance(record["ts"], float)


# ---------------------------------------------------------------------------
# No secrets
# ---------------------------------------------------------------------------

async def test_audit_line_has_no_secrets(tmp_path: Path) -> None:
    """Audit line does not contain secret key fields (public_key, body_bytes, etc)."""
    import json as _json
    log_path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path=log_path)
    await writer.record_failure(
        claimed_agent_id="alice",
        reason="identity check failed",
        operation="send",
        connection_id=None,
    )
    record = _json.loads(log_path.read_text().strip())
    # Only the five safe fields should be present as top-level keys
    allowed_keys = {"ts", "claimed_agent_id", "reason", "operation", "connection_id"}
    secret_keys = {"public_key", "signature", "body_bytes", "secret", "private_key"}
    for key in record:
        assert key not in secret_keys, f"Secret key '{key}' found in audit log"
    assert set(record.keys()) == allowed_keys


# ---------------------------------------------------------------------------
# None values
# ---------------------------------------------------------------------------

async def test_audit_accepts_none_connection_id(tmp_path: Path) -> None:
    """record_failure() handles None connection_id."""
    log_path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path=log_path)
    await writer.record_failure(
        claimed_agent_id="alice",
        reason="test",
        operation="send",
        connection_id=None,
    )
    record = json.loads(log_path.read_text().strip())
    assert record["connection_id"] is None


async def test_audit_accepts_none_claimed_agent_id(tmp_path: Path) -> None:
    """record_failure() handles None claimed_agent_id (malformed envelope)."""
    log_path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path=log_path)
    await writer.record_failure(
        claimed_agent_id=None,
        reason="malformed",
        operation="send",
        connection_id=None,
    )
    record = json.loads(log_path.read_text().strip())
    assert record["claimed_agent_id"] is None


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------

async def test_audit_creates_parent_dir(tmp_path: Path) -> None:
    """AuditLogWriter creates parent directories on first write."""
    nested = tmp_path / "deep" / "nested" / "audit.jsonl"
    writer = AuditLogWriter(path=nested)
    await writer.record_failure(
        claimed_agent_id="alice",
        reason="test",
        operation="send",
        connection_id=None,
    )
    assert nested.exists()


# ---------------------------------------------------------------------------
# Clock injection
# ---------------------------------------------------------------------------

async def test_audit_uses_injected_clock(tmp_path: Path) -> None:
    """AuditLogWriter uses the injected clock for the ts field."""
    log_path = tmp_path / "audit.jsonl"
    fixed_ts = 9_999_999_999.5
    writer = AuditLogWriter(path=log_path, clock=lambda: fixed_ts)
    await writer.record_failure(
        claimed_agent_id="alice",
        reason="test",
        operation="send",
        connection_id=None,
    )
    record = json.loads(log_path.read_text().strip())
    assert record["ts"] == fixed_ts
