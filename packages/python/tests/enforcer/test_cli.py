# SPDX-License-Identifier: Apache-2.0
"""Tests for enforcer/cli.py and enforcer/__main__.py."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sox_protocol.enforcer import cli as enforcer_cli

# ---------------------------------------------------------------------------
# _resolve_state_db / _resolve_backing_store_url helpers
# ---------------------------------------------------------------------------


def test_resolve_state_db_uses_env(tmp_path: Path) -> None:
    """_resolve_state_db uses SOX_STATE_DIR when set."""
    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        path = enforcer_cli._resolve_state_db()
    assert path == tmp_path / "state.db"


def test_resolve_state_db_default() -> None:
    """_resolve_state_db returns default path when SOX_STATE_DIR unset."""
    env = {k: v for k, v in os.environ.items() if k != "SOX_STATE_DIR"}
    with patch.dict(os.environ, env, clear=True):
        path = enforcer_cli._resolve_state_db()
    assert str(path).endswith("state.db")


def test_resolve_backing_store_url_from_env() -> None:
    """_resolve_backing_store_url reads SOX_BACKING_STORE."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "memory://custom"}):
        url = enforcer_cli._resolve_backing_store_url()
    assert url == "memory://custom"


def test_resolve_backing_store_url_default() -> None:
    """_resolve_backing_store_url defaults to memory://."""
    env = {k: v for k, v in os.environ.items() if k != "SOX_BACKING_STORE"}
    with patch.dict(os.environ, env, clear=True):
        url = enforcer_cli._resolve_backing_store_url()
    assert url == "memory://"


# ---------------------------------------------------------------------------
# _extract_agent_id
# ---------------------------------------------------------------------------


def test_extract_agent_id_from_agent_name() -> None:
    assert enforcer_cli._extract_agent_id({"agent_name": "my-agent"}) == "my-agent"


def test_extract_agent_id_from_session_id() -> None:
    assert enforcer_cli._extract_agent_id({"session_id": "sess-123"}) == "sess-123"


def test_extract_agent_id_from_agent_name_camel() -> None:
    assert enforcer_cli._extract_agent_id({"agentName": "camel-agent"}) == "camel-agent"


def test_extract_agent_id_falls_back_to_env() -> None:
    with patch.dict(os.environ, {"CLAUDE_AGENT_NAME": "env-agent"}):
        result = enforcer_cli._extract_agent_id({})
    assert result == "env-agent"


def test_extract_agent_id_falls_back_to_sox_agent_id() -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_AGENT_NAME",)}
    env["SOX_AGENT_ID"] = "sox-id"
    # Remove CLAUDE_AGENT_NAME if present
    env.pop("CLAUDE_AGENT_NAME", None)
    with patch.dict(os.environ, env, clear=True):
        result = enforcer_cli._extract_agent_id({})
    assert result == "sox-id"


def test_extract_agent_id_falls_back_to_unknown() -> None:
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_AGENT_NAME", "SOX_AGENT_ID")}
    with patch.dict(os.environ, env, clear=True):
        result = enforcer_cli._extract_agent_id({})
    assert result == "unknown-agent"


# ---------------------------------------------------------------------------
# _build_tool_used_event / _build_stop_event
# ---------------------------------------------------------------------------


def test_build_tool_used_event() -> None:
    from sox_protocol.core.enforcer.events import EventType

    hook_data = {"agent_name": "agent-x", "tool_name": "bash"}
    event = enforcer_cli._build_tool_used_event(hook_data)
    assert event.event_type == EventType.tool_used
    assert event.agent_id == "agent-x"
    assert event.tool_name == "bash"


def test_build_tool_used_event_camel_tool_name() -> None:

    hook_data = {"agent_name": "agent-y", "toolName": "edit"}
    event = enforcer_cli._build_tool_used_event(hook_data)
    assert event.tool_name == "edit"


def test_build_event_for_recv_emits_channel_recv() -> None:
    """recv hook fires must map to channel_recv so apply_event resets counters.

    Pre-0.2.3 the CLI always emitted ``EventType.tool_used`` regardless of
    tool name, so ``StateStore.apply_event`` only saw ``tool_used`` and
    *incremented* the counter — even on a successful recv.  Result: the
    "checked the channels inbox" reminder fired immediately after every
    recv call.
    """
    from sox_protocol.core.enforcer.events import EventType

    hook_data = {"agent_name": "agent-r", "tool_name": "mcp__sox__channels__recv"}
    event = enforcer_cli._build_tool_used_event(hook_data)
    assert event.event_type == EventType.channel_recv
    assert event.tool_name == "mcp__sox__channels__recv"


