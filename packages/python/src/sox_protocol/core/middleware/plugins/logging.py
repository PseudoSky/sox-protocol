# SPDX-License-Identifier: Apache-2.0
"""LoggingMiddleware — sample observation-only JSONL logging plugin.

Demonstrates composition: a plugin that lives at the bottom of the chain
(post-store_dispatch) and writes one JSON line per dispatched call.

Runtime default path: ``~/.sox/logs/middleware.jsonl``
The directory is created on first write (``mkdir -p`` semantics).

This module MUST NOT write to ``~/.sox/`` or any external path during tests;
tests inject a temporary path via the ``path`` constructor argument.

Spec reference: ``docs/adr/0003 §Decision (4) sample plugin``

Plugin registration
-------------------
Register this plugin via the default registry::

    from sox_protocol.core.middleware import register_middleware
    from sox_protocol.core.middleware.plugins.logging import LoggingMiddleware
    from pathlib import Path

    register_middleware.register(
        "middleware_log",
        lambda: LoggingMiddleware(path=Path("/tmp/my-log.jsonl")),
    )
"""

from __future__ import annotations

import json
import pathlib
import time as _time_module
from collections.abc import Callable

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.protocol import CallNext


def default_log_path() -> pathlib.Path:
    """Return the default runtime log path.

    The returned path is ``~/.sox/logs/middleware.jsonl``.  The directory is
    NOT created by this function; creation happens on the first write.

    Returns:
        :class:`~pathlib.Path` pointing to the default JSONL file.
    """
    return pathlib.Path.home() / ".sox" / "logs" / "middleware.jsonl"


class LoggingMiddleware:
    """Observation-only middleware that appends one JSONL line per call.

    Runs after ``store_dispatch`` so the log captures the final outcome.

    The written record contains:
    ``ts``, ``operation``, ``connection_id``, ``agent_id``,
    ``correlation_id``, ``response_keys`` (list of top-level response keys).

    Args:
        path: Path to the JSONL file.  Defaults to :func:`default_log_path`.
            Override in tests to a temporary path.
        clock: Callable returning the current Unix epoch seconds (float).
            Defaults to :func:`time.time`.  Injectable for deterministic tests.

    Attributes:
        name: Always ``'middleware_log'``.
        must_run_after: Runs after ``store_dispatch`` so it observes the final
            response.
        must_run_before: Empty — this plugin is outermost on the response path.
    """

    name: str = "middleware_log"
    must_run_before: tuple[str, ...] = ()
    must_run_after: tuple[str, ...] = ("store_dispatch",)

    def __init__(
        self,
        path: pathlib.Path | None = None,
        *,
        clock: Callable[[], float] = _time_module.time,
    ) -> None:
        self._path: pathlib.Path = path if path is not None else default_log_path()
        self._clock = clock

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: CallNext,
    ) -> dict[str, object]:
        """Forward to *call_next* then append a log line.

        Args:
            ctx: The per-call context.
            call_next: Next pipeline stage.

        Returns:
            The unmodified response from *call_next*.
        """
        response = await call_next(ctx)
        self._write_log(ctx, response)
        return response

    def _write_log(
        self,
        ctx: MiddlewareContext,
        response: dict[str, object],
    ) -> None:
        """Append one JSONL record to the log file.

        Creates parent directories on first write.

        Args:
            ctx: The context for this call.
            response: The response dict returned by the chain.
        """
        record = {
            "ts": self._clock(),
            "operation": ctx.operation,
            "connection_id": ctx.connection_id,
            "agent_id": ctx.agent_id,
            "correlation_id": ctx.correlation_id,
            "response_keys": sorted(response.keys()),
        }
        line = json.dumps(record, separators=(",", ":")) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)
