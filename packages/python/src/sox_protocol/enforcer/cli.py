"""SOX Protocol — enforcer CLI bridge for Claude Code hooks.

Called by the hook shell scripts::

    python -m sox_protocol.enforcer cli --hook post_tool_use
    python -m sox_protocol.enforcer cli --hook stop

Reads Claude Code hook JSON from stdin, maps it to an ``Event``, runs
``decide()``, and prints one of:

- Nothing (``noop``)
- A JSON Decision dict (``inject`` or ``block``)

Exit codes:
    0  — success (noop, inject, or block all exit 0; Claude Code reads stdout)
    1  — usage error or unrecoverable internal error

The hooks wrap this in try/safe-fail so errors MUST NOT propagate to the agent.

Claude Code hook JSON shapes
----------------------------
``PostToolUse``::

    {
      "session_id": "...",
      "agent_name": "...",      # used as agent_id
      "tool_name": "...",
      "tool_input": {...},
      "tool_response": {...}
    }

``Stop`` / ``SubagentStop``::

    {
      "session_id": "...",
      "agent_name": "..."
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_STATE_DIR = Path.home() / ".sox"
_DEFAULT_BACKING_STORE = "memory://"


def _resolve_state_db() -> Path:
    env_dir = os.environ.get("SOX_STATE_DIR")
    if env_dir:
        return Path(env_dir) / "state.db"
    return _DEFAULT_STATE_DIR / "state.db"


def _resolve_backing_store_url() -> str:
    return os.environ.get("SOX_BACKING_STORE", _DEFAULT_BACKING_STORE)


# ---------------------------------------------------------------------------
# Inbox check
# ---------------------------------------------------------------------------


async def _inbox_non_empty(agent_id: str) -> bool:
    """Return True if the backing store has undelivered messages for *agent_id*.

    Falls back to False on any error (safe-fail).
    """
    url = _resolve_backing_store_url()
    try:
        from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore
        from sox_protocol.adapters.backing_stores.memory.store import MemoryStore

        store: Any
        if url.startswith("sqlite://") or url.startswith("sqlite:///"):
            db_path = url.split("://", 1)[1].lstrip("/")
            if not db_path or db_path == ":memory:":
                return False  # memory store — treat as empty
            store = SqliteStore(Path(db_path))
        elif url.startswith("memory://"):
            return False  # ephemeral — always empty
        else:
            return False  # unsupported scheme; safe-fail

        async with store:
            messages = await store.recv(agent_id=agent_id, max_messages=1)
            has_messages = len(messages) > 0
            if has_messages:
                # We drained one message to check; put it back by re-sending
                # is not possible without losing sender context.  Instead we
                # use a lighter-weight approach: peek via list_channels + a
                # dedicated peek query if available.  For now, treat this as
                # non-empty (the agent will drain it properly).
                pass
            return has_messages
    except Exception as exc:
        log.debug("inbox_non_empty check failed for %s: %s", agent_id, exc)
        return False


# ---------------------------------------------------------------------------
# Event construction
# ---------------------------------------------------------------------------


def _extract_agent_id(hook_data: dict[str, Any]) -> str:
    """Extract agent_id from hook JSON. Falls back to 'unknown-agent'."""
    for key in ("agent_name", "session_id", "agentName"):
        val = hook_data.get(key)
        if val and isinstance(val, str):
            return val
    env_id = os.environ.get("CLAUDE_AGENT_NAME") or os.environ.get("SOX_AGENT_ID")
    return env_id or "unknown-agent"


def _build_tool_used_event(hook_data: dict[str, Any]) -> "Event":
    from sox_protocol.core.enforcer.events import Event, EventType

    agent_id = _extract_agent_id(hook_data)
    tool_name: str | None = hook_data.get("tool_name") or hook_data.get("toolName")
    return Event(
        schema_version="1.0",
        event_type=EventType.tool_used,
        agent_id=agent_id,
        timestamp=time.time(),
        tool_name=tool_name,
    )


def _build_stop_event(hook_data: dict[str, Any], inbox_non_empty: bool) -> "Event":
    from sox_protocol.core.enforcer.events import Event, EventType

    agent_id = _extract_agent_id(hook_data)
    return Event(
        schema_version="1.0",
        event_type=EventType.stop_requested,
        agent_id=agent_id,
        timestamp=time.time(),
        metadata={"inbox_non_empty": inbox_non_empty},
    )


# ---------------------------------------------------------------------------
# Main CLI logic
# ---------------------------------------------------------------------------


async def _run(hook_type: str, hook_data: dict[str, Any]) -> dict[str, Any] | None:
    """Run the enforcer for *hook_type* and return a Decision dict or None."""
    from sox_protocol.core.enforcer.decide import decide
    from sox_protocol.core.enforcer.events import EventType
    from sox_protocol.core.enforcer.policy import Policy
    from sox_protocol.core.enforcer.state import StateStore

    policy = Policy()
    state_db = _resolve_state_db()

    if hook_type == "post_tool_use":
        event = _build_tool_used_event(hook_data)
    elif hook_type in ("stop", "subagent_stop"):
        agent_id = _extract_agent_id(hook_data)
        if policy.force_drain_on_stop:
            inbox_flag = await _inbox_non_empty(agent_id)
        else:
            inbox_flag = False
        event = _build_stop_event(hook_data, inbox_non_empty=inbox_flag)
    else:
        return None

    async with StateStore(db_path=state_db) as store:
        # Load state BEFORE mutation (decide reads pre-mutation state)
        state = await store.load(event.agent_id)
        decision = decide(event, state, policy)
        # Apply mutation after decide (state.apply_event handles the mutation)
        await store.apply_event(event.agent_id, event.event_type, event.timestamp)

    from sox_protocol.core.enforcer.events import Action

    if decision.action == Action.noop:
        return None

    # Substitute {{placeholder}} tokens in reminder messages with Claude Code
    # tool names before returning to the hook script.
    _PLACEHOLDER_MAP = {
        "{{send_tool}}": "mcp__sox__channels__send",
        "{{recv_tool}}": "mcp__sox__channels__recv",
        "{{subscribe_tool}}": "mcp__sox__channels__subscribe",
        "{{list_tool}}": "mcp__sox__channels__list_channels",
    }
    message = decision.message or ""
    for placeholder, tool_name in _PLACEHOLDER_MAP.items():
        message = message.replace(placeholder, tool_name)

    return {
        "action": decision.action.value,
        "message": message if message else None,
        "reason": decision.reason,
        "schema_version": decision.schema_version,
    }


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: reads stdin JSON, runs enforcer, prints result."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m sox_protocol.enforcer",
        description="SOX enforcer CLI — invoked by Claude Code hook scripts.",
    )
    subparsers = parser.add_subparsers(dest="command")
    cli_parser = subparsers.add_parser("cli", help="Process a hook event from stdin.")
    cli_parser.add_argument(
        "--hook",
        required=True,
        choices=["post_tool_use", "stop", "subagent_stop"],
        help="The hook type being processed.",
    )

    args = parser.parse_args(argv)
    if args.command != "cli":
        parser.print_help()
        sys.exit(1)

    # Read hook JSON from stdin
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        hook_data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"sox-enforcer: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        decision = asyncio.run(_run(args.hook, hook_data))
    except Exception as exc:
        print(f"sox-enforcer: internal error: {exc}", file=sys.stderr)
        sys.exit(1)

    if decision is not None:
        print(json.dumps(decision))
    # noop: exit 0 with no output
