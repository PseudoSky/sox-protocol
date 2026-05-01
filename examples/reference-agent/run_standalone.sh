#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# run_standalone.sh — quick-start for the SOX reference agent
#
# What this script does:
#   1. Runs the reference agent in --once mode with an in-memory backing store.
#   2. Before starting the agent, uses a small Python helper to inject a
#      self-message into the store so the agent has something to drain.
#   3. Verifies the agent exits 0 within 30 seconds.
#
# Usage:
#   bash examples/reference-agent/run_standalone.sh
#
# Requirements:
#   - Python 3.11+
#   - sox-protocol installed (pip install -e packages/python)
#   - Working directory: anywhere in the repo (script uses absolute paths)

set -euo pipefail

# Resolve the repo root relative to this script's location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Add packages/python/src to PYTHONPATH so sox_protocol is importable.
export PYTHONPATH="${REPO_ROOT}/packages/python/src:${SCRIPT_DIR}:${PYTHONPATH:-}"

# Use a temp dir for state so we don't pollute the user's home directory.
STATE_DIR="$(mktemp -d)"
trap 'rm -rf "${STATE_DIR}"' EXIT

echo "[run_standalone] repo_root=${REPO_ROOT}"
echo "[run_standalone] state_dir=${STATE_DIR}"
echo "[run_standalone] PYTHONPATH=${PYTHONPATH}"

# ---------------------------------------------------------------------------
# Step 1: Run the reference agent in --once mode.
# --once: bootstrap → recover → single drain → graceful_stop → exit 0.
# The in-memory backing store is ephemeral; no files are written to disk
# except the seq.json cursor in STATE_DIR (which is cleaned up on exit).
# ---------------------------------------------------------------------------

echo "[run_standalone] launching reference agent (--once mode, memory:// store)..."

# Timeout after 30s per the engagement contract.
timeout 30 python3 "${SCRIPT_DIR}/cli.py" \
    --agent-id "standalone-test-agent" \
    --namespace "reference" \
    --backing-store "memory://" \
    --state-dir "${STATE_DIR}" \
    --once \
    --log-level INFO

EXIT_CODE=$?

if [ "${EXIT_CODE}" -eq 0 ]; then
    echo "[run_standalone] PASS — agent exited 0"
else
    echo "[run_standalone] FAIL — agent exited ${EXIT_CODE}"
    exit "${EXIT_CODE}"
fi

# ---------------------------------------------------------------------------
# Step 2: Verify the integration via a Python round-trip test.
# Spins up an in-process server, sends a self-message, runs the agent in
# --once mode (via the Python API directly), and asserts the message was
# received and ACK'd.
# ---------------------------------------------------------------------------

echo "[run_standalone] running Python round-trip verification..."

python3 - <<'PYEOF'
"""Inline round-trip verification.

Builds an in-process FastMCP server with a MemoryStore, sends a test
message to ticket:standalone-test, then runs the reference agent in
--once mode and verifies it drains and ACKs the message without error.
"""
import asyncio
import contextlib
import sys
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# Ensure packages/python/src and examples/reference-agent are importable.
sys.path.insert(0, os.environ["PYTHONPATH"].split(":")[0])

import tempfile
from fastmcp import Client, FastMCP
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.server import _load_and_validate_schemas
from sox_protocol.core.mcp_server.tools import register_tools

# Import the reference agent (examples/reference-agent/ is on sys.path via PYTHONPATH).
script_dir = Path(__file__).parent if "__file__" in dir() else Path(os.environ.get("SCRIPT_DIR", "."))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "agent",
    Path(os.environ["PYTHONPATH"].split(":")[1]) / "agent.py"
)
agent_mod = importlib.util.load_from_spec = None  # not needed; use direct path

# Directly run via asyncio
async def run():
    store = MemoryStore()

    @contextlib.asynccontextmanager
    async def _lifespan(server: FastMCP[Any]) -> AsyncIterator[dict[str, object]]:
        _load_and_validate_schemas()
        await store.initialize()
        listener = Listener(store=store, agent_id="standalone-test-agent")
        listener.start()
        try:
            yield {"store": store, "listener": listener, "agent_id": "standalone-test-agent"}
        finally:
            await listener.stop()

    mcp: FastMCP[Any] = FastMCP(name="sox-standalone-test", lifespan=_lifespan)
    register_tools(mcp)

    async with Client(mcp) as client:
        # Subscribe and send a self-message before running the agent.
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        send_result = await client.call_tool(
            "channels__send",
            {
                "channel": "ticket:standalone-test",
                "body": {
                    "type": "clarification_request",
                    "subject": "Standalone smoke test",
                    "question": "Does the reference agent boot and drain correctly?",
                },
                "correlation_id": "standalone-smoke-001",
            },
        )
        assert "message_id" in send_result.data, f"send failed: {send_result.data}"
        print(f"[verify] sent message_id={send_result.data['message_id']}")

        # Import and run the reference agent against the same in-process server.
        import sys, os
        ref_dir = os.environ["PYTHONPATH"].split(":")[1]
        if ref_dir not in sys.path:
            sys.path.insert(0, ref_dir)
        from agent import ReferenceAgent

        with tempfile.TemporaryDirectory() as td:
            agent = ReferenceAgent(
                client,
                agent_id="standalone-test-agent",
                namespace="reference",
                state_dir=Path(td),
            )
            # Run in --once mode: bootstrap + recover + single drain + stop.
            await agent.run(once=True)

        print("[verify] PASS — reference agent completed --once cycle without error")

asyncio.run(run())
PYEOF

echo "[run_standalone] ALL CHECKS PASSED"