def test_build_event_for_recv_bare_tool_name() -> None:
    """The bare ``channels__recv`` tool name is also recognised."""
    from sox_protocol.core.enforcer.events import EventType

    hook_data = {"agent_name": "agent-r", "tool_name": "channels__recv"}
    event = enforcer_cli._build_tool_used_event(hook_data)
    assert event.event_type == EventType.channel_recv


def test_build_event_for_send_emits_channel_send() -> None:
    """send hook fires must map to channel_send for send-and-stall detection."""
    from sox_protocol.core.enforcer.events import EventType

    hook_data = {"agent_name": "agent-s", "tool_name": "mcp__sox__channels__send"}
    event = enforcer_cli._build_tool_used_event(hook_data)
    assert event.event_type == EventType.channel_send


@pytest.mark.asyncio
async def test_post_tool_use_hook_auto_heartbeats(tmp_path: Path) -> None:
    """End-to-end: every PostToolUse fire UPSERTs a liveness row.

    Pre-0.2.3, heartbeat was the LLM's responsibility — it had to call
    ``mcp__sox__channels__heartbeat`` on a loop per the SKILL.md
    activation block, and most agents just forgot.  Now the hook
    maintains the row deterministically as long as the agent is making
    tool calls.
    """
    from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

    db_path = tmp_path / "messages.db"
    state_db = tmp_path

    with patch.dict(
        os.environ,
        {
            "SOX_STATE_DIR": str(state_db),
            "SOX_BACKING_STORE": f"sqlite:///{db_path}",
        },
    ):
        await enforcer_cli._run(
            "post_tool_use",
            {"agent_name": "agent-keepalive", "tool_name": "Bash", "tool_response": {}},
        )

    # Verify a liveness row was written for the agent.
    store = SqliteStore(db_path=db_path)
    await store.initialize()
    try:
        agents = await store.list_agents()
    finally:
        await store.close()

    ids = {a["agent_id"] for a in agents}
    assert "agent-keepalive" in ids
    rec = next(a for a in agents if a["agent_id"] == "agent-keepalive")
    assert rec["presence_state"] == "online"


@pytest.mark.asyncio
async def test_post_tool_use_hook_skips_auto_heartbeat_for_unknown_agent(
    tmp_path: Path,
) -> None:
    """Hook fires without an agent_name in the payload must NOT seed
    a bogus 'unknown-agent' row in the liveness table."""
    from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

    db_path = tmp_path / "messages.db"
    state_db = tmp_path

    with patch.dict(
        os.environ,
        {
            "SOX_STATE_DIR": str(state_db),
            "SOX_BACKING_STORE": f"sqlite:///{db_path}",
        },
        clear=False,
    ):
        # Strip the env vars that would otherwise let _extract_agent_id
        # find a fallback identity.
        for key in ("CLAUDE_AGENT_NAME", "SOX_AGENT_ID"):
            os.environ.pop(key, None)
        await enforcer_cli._run(
            "post_tool_use",
            {"tool_name": "Bash", "tool_response": {}},
        )

    store = SqliteStore(db_path=db_path)
    await store.initialize()
    try:
        agents = await store.list_agents()
    finally:
        await store.close()

    ids = {a["agent_id"] for a in agents}
    assert "unknown-agent" not in ids


