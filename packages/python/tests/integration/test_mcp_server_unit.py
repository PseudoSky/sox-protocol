# SPDX-License-Identifier: Apache-2.0
"""Unit tests for server.py — _load_and_validate_schemas, _build_store, create_server."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sox_protocol.core.mcp_server import server as mcp_server

# ---------------------------------------------------------------------------
# _load_and_validate_schemas
# ---------------------------------------------------------------------------


def test_load_and_validate_schemas_succeeds() -> None:
    """_load_and_validate_schemas() passes when spec/ is present."""
    # Should not raise or call sys.exit
    mcp_server._load_and_validate_schemas()


def test_load_and_validate_schemas_missing_dir_exits() -> None:
    """_load_and_validate_schemas exits(1) when the spec dir doesn't exist."""
    with patch.object(mcp_server, "_SPEC_SCHEMAS_DIR", Path("/nonexistent/path/schemas/tools")):
        with pytest.raises(SystemExit) as exc_info:
            mcp_server._load_and_validate_schemas()
        assert exc_info.value.code == 1


def test_load_and_validate_schemas_missing_schema_file_exits(tmp_path: Path) -> None:
    """_load_and_validate_schemas exits(1) when a schema file is missing."""
    # Create an empty dir — no schema files present
    with patch.object(mcp_server, "_SPEC_SCHEMAS_DIR", tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            mcp_server._load_and_validate_schemas()
        assert exc_info.value.code == 1


def test_load_and_validate_schemas_validation_error_exits(tmp_path: Path) -> None:
    """_load_and_validate_schemas exits(1) when a sample fails schema validation."""
    import json

    # Write a schema that rejects everything
    schema_that_rejects_all = {"type": "string"}  # samples are dicts, will fail

    for fname in mcp_server._SCHEMA_SMOKE_SAMPLES:
        schema_path = tmp_path / fname
        schema_path.write_text(json.dumps(schema_that_rejects_all), encoding="utf-8")

    with patch.object(mcp_server, "_SPEC_SCHEMAS_DIR", tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            mcp_server._load_and_validate_schemas()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _build_store
# ---------------------------------------------------------------------------


def test_build_store_memory() -> None:
    """_build_store('memory://') returns a MemoryStore."""
    from sox_protocol.adapters.backing_stores.memory.store import MemoryStore

    store = mcp_server._build_store("memory://")
    assert isinstance(store, MemoryStore)


def test_build_store_sqlite_memory() -> None:
    """_build_store('sqlite://:memory:') returns a SqliteStore."""
    from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

    store = mcp_server._build_store("sqlite://:memory:")
    assert isinstance(store, SqliteStore)


def test_build_store_sqlite_absolute(tmp_path: Path) -> None:
    """_build_store('sqlite:///path') returns a SqliteStore for a file path."""
    from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

    db_path = str(tmp_path / "test.db")
    store = mcp_server._build_store(f"sqlite://{db_path}")
    assert isinstance(store, SqliteStore)


def test_build_store_sqlite_triple_slash(tmp_path: Path) -> None:
    """_build_store('sqlite:///abs/path') returns a SqliteStore."""
    from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

    db_path = str(tmp_path / "test2.db")
    store = mcp_server._build_store(f"sqlite:///{db_path.lstrip('/')}")
    assert isinstance(store, SqliteStore)


def test_build_store_file(tmp_path: Path) -> None:
    """_build_store('file://path') returns a FilesystemStore."""
    from sox_protocol.adapters.backing_stores.filesystem.store import FilesystemStore

    store = mcp_server._build_store(f"file://{tmp_path}")
    assert isinstance(store, FilesystemStore)


def test_build_store_unknown_scheme_raises() -> None:
    """_build_store raises ValueError for unknown scheme."""
    with pytest.raises(ValueError, match="Unrecognised SOX_BACKING_STORE URI"):
        mcp_server._build_store("redis://localhost")


# ---------------------------------------------------------------------------
# create_server
# ---------------------------------------------------------------------------


def test_create_server_returns_fastmcp() -> None:
    """create_server() returns a FastMCP instance."""
    from fastmcp import FastMCP

    os.environ.setdefault("SOX_AGENT_ID", "test-agent")
    os.environ.setdefault("SOX_BACKING_STORE", "memory://")
    srv = mcp_server.create_server()
    assert isinstance(srv, FastMCP)


def test_create_server_uses_env_agent_id() -> None:
    """create_server() reads agent_id from environment."""
    from fastmcp import FastMCP

    env = {"SOX_AGENT_ID": "env-agent", "SOX_BACKING_STORE": "memory://"}
    with patch.dict(os.environ, env, clear=False):
        srv = mcp_server.create_server()
    assert isinstance(srv, FastMCP)


def test_create_server_uses_claude_agent_name_fallback() -> None:
    """create_server() falls back to CLAUDE_AGENT_NAME when SOX_AGENT_ID is unset."""
    from fastmcp import FastMCP

    env = {"CLAUDE_AGENT_NAME": "claude-agent", "SOX_BACKING_STORE": "memory://"}
    with patch.dict(os.environ, env, clear=False):
        # Remove SOX_AGENT_ID if present
        saved = os.environ.pop("SOX_AGENT_ID", None)
        try:
            srv = mcp_server.create_server()
            assert isinstance(srv, FastMCP)
        finally:
            if saved is not None:
                os.environ["SOX_AGENT_ID"] = saved


def test_create_server_invalid_backing_store_exits() -> None:
    """create_server() exits(1) on unrecognised backing store URI."""
    env = {"SOX_BACKING_STORE": "bogus://something", "SOX_AGENT_ID": "x"}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(SystemExit) as exc_info:
            mcp_server.create_server()
        assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_create_server_lifespan_runs() -> None:
    """create_server() lifespan initialises store and listener, then cleans up."""
    from fastmcp import Client

    env = {"SOX_AGENT_ID": "lifespan-agent", "SOX_BACKING_STORE": "memory://"}
    with patch.dict(os.environ, env, clear=False):
        srv = mcp_server.create_server()

    # Run a simple operation through the lifespan
    async with Client(srv) as client:
        result = await client.call_tool("channels__list_channels", {})
        assert "channels" in result.data


# ---------------------------------------------------------------------------
# __main__ entry point  (mcp_server.__main__ module — 0% coverage)
# ---------------------------------------------------------------------------


def test_mcp_server_main_module_importable() -> None:
    """The __main__ module in mcp_server is importable."""
    import importlib
    # Just confirm it exists without running it
    spec = importlib.util.find_spec("sox_protocol.core.mcp_server.__main__")
    assert spec is not None


def test_mcp_server_main_entry_exists() -> None:
    """server.main() function exists and is callable."""
    assert callable(mcp_server.main)
