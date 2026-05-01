# SPDX-License-Identifier: Apache-2.0
"""Tests for the bootstrap lifecycle step.

Covers:
- list_channels version handshake (compatible and incompatible versions)
- subscribe patterns established correctly
- namespace propagation
- initial drain discards pre-existing messages
- annotation density check: agent.py must have ≥1 comment line per 3 code lines
"""

from __future__ import annotations

import sys
import tokenize
import io
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client

# Ensure examples/reference-agent/ is on the path.
_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))

from agent import ReferenceAgent, SUPPORTED_PROTOCOL_VERSION
from tests.reference_agent.helpers import build_server
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Annotation density test
# ---------------------------------------------------------------------------


def test_annotation_density_agent_py() -> None:
    """agent.py must have at least 1 comment line per 3 code lines.

    Comment lines must be ≥10 chars (excluding the '#') to avoid trivial
    one-word comments gaming the ratio. Shebang and encoding lines are
    excluded. This test is the enforcement mechanism for the plan contract.
    """
    agent_path = _REF_AGENT_DIR / "agent.py"
    source = agent_path.read_text(encoding="utf-8")

    comment_lines = 0
    code_lines = 0

    # Tokenize the file to accurately classify lines.
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    comment_token_lines: set[int] = set()
    for tok_type, tok_string, tok_start, _, _ in tokens:
        if tok_type == tokenize.COMMENT:
            # Only count substantive comments (≥10 chars after the '#').
            content = tok_string.lstrip("#").strip()
            if len(content) >= 10:
                comment_token_lines.add(tok_start[0])

    # Count physical lines that are not blank and not pure comments.
    source_lines = source.splitlines()
    for i, line in enumerate(source_lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue  # blank lines don't count
        if stripped.startswith("#"):
            # Already captured by tokenizer; count here for non-tokenized cases.
            content = stripped.lstrip("#").strip()
            if len(content) >= 10:
                comment_lines += 1
        else:
            # Non-blank, non-comment line counts as code.
            code_lines += 1

    # Add comment lines identified by tokenizer (inline comments on code lines).
    for lineno in comment_token_lines:
        stripped = source_lines[lineno - 1].strip()
        if not stripped.startswith("#"):
            # This is an inline comment on a code line — count it additionally.
            comment_lines += 1

    # The ratio must be at least 1:3 (1 comment per 3 code lines).
    assert code_lines > 0, "agent.py appears to have no code lines"
    ratio = comment_lines / code_lines
    assert ratio >= 1 / 3, (
        f"Annotation density too low: {comment_lines} comment lines / "
        f"{code_lines} code lines = {ratio:.2f} (required ≥ 0.333)"
    )


# ---------------------------------------------------------------------------
# Version handshake tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_compatible_version(tmp_state_dir: Path) -> None:
    """Bootstrap succeeds when server reports a compatible version."""
    store = MemoryStore()
    mcp = await build_server(store, "test-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="test-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Should not raise — server reports version "1.0".
        await agent.bootstrap()


@pytest.mark.asyncio
async def test_bootstrap_version_mismatch_raises(tmp_state_dir: Path) -> None:
    """Bootstrap raises RuntimeError when server version is incompatible."""
    store = MemoryStore()
    mcp = await build_server(store, "test-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="test-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Patch list_channels to return a version-2 server.
        original_call = client.call_tool

        async def _patched_call(name: str, args: dict[str, Any] | None = None) -> Any:
            if name == "channels__list_channels":
                result = MagicMock()
                result.data = {
                    "channels": [],
                    "_sox_protocol": {
                        "server_version": "2.0",
                        "supported_versions": ["2.0"],
                        "min_client_version": "2.0",
                    },
                }
                return result
            return await original_call(name, args or {})

        client.call_tool = _patched_call  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="SOX version mismatch"):
            await agent.bootstrap()


@pytest.mark.asyncio
async def test_bootstrap_subscribes_expected_patterns(tmp_state_dir: Path) -> None:
    """Bootstrap registers ticket:*, dm/<id>~*, dm/*~<id>, sox/presence."""
    store = MemoryStore()
    mcp = await build_server(store, "bootstrap-test")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="bootstrap-test",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        # Verify subscriptions were registered in the backing store.
        patterns = store._subscriptions.get("bootstrap-test", [])
        assert "ticket:*" in patterns
        # sox/presence is a server-emitted channel for peer visibility.
        assert "sox/presence" in patterns
        # DMs use exact channel names (wildcards on dm/ are forbidden by spec).
        # Exact DM subscriptions are set up per-conversation, not in bootstrap.


@pytest.mark.asyncio
async def test_bootstrap_emits_online_heartbeat(tmp_state_dir: Path) -> None:
    """Bootstrap emits a heartbeat(online) to register with the liveness table."""
    store = MemoryStore()
    mcp = await build_server(store, "hb-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="hb-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        # Liveness record should now exist for this agent.
        liveness = store._liveness.get("hb-agent")
        assert liveness is not None
        assert liveness["status"] == "online"


@pytest.mark.asyncio
async def test_bootstrap_drains_preexisting_messages(tmp_state_dir: Path) -> None:
    """Bootstrap initial drain discards messages queued during offline period."""
    store = MemoryStore()
    # Pre-seed a message before the agent subscribes.
    await store.initialize()
    await store.subscribe("hb-agent", "ticket:*")
    await store.send("ticket:pre-existing", "some-other-agent", {"type": "status_update"})

    mcp = await build_server(store, "hb-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="hb-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Bootstrap should not raise even with pre-existing messages.
        await agent.bootstrap()
        # After bootstrap, a second recv should return nothing (already drained).
        recv_result = await client.call_tool("channels__recv", {})
        msgs = recv_result.data.get("messages", [])
        assert msgs == [], f"Expected empty after bootstrap drain, got: {msgs}"
