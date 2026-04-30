# SPDX-License-Identifier: Apache-2.0
"""Append-only JSONL audit log writer for identity-verification failures.

One JSON line is written per rejection with the fields required by
``spec/ports/identity.md §5``:
    ``ts``, ``claimed_agent_id``, ``reason``, ``operation``, ``connection_id``

No secrets (signatures, public keys, body bytes) appear in audit lines.

Runtime default path: ``~/.sox/logs/identity-failures.jsonl``
The directory is created on first write (``mkdir -p`` semantics).
This module does NOT create the directory at import time.

Spec reference: ``spec/ports/identity.md §5 (SHOULD log)``

Worker scope rule: the path above is the RUNTIME default.  This module MUST
NOT write to ``~/.sox/`` or any path outside the repository during tests;
tests inject a tmp path via the ``path`` constructor argument.
"""

from __future__ import annotations

import json
import time as _time_module
from collections.abc import Callable
from pathlib import Path


def default_audit_path() -> Path:
    """Return the default runtime audit-log path.

    The returned path is ``~/.sox/logs/identity-failures.jsonl``.
    The directory is NOT created by this function; creation happens
    on the first :meth:`AuditLogWriter.record_failure` call.

    Returns:
        :class:`~pathlib.Path` pointing to the default JSONL file.
    """
    return Path.home() / ".sox" / "logs" / "identity-failures.jsonl"


class AuditLogWriter:
    """Append-only JSONL writer for identity-verification failures.

    Each :meth:`record_failure` call appends exactly one JSON line to the
    configured path.  The parent directory is created on the first write
    (``parents=True, exist_ok=True``).

    The log MUST NOT contain secrets (signatures, public keys, body content).
    Only the fields listed in ``spec/ports/identity.md §5`` are written:
    ``ts``, ``claimed_agent_id``, ``reason``, ``operation``, ``connection_id``.

    Args:
        path: Path to the JSONL file.  Defaults to
            :func:`default_audit_path` (``~/.sox/logs/identity-failures.jsonl``).
            Override in tests to a temporary path.
        clock: Callable returning the current Unix epoch seconds (float).
            Defaults to :func:`time.time`.  Injectable for deterministic tests.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable[[], float] = _time_module.time,
    ) -> None:
        self._path: Path = path if path is not None else default_audit_path()
        self._clock: Callable[[], float] = clock

    async def record_failure(
        self,
        *,
        claimed_agent_id: str | None,
        reason: str,
        operation: str,
        connection_id: str | None,
    ) -> None:
        """Append one JSONL line for a rejected identity check.

        Creates parent directories on first write (no-op on subsequent calls).

        The written record contains ONLY safe fields — no signatures, public
        keys, or body content that could assist an attacker
        (``spec/ports/identity.md §5``).

        Args:
            claimed_agent_id: The ``agent_id`` the caller presented (may be
                ``None`` if the envelope was malformed).
            reason: Short human-readable description of the failure (the
                exception ``reason`` attribute).
            operation: The SOX operation that was attempted (e.g. ``"send"``).
            connection_id: Opaque transport connection identifier, or ``None``.
        """
        record = {
            "ts": self._clock(),
            "claimed_agent_id": claimed_agent_id,
            "reason": reason,
            "operation": operation,
            "connection_id": connection_id,
        }
        line = json.dumps(record, separators=(",", ":")) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)
