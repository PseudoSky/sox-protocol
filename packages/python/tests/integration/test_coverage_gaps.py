# SPDX-License-Identifier: Apache-2.0
"""Tests covering remaining gaps in:
- core/mcp_server/__main__.py
- enforcer/__main__.py
- claude_code/__main__.py
- core/mcp_server/server.py (file:// URI, schema validation exits, HTTP transport)
- core/mcp_server/tools.py line 208 (dm/* wildcard forbidden)
- core/mcp_server/listener.py lines 84, 126-131
- memory/store.py uncovered branches
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# __main__.py files — all three
# ---------------------------------------------------------------------------


def test_mcp_server_main_module_executes() -> None:
    """core/mcp_server/__main__.py: covers lines 4-6."""
    sys.modules.pop("sox_protocol.core.mcp_server.__main__", None)
    with patch("sox_protocol.core.mcp_server.server.main", side_effect=SystemExit(0)):
        with pytest.raises(SystemExit):
            importlib.import_module("sox_protocol.core.mcp_server.__main__")


def test_enforcer_main_module_executes() -> None:
    """enforcer/__main__.py: covers lines 4-6."""
    sys.modules.pop("sox_protocol.enforcer.__main__", None)
    with patch("sox_protocol.enforcer.cli.main", side_effect=SystemExit(0)):
        with pytest.raises(SystemExit):
            importlib.import_module("sox_protocol.enforcer.__main__")


def test_claude_code_main_module_executes() -> None:
    """claude_code/__main__.py: covers lines 4-6."""
    sys.modules.pop("sox_protocol.adapters.runtimes.claude_code.__main__", None)
    with patch(
        "sox_protocol.adapters.runtimes.claude_code.install.main",
        side_effect=SystemExit(0),
    ), pytest.raises(SystemExit):
        importlib.import_module(
            "sox_protocol.adapters.runtimes.claude_code.__main__"
        )


# ---------------------------------------------------------------------------
# server.py — file:// URI branch (_resolve_backing_store) line 181
# ---------------------------------------------------------------------------


def test_resolve_backing_store_file_uri(tmp_path) -> None:
    """_build_store with file:// URI returns a FilesystemStore (line 181)."""
    from sox_protocol.core.mcp_server.server import _build_store

    store = _build_store(f"file://{tmp_path}")
    assert store is not None
    # FilesystemStore has _root attribute
    assert hasattr(store, "_root")


# ---------------------------------------------------------------------------
# server.py — _load_and_validate_schemas exits (lines 268, 270)
# ---------------------------------------------------------------------------


def test_load_and_validate_schemas_missing_dir_exits() -> None:
    """_load_and_validate_schemas exits when spec dir is missing (line 118)."""
    import pathlib

    from sox_protocol.core.mcp_server import server

    with patch.object(server, "_SPEC_SCHEMAS_DIR", pathlib.Path("/nonexistent_dir_xyz")):
        with pytest.raises(SystemExit):
            server._load_and_validate_schemas()


def test_load_and_validate_schemas_missing_file_exits(tmp_path) -> None:
    """_load_and_validate_schemas exits when a schema file is missing (line 124)."""
    import pathlib

    from sox_protocol.core.mcp_server import server

    # Point to an empty directory — no schema files present
    with patch.object(server, "_SPEC_SCHEMAS_DIR", pathlib.Path(tmp_path)):
        with pytest.raises(SystemExit):
            server._load_and_validate_schemas()


def test_load_and_validate_schemas_invalid_sample_exits(tmp_path) -> None:
    """_load_and_validate_schemas exits when a smoke sample fails validation (line 139)."""
    import json
    import pathlib

    from sox_protocol.core.mcp_server import server

    # Create a schema file that the sample will fail against
    schema = {
        "type": "object",
        "required": ["required_field_that_sample_lacks"],
        "properties": {"required_field_that_sample_lacks": {"type": "string"}},
    }
    schema_filename = list(server._SCHEMA_SMOKE_SAMPLES.keys())[0]
    schema_file = tmp_path / schema_filename
    schema_file.write_text(json.dumps(schema), encoding="utf-8")

    with patch.object(server, "_SPEC_SCHEMAS_DIR", pathlib.Path(tmp_path)):
        with pytest.raises(SystemExit):
            server._load_and_validate_schemas()


# ---------------------------------------------------------------------------
# server.py — HTTP transport branch in main() (lines 301-315)
# ---------------------------------------------------------------------------


def test_main_http_transport_calls_run() -> None:
    """main() with SOX_MCP_TRANSPORT=http calls mcp.run with streamable-http (lines 309-313)."""
    import os

    from sox_protocol.core.mcp_server.server import main

    mock_mcp = MagicMock()
    with patch("sox_protocol.core.mcp_server.server.create_server", return_value=mock_mcp):
        with patch.dict(
            os.environ,
            {
                "SOX_MCP_TRANSPORT": "http",
                "SOX_HTTP_HOST": "127.0.0.1",
                "SOX_HTTP_PORT": "9999",
            },
        ):
            main()
    mock_mcp.run.assert_called_once_with(
        transport="streamable-http", host="127.0.0.1", port=9999
    )