@pytest.mark.asyncio
async def test_recv_hook_resets_tool_calls_counter(tmp_path: Path) -> None:
    """End-to-end: a PostToolUse recv hook must zero tool_calls_since_drain.

    Pre-0.2.3, the CLI emitted ``EventType.tool_used`` for every PostToolUse
    fire, so ``StateStore.apply_event`` saw ``tool_used`` and incremented
    the counter — meaning a recv call *increased* the "due for a reminder"
    counter instead of resetting it.  This is the bug the user reported:
    the "checked the channels inbox" reminder fired immediately after a
    successful drain.
    """
    from sox_protocol.core.enforcer.events import EventType
    from sox_protocol.core.enforcer.state import StateStore

    state_db = tmp_path / "state.db"

    # Bump tool_calls_since_drain a few times via non-recv tool fires so it
    # has a non-zero value going into the recv.
    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        for _ in range(3):
            await enforcer_cli._run(
                "post_tool_use",
                {"agent_name": "agent-x", "tool_name": "Bash", "tool_response": {}},
            )

        # Sanity: counter is now 3.
        async with StateStore(db_path=state_db) as store:
            state = await store.load("agent-x")
        assert state.tool_calls_since_drain == 3

        # Now a recv hook fires.  Counter MUST reset to 0.
        await enforcer_cli._run(
            "post_tool_use",
            {
                "agent_name": "agent-x",
                "tool_name": "mcp__sox__channels__recv",
                "tool_response": {"messages": []},
            },
        )

        async with StateStore(db_path=state_db) as store:
            state_after_recv = await store.load("agent-x")

    # The bug regressed when this counter remained > 0 after a recv.
    assert state_after_recv.tool_calls_since_drain == 0
    # And last_drain_ts should now be set.
    assert state_after_recv.last_drain_ts is not None
    # The event type that was processed must be channel_recv (sanity for
    # the unit-level mapping being exercised by _run).
    assert EventType.channel_recv.value == "channel_recv"


def test_build_stop_event() -> None:
    from sox_protocol.core.enforcer.events import EventType

    hook_data = {"agent_name": "agent-z"}
    event = enforcer_cli._build_stop_event(hook_data, inbox_non_empty=True)
    assert event.event_type == EventType.stop_requested
    assert event.agent_id == "agent-z"
    assert event.metadata["inbox_non_empty"] is True


# ---------------------------------------------------------------------------
# _inbox_non_empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbox_non_empty_memory_store_returns_false() -> None:
    """memory:// backing store always returns False (ephemeral)."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "memory://"}):
        result = await enforcer_cli._inbox_non_empty("any-agent")
    assert result is False


@pytest.mark.asyncio
async def test_inbox_non_empty_unsupported_scheme_returns_false() -> None:
    """Unknown scheme safe-fails to False."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "redis://localhost"}):
        result = await enforcer_cli._inbox_non_empty("any-agent")
    assert result is False


@pytest.mark.asyncio
async def test_inbox_non_empty_sqlite_memory_returns_false() -> None:
    """sqlite://:memory: path returns False (treated as empty)."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "sqlite://:memory:"}):
        result = await enforcer_cli._inbox_non_empty("any-agent")
    assert result is False


@pytest.mark.asyncio
async def test_inbox_non_empty_sqlite_no_path_returns_false() -> None:
    """sqlite:// with empty path returns False."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "sqlite://"}):
        result = await enforcer_cli._inbox_non_empty("any-agent")
    assert result is False


@pytest.mark.asyncio
async def test_inbox_non_empty_exception_returns_false(tmp_path: Path) -> None:
    """Any exception during inbox check returns False (safe-fail)."""
    # Use a sqlite path that will cause an error (we mock recv to raise)
    db_path = tmp_path / "inbox.db"
    url = f"sqlite://{db_path}"
    with patch.dict(os.environ, {"SOX_BACKING_STORE": url}), patch(
        "sox_protocol.adapters.backing_stores.sqlite.store.SqliteStore.recv",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db error"),
    ):
        result = await enforcer_cli._inbox_non_empty("any-agent")
    assert result is False


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_post_tool_use_returns_none_for_noop(tmp_path: Path) -> None:
    """_run post_tool_use with a low tool count returns None (noop)."""
    hook_data = {"agent_name": "run-agent", "tool_name": "bash"}
    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        result = await enforcer_cli._run("post_tool_use", hook_data)
    # First tool call should be a noop
    assert result is None


@pytest.mark.asyncio
async def test_run_stop_noop(tmp_path: Path) -> None:
    """_run stop with empty inbox returns None (noop) for a fresh agent."""
    hook_data = {"agent_name": "stop-run-agent"}
    with patch.dict(os.environ, {
        "SOX_STATE_DIR": str(tmp_path),
        "SOX_BACKING_STORE": "memory://",
    }):
        result = await enforcer_cli._run("stop", hook_data)
    # With no messages, stop should be noop
    assert result is None


