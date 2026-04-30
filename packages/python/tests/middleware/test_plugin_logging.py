# SPDX-License-Identifier: Apache-2.0
"""Tests for LoggingMiddleware plugin.

Spec reference: ``docs/adr/0003 §Decision (4)``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.pipeline import Pipeline
from sox_protocol.core.middleware.plugins.logging import LoggingMiddleware, default_log_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _passthrough(ctx: MiddlewareContext) -> dict[str, object]:
    return {"ok": True}


# ---------------------------------------------------------------------------
# default_log_path
# ---------------------------------------------------------------------------


def test_default_log_path_is_under_home() -> None:
    p = default_log_path()
    assert p.name == "middleware.jsonl"
    assert ".sox" in str(p)


# ---------------------------------------------------------------------------
# Appends one JSONL line per call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logging_plugin_appends_one_line(middleware_log_path: Path) -> None:
    mw = LoggingMiddleware(path=middleware_log_path, clock=lambda: 1_700_000_000.0)
    pipeline = Pipeline([mw], _passthrough)

    await pipeline.dispatch("send", {"channel": "x"}, connection_id="conn-1")

    lines = middleware_log_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["operation"] == "send"
    assert record["connection_id"] == "conn-1"
    assert record["ts"] == 1_700_000_000.0


@pytest.mark.asyncio
async def test_logging_plugin_appends_multiple_lines(middleware_log_path: Path) -> None:
    mw = LoggingMiddleware(path=middleware_log_path, clock=lambda: 1_700_000_000.0)
    pipeline = Pipeline([mw], _passthrough)

    await pipeline.dispatch("send", {}, connection_id="c")
    await pipeline.dispatch("recv", {}, connection_id="c")

    lines = middleware_log_path.read_text().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# Creates parent dir on first write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logging_plugin_creates_parent_dir(tmp_path: Path) -> None:
    deep_path = tmp_path / "nested" / "dirs" / "middleware.jsonl"
    assert not deep_path.parent.exists()

    mw = LoggingMiddleware(path=deep_path)
    pipeline = Pipeline([mw], _passthrough)
    await pipeline.dispatch("send", {}, connection_id="c")

    assert deep_path.exists()


# ---------------------------------------------------------------------------
# Record fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logging_plugin_record_has_expected_fields(middleware_log_path: Path) -> None:
    mw = LoggingMiddleware(path=middleware_log_path)
    pipeline = Pipeline([mw], _passthrough)
    await pipeline.dispatch("send", {}, connection_id="conn-99")

    record = json.loads(middleware_log_path.read_text().splitlines()[0])
    assert "ts" in record
    assert "operation" in record
    assert "connection_id" in record
    assert "agent_id" in record
    assert "correlation_id" in record
    assert "response_keys" in record


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def test_logging_middleware_name(middleware_log_path: Path) -> None:
    mw = LoggingMiddleware(path=middleware_log_path)
    assert mw.name == "middleware_log"


def test_logging_middleware_must_run_after_store_dispatch(middleware_log_path: Path) -> None:
    mw = LoggingMiddleware(path=middleware_log_path)
    assert "store_dispatch" in mw.must_run_after
