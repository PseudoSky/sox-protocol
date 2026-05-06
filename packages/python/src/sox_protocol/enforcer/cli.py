# SPDX-License-Identifier: Apache-2.0
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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sox_protocol.core.enforcer.events import Event

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


def _resolve_sqlite_path(url: str) -> str | None:
    """Extract a usable filesystem path from a ``sqlite://`` URL.

    Mirrors the parsing in ``core.mcp_server.server._build_store`` so the
    enforcer hook hits the *same* DB the MCP server is reading.  Returns
    ``None`` for non-sqlite schemes, ``:memory:``, or empty paths.

    Pre-0.2.3 the enforcer naively did ``url.split("://", 1)[1].lstrip("/")``
    which silently turned ``sqlite:///tmp/foo.db`` into the *relative*
    path ``tmp/foo.db`` — so every hook-triggered heartbeat and inbox
    peek wrote to / read from a phantom DB under the agent's cwd
    instead of the real project DB.
    """
    if not url.startswith("sqlite://"):
        return None
    raw_path = url[len("sqlite://"):]
    if raw_path == ":memory:" or raw_path == "/:memory:":
        return None
    if not raw_path:
        return None
    # The triple-slash form ``sqlite:///<abs>`` keeps the leading slash;
    # the double-slash form ``sqlite://<rel>`` doesn't.  Both work via
    # SqliteStore (it creates parent dirs as needed).
    return raw_path


async def _inbox_non_empty(agent_id: str) -> bool:
    """Return True if the backing store has undelivered messages for *agent_id*.

    Falls back to False on any error (safe-fail).
    """
    url = _resolve_backing_store_url()
    try:
        from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

        store: Any
        if url.startswith("memory://"):
            return False  # ephemeral — always empty
        db_path = _resolve_sqlite_path(url)
        if db_path is None:
            return False  # unsupported scheme or :memory:; safe-fail
        store = SqliteStore(Path(db_path))

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
# Auto-heartbeat
# ---------------------------------------------------------------------------


# How long the auto-heartbeat keeps the agent "online" past its last tool
# call.  60s gives enough headroom for an agent that's mid-tool-call or
# briefly idle while still flipping to "stale" within a reasonable window
# when the agent has actually stopped.  Operators can override per-server
# via SOX_HEARTBEAT_TTL_DEFAULT (read by the heartbeat tool resolver) but
# this is the constant used by the hook-driven auto-beat path.
_AUTO_HEARTBEAT_TTL_SECONDS = 60


async def _auto_heartbeat(agent_id: str) -> None:
    """UPSERT a heartbeat row for *agent_id* via the resolved backing store.

    Called from every PostToolUse hook fire so the agent's liveness row
    stays fresh as long as it's making tool calls — without depending
    on the LLM to remember to call ``mcp__sox__channels__heartbeat``
    on its own.  This is the auto-keepalive path: the SKILL.md
    activation block tells the LLM to heartbeat too, but the LLM
    forgets, so the hook does it deterministically.

    Safe-fail: any error is logged at DEBUG and swallowed.  The
    PostToolUse hook MUST NOT crash the agent.
    """
    if not agent_id or agent_id == "unknown-agent":
        # No usable identity — skip rather than spam the liveness table
        # with an "unknown-agent" row.  The hook continues; only the
        # heartbeat is skipped.
        return
    url = _resolve_backing_store_url()
    try:
        from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

        db_path = _resolve_sqlite_path(url)
        if db_path is None:
            # memory:// and unknown schemes: no cross-process visibility
            # to maintain anyway.  Skip.
            return
        store = SqliteStore(Path(db_path))
        async with store:
            await store.heartbeat(
                agent_id=agent_id,
                status="online",
                ttl=_AUTO_HEARTBEAT_TTL_SECONDS,
            )
    except Exception as exc:
        log.debug("auto-heartbeat failed for %s: %s", agent_id, exc)


# ---------------------------------------------------------------------------
# Event construction
# ---------------------------------------------------------------------------


def _extract_agent_id(hook_data: dict[str, Any]) -> str:
    """Extract agent_id from hook JSON. Falls back to 'unknown-agent'."""
    for key in ("agent_name", "session_id", "agentName"):
        val = hook_data.get(key)
        if val and isinstance(val, str):
            return str(val)
    env_id = os.environ.get("CLAUDE_AGENT_NAME") or os.environ.get("SOX_AGENT_ID")
    return env_id or "unknown-agent"


def _build_tool_used_event(hook_data: dict[str, Any]) -> Event:
    """Build the enforcer Event from a PostToolUse hook payload.

    Picks ``EventType.channel_recv`` (vs. the generic ``tool_used``) when
    the tool was a SOX recv tool, so that
    :meth:`StateStore.apply_event` actually resets the
    ``tool_calls_since_drain`` counter.  Pre-0.2.3 this always emitted
    ``tool_used`` for every PostToolUse fire — meaning recv calls
    incremented the counter instead of resetting it, and the
    "checked the channels inbox" reminder fired immediately after a
    successful drain.

    Same treatment for send: emit ``channel_send`` so send-and-stall
    detection records the send via the canonical event path.
    """
    from sox_protocol.core.enforcer.events import Event, EventType

    agent_id = _extract_agent_id(hook_data)
    tool_name: str | None = hook_data.get("tool_name") or hook_data.get("toolName")

    # Map the tool name to the right event type.  Both the bare and
    # mcp__sox__-prefixed forms are recognised since either can appear
    # in the hook JSON depending on the runtime version.
    event_type = EventType.tool_used
    if tool_name in {"channels__recv", "mcp__sox__channels__recv"}:
        event_type = EventType.channel_recv
    elif tool_name in {"channels__send", "mcp__sox__channels__send"}:
        event_type = EventType.channel_send

    return Event(
        schema_version="1.0",
        event_type=event_type,
        agent_id=agent_id,
        timestamp=time.time(),
        tool_name=tool_name,
    )


def _build_stop_event(hook_data: dict[str, Any], inbox_non_empty: bool) -> Event:
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
    from sox_protocol.core.enforcer.policy import Policy
    from sox_protocol.core.enforcer.state import StateStore

    policy = Policy()
    state_db = _resolve_state_db()

    if hook_type == "post_tool_use":
        event = _build_tool_used_event(hook_data)
        # Auto-keepalive: bump the agent's liveness row on every tool
        # use so the cross-process roster reflects activity even when
        # the LLM forgets to call ``channels__heartbeat`` on the cadence
        # the activation block recommends.  Safe-fail.
        await _auto_heartbeat(event.agent_id)
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