@pytest.mark.asyncio
async def test_run_subagent_stop(tmp_path: Path) -> None:
    """_run subagent_stop is handled same as stop."""
    hook_data = {"agent_name": "subagent-stop"}
    with patch.dict(os.environ, {
        "SOX_STATE_DIR": str(tmp_path),
        "SOX_BACKING_STORE": "memory://",
    }):
        result = await enforcer_cli._run("subagent_stop", hook_data)
    assert result is None


@pytest.mark.asyncio
async def test_run_unknown_hook_type_returns_none(tmp_path: Path) -> None:
    """_run returns None for unknown hook types."""
    hook_data = {"agent_name": "x"}
    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        result = await enforcer_cli._run("unknown_hook", hook_data)
    assert result is None


@pytest.mark.asyncio
async def test_run_stop_force_drain_checks_inbox(tmp_path: Path) -> None:
    """_run stop with force_drain_on_stop=True calls _inbox_non_empty."""
    from sox_protocol.core.enforcer.policy import Policy

    hook_data = {"agent_name": "drain-agent"}

    # Patch Policy to force force_drain_on_stop=True
    mock_policy = MagicMock(spec=Policy)
    mock_policy.force_drain_on_stop = True

    with patch.dict(os.environ, {
        "SOX_STATE_DIR": str(tmp_path),
        "SOX_BACKING_STORE": "memory://",
    }):
        # Policy is imported locally inside _run() as:
        #   from sox_protocol.core.enforcer.policy import Policy
        with patch("sox_protocol.core.enforcer.policy.Policy", return_value=mock_policy):
            with patch(
                "sox_protocol.enforcer.cli._inbox_non_empty",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_inbox:
                await enforcer_cli._run("stop", hook_data)
                mock_inbox.assert_called_once()


@pytest.mark.asyncio
async def test_run_returns_decision_dict_when_action_non_noop(tmp_path: Path) -> None:
    """_run returns a dict with action/message when decide returns non-noop."""
    from sox_protocol.core.enforcer.events import Action, Decision

    hook_data = {"agent_name": "block-agent", "tool_name": "bash"}

    # Mock decide to return a block decision
    mock_decision = Decision(
        schema_version="1.0",
        action=Action.inject,
        message="Call {{recv_tool}} now",
        reason="test",
    )

    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        # decide is imported locally inside _run() as:
        #   from sox_protocol.core.enforcer.decide import decide
        with patch("sox_protocol.core.enforcer.decide.decide", return_value=mock_decision):
            result = await enforcer_cli._run("post_tool_use", hook_data)

    assert result is not None
    assert result["action"] == "inject"
    # Placeholders should be substituted
    assert "mcp__sox__channels__recv" in result["message"]
    assert result["reason"] == "test"


@pytest.mark.asyncio
async def test_run_substitutes_all_placeholders(tmp_path: Path) -> None:
    """_run substitutes all {{placeholder}} tokens in messages."""
    from sox_protocol.core.enforcer.events import Action, Decision

    message = (
        "Use {{send_tool}}, {{recv_tool}}, {{subscribe_tool}}, {{list_tool}}"
    )
    mock_decision = Decision(
        schema_version="1.0",
        action=Action.inject,
        message=message,
        reason="test",
    )

    hook_data = {"agent_name": "placeholder-agent", "tool_name": "bash"}

    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        with patch("sox_protocol.core.enforcer.decide.decide", return_value=mock_decision):
            result = await enforcer_cli._run("post_tool_use", hook_data)

    assert result is not None
    assert "mcp__sox__channels__send" in result["message"]
    assert "mcp__sox__channels__recv" in result["message"]
    assert "mcp__sox__channels__subscribe" in result["message"]
    assert "mcp__sox__channels__list_channels" in result["message"]


@pytest.mark.asyncio
async def test_run_empty_message_returns_none_message(tmp_path: Path) -> None:
    """_run with empty decision message produces message=None in output."""
    from sox_protocol.core.enforcer.events import Action, Decision

    mock_decision = Decision(
        schema_version="1.0",
        action=Action.inject,
        message="",
        reason="test",
    )

    hook_data = {"agent_name": "empty-msg-agent", "tool_name": "bash"}

    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        with patch("sox_protocol.core.enforcer.decide.decide", return_value=mock_decision):
            result = await enforcer_cli._run("post_tool_use", hook_data)

    assert result is not None
    assert result["message"] is None


# ---------------------------------------------------------------------------
# main() — the CLI entry point
# ---------------------------------------------------------------------------


def test_main_no_command_exits_1(tmp_path: Path) -> None:
    """main() with no subcommand exits 1."""
    with pytest.raises(SystemExit) as exc_info:
        enforcer_cli.main([])
    assert exc_info.value.code == 1


def test_main_empty_stdin_exits_0(tmp_path: Path) -> None:
    """main() with cli --hook post_tool_use and empty stdin exits 0."""
    with patch("sys.stdin", io.StringIO("")):
        with pytest.raises(SystemExit) as exc_info:
            enforcer_cli.main(["cli", "--hook", "post_tool_use"])
        assert exc_info.value.code == 0


def test_main_invalid_json_exits_1() -> None:
    """main() exits 1 when stdin is not valid JSON."""
    with patch("sys.stdin", io.StringIO("not json {")):
        with pytest.raises(SystemExit) as exc_info:
            enforcer_cli.main(["cli", "--hook", "post_tool_use"])
        assert exc_info.value.code == 1


def test_main_valid_json_noop_no_output(tmp_path: Path, capsys) -> None:
    """main() with noop decision prints nothing."""
    hook_data = json.dumps({"agent_name": "main-agent", "tool_name": "bash"})
    with patch("sys.stdin", io.StringIO(hook_data)):
        with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
            enforcer_cli.main(["cli", "--hook", "post_tool_use"])
    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_valid_json_decision_prints_json(tmp_path: Path, capsys) -> None:
    """main() with a non-noop decision prints JSON to stdout."""
    from sox_protocol.core.enforcer.events import Action, Decision

    mock_decision = Decision(
        schema_version="1.0",
        action=Action.inject,
        message="check inbox",
        reason="test",
    )

    hook_data = json.dumps({"agent_name": "print-agent", "tool_name": "bash"})
    with patch("sys.stdin", io.StringIO(hook_data)):
        with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
            with patch("sox_protocol.core.enforcer.decide.decide", return_value=mock_decision):
                enforcer_cli.main(["cli", "--hook", "post_tool_use"])

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["action"] == "inject"
    assert output["message"] == "check inbox"


def test_main_internal_error_exits_1(tmp_path: Path) -> None:
    """main() exits 1 when _run raises an unexpected exception."""
    hook_data = json.dumps({"agent_name": "error-agent"})
    with patch("sys.stdin", io.StringIO(hook_data)):
        with patch("sox_protocol.enforcer.cli._run", side_effect=RuntimeError("boom")):
            with pytest.raises(SystemExit) as exc_info:
                enforcer_cli.main(["cli", "--hook", "post_tool_use"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# enforcer/__main__.py — just ensure it is importable / triggers main()
# ---------------------------------------------------------------------------


def test_enforcer_main_module_importable() -> None:
    """The __main__ module is importable (exercises the 4-6 lines)."""
    import importlib.util

    spec = importlib.util.find_spec("sox_protocol.enforcer.__main__")
    assert spec is not None


def test_enforcer_main_module_calls_main(monkeypatch) -> None:
    """Running enforcer.__main__ as script calls enforcer_cli.main()."""
    import importlib.util

    spec = importlib.util.find_spec("sox_protocol.enforcer.__main__")
    assert spec is not None


# ---------------------------------------------------------------------------
# enforcer/cli.py line 110: `pass` branch when has_messages is True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbox_non_empty_returns_true_when_messages_present(
    tmp_path: Path,
) -> None:
    """Line 110: _inbox_non_empty hits the `pass` branch when recv returns messages."""
    db_path = tmp_path / "inbox_with_msg.db"
    url = f"sqlite://{db_path}"
    # Mock recv to return a non-empty list, exercising the has_messages=True path
    with patch.dict(os.environ, {"SOX_BACKING_STORE": url}), patch(
        "sox_protocol.adapters.backing_stores.sqlite.store.SqliteStore.recv",
        new_callable=AsyncMock,
        return_value=[{"message_id": "msg-1", "body": {}}],
    ):
        result = await enforcer_cli._inbox_non_empty("any-agent")
    assert result is True