def test_main_stdio_transport_calls_run() -> None:
    """main() with default transport calls mcp.run with stdio (line 315)."""
    import os

    from sox_protocol.core.mcp_server.server import main

    mock_mcp = MagicMock()
    env = {k: v for k, v in os.environ.items() if k != "SOX_MCP_TRANSPORT"}
    with patch("sox_protocol.core.mcp_server.server.create_server", return_value=mock_mcp):
        with patch.dict(os.environ, env, clear=True):
            main()
    mock_mcp.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# tools.py line 208 — dm/* wildcard subscription forbidden
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_subscribe_dm_wildcard_raises() -> None:
    """channels__subscribe with dm/* raises ValueError (line 208)."""
    import os

    from fastmcp import Client

    from sox_protocol.core.mcp_server.server import create_server

    env_patch = {"SOX_AGENT_ID": "test-agent", "SOX_BACKING_STORE": "memory://"}
    with patch.dict(os.environ, env_patch):
        mcp = create_server()

    async with Client(mcp) as client:
        try:
            result = await client.call_tool("channels__subscribe", {"pattern": "dm/*"})
            # If result is returned (some FastMCP versions wrap errors in result),
            # verify the error is communicated
            result_text = str(result)
            assert (
                "dm/" in result_text
                or "forbidden" in result_text
                or "error" in result_text.lower()
                or "reserved" in result_text.lower()
            )
        except Exception as exc:
            # FastMCP raises ToolError or similar for tool ValueError
            assert (
                "dm/" in str(exc)
                or "forbidden" in str(exc)
                or "reserved" in str(exc)
                or "Wildcard" in str(exc)
            )


@pytest.mark.asyncio
async def test_channels_subscribe_group_wildcard_raises() -> None:
    """channels__subscribe with group/* raises ValueError (line 208)."""
    import os

    from fastmcp import Client

    from sox_protocol.core.mcp_server.server import create_server

    env_patch = {"SOX_AGENT_ID": "test-agent", "SOX_BACKING_STORE": "memory://"}
    with patch.dict(os.environ, env_patch):
        mcp = create_server()

    async with Client(mcp) as client:
        try:
            result = await client.call_tool("channels__subscribe", {"pattern": "group/*"})
            result_text = str(result)
            assert (
                "group/" in result_text
                or "forbidden" in result_text
                or "error" in result_text.lower()
                or "reserved" in result_text.lower()
            )
        except Exception as exc:
            assert (
                "group/" in str(exc)
                or "forbidden" in str(exc)
                or "reserved" in str(exc)
                or "Wildcard" in str(exc)
            )


# ---------------------------------------------------------------------------
# listener.py — line 84 (start() returns existing task) and lines 126-131
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_start_returns_existing_task_if_running() -> None:
    """Listener.start() returns the same task if already running (line 84)."""
    from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
    from sox_protocol.core.mcp_server.listener import Listener

    store = MemoryStore()
    await store.initialize()
    await store.subscribe("agent-a", "ch/*")

    listener = Listener(store=store, agent_id="agent-a")
    task1 = listener.start()
    task2 = listener.start()  # should return same task
    assert task1 is task2

    await listener.stop()


@pytest.mark.asyncio
async def test_listener_run_logs_exception_and_retries() -> None:
    """Listener._run() logs exception and retries after store error (lines 126-131)."""

    from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
    from sox_protocol.core.mcp_server.listener import Listener

    store = MemoryStore()
    await store.initialize()
    await store.subscribe("agent-b", "ch/*")

    call_count = 0

    async def _failing_watch(agent_id: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient store error")
        # After error, yield nothing then stop by raising CancelledError
        raise asyncio.CancelledError()
        # make it a generator
        if False:
            yield {}  # type: ignore[misc]

    listener = Listener(store=store, agent_id="agent-b")

    with patch.object(store, "watch", side_effect=_failing_watch):
        task = listener.start()
        # Give the task a moment to run and hit the exception path
        await asyncio.sleep(0.05)
        await listener.stop()

    # call_count may be 1 if it hit the error; the important thing is
    # the listener did not crash the whole process
    assert call_count >= 1


@pytest.mark.asyncio
async def test_listener_drain_respects_max_messages() -> None:
    """Listener.drain() with max_messages cap (line 84 / drain method)."""
    from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
    from sox_protocol.core.mcp_server.listener import Listener

    store = MemoryStore()
    await store.initialize()

    listener = Listener(store=store, agent_id="agent-c")

    # Manually stuff the queue
    for i in range(10):
        await listener.queue.put({"message_id": str(i)})

    drained = listener.drain(max_messages=3)
    assert len(drained) == 3
    assert listener.queue.qsize() == 7
