# SPDX-License-Identifier: Apache-2.0
"""Integration tests for the ``sox-protocol channels`` and ``config`` CLI.

Exercises the full subprocess invocation path to prove the CLI wires
through to the BackingStore correctly — the same scenario the chat TUI
hits when it shares a SQLite file with a Claude Code agent's MCP server.

Each test points the CLI at an isolated tmp-path SQLite file via
``SOX_BACKING_STORE`` so they don't collide with the developer's local
``~/.sox`` or repo-root state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m sox_protocol.cli ...`` as a subprocess.

    Captures stdout+stderr; raises if non-zero exit.
    """
    cmd = [sys.executable, "-m", "sox_protocol.cli", *args]
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    result = subprocess.run(
        cmd,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


@pytest.fixture
def db_uri(tmp_path: Path) -> str:
    """Return a SOX_BACKING_STORE URI pointing at a tmp_path-scoped SQLite file."""
    db_path = tmp_path / "channels-cli.db"
    return f"sqlite:///{db_path}"


def test_heartbeat_then_list_agents_round_trip(db_uri: str) -> None:
    """A heartbeat in one CLI invocation is visible from a second one."""
    env = {"SOX_BACKING_STORE": db_uri}

    hb = _cli("channels", "heartbeat", "--agent-id", "alice", "--ttl", "120", "--compact", env=env)
    assert hb.returncode == 0, hb.stderr
    parsed_hb = json.loads(hb.stdout)
    assert parsed_hb["agent_id"] == "alice"
    assert parsed_hb["status"] == "online"

    listed = _cli("channels", "list-agents", "--compact", env=env)
    assert listed.returncode == 0, listed.stderr
    payload = json.loads(listed.stdout)
    ids = {a["agent_id"] for a in payload["agents"]}
    assert ids == {"alice"}


def test_send_then_recv_round_trip(db_uri: str) -> None:
    """Subscribe + send + recv across separate CLI invocations."""
    env = {"SOX_BACKING_STORE": db_uri}

    sub = _cli(
        "channels", "subscribe", "agent/alice",
        "--agent-id", "alice", "--compact",
        env=env,
    )
    assert sub.returncode == 0, sub.stderr

    send = _cli(
        "channels", "send", "agent/alice",
        "--text", "hi alice",
        "--agent-id", "bob",
        "--compact",
        env=env,
    )
    assert send.returncode == 0, send.stderr
    receipt = json.loads(send.stdout)
    assert receipt["channel"] == "agent/alice"
    assert receipt["sender"] == "bob"
    assert receipt["seq"] == 1

    recv = _cli(
        "channels", "recv",
        "--channel", "agent/alice",
        "--agent-id", "alice",
        "--compact",
        env=env,
    )
    assert recv.returncode == 0, recv.stderr
    msgs = json.loads(recv.stdout)["messages"]
    assert len(msgs) == 1
    assert msgs[0]["body"] == {"text": "hi alice"}
    assert msgs[0]["sender"] == "bob"


def test_send_with_json_body(db_uri: str) -> None:
    """`--body` accepts a JSON object literal verbatim."""
    env = {"SOX_BACKING_STORE": db_uri}

    _cli("channels", "subscribe", "ticket/X", "--agent-id", "agent1", "--compact", env=env)
    send = _cli(
        "channels", "send", "ticket/X",
        "--body", '{"kind": "review_request", "ticket_id": "X-42"}',
        "--agent-id", "agent1",
        "--compact",
        env=env,
    )
    assert send.returncode == 0, send.stderr

    recv = _cli(
        "channels", "recv", "--channel", "ticket/X", "--agent-id", "agent1", "--compact", env=env
    )
    msgs = json.loads(recv.stdout)["messages"]
    assert msgs[0]["body"]["kind"] == "review_request"
    assert msgs[0]["body"]["ticket_id"] == "X-42"


def test_send_text_and_body_both_rejected(db_uri: str) -> None:
    """Passing both --text and --body is a clear error."""
    env = {"SOX_BACKING_STORE": db_uri}
    result = _cli(
        "channels", "send", "ch1",
        "--text", "x",
        "--body", '{"y": 1}',
        env=env,
    )
    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert "--text" in combined and "--body" in combined


def test_send_missing_body_is_rejected(db_uri: str) -> None:
    """Send without a body is a clear error (not a silent empty message)."""
    env = {"SOX_BACKING_STORE": db_uri}
    result = _cli("channels", "send", "ch1", env=env)
    assert result.returncode != 0


def test_subscribe_then_list_channels(db_uri: str) -> None:
    """After subscribe, the channel appears in list-channels even before send."""
    env = {"SOX_BACKING_STORE": db_uri}
    _cli("channels", "subscribe", "team/eng", "--agent-id", "lead", "--compact", env=env)
    out = _cli("channels", "list-channels", "--compact", env=env)
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    names = {c["name"] for c in payload["channels"]}
    assert "team/eng" in names


def test_unsubscribe_drops_subscription(db_uri: str) -> None:
    env = {"SOX_BACKING_STORE": db_uri}
    _cli("channels", "subscribe", "team/eng", "--agent-id", "lead", "--compact", env=env)
    out = _cli("channels", "unsubscribe", "team/eng", "--agent-id", "lead", "--compact", env=env)
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert "team/eng" in payload["removed_patterns"]


def test_replay_returns_seq_ordered_messages(db_uri: str) -> None:
    """Replay returns messages in seq order even after they were drained."""
    env = {"SOX_BACKING_STORE": db_uri}
    _cli("channels", "subscribe", "log/x", "--agent-id", "writer", "--compact", env=env)
    for i in range(3):
        _cli(
            "channels", "send", "log/x",
            "--text", f"msg-{i}",
            "--agent-id", "writer", "--compact",
            env=env,
        )
    out = _cli("channels", "replay", "log/x", "--compact", env=env)
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    bodies = [m["body"]["text"] for m in payload["messages"]]
    assert bodies == ["msg-0", "msg-1", "msg-2"]


def test_config_outputs_valid_json(tmp_path: Path) -> None:
    """`sox-protocol config` produces a well-formed JSON snapshot."""
    out = _cli("config", "--project-dir", str(tmp_path), "--compact")
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    # Sentinel keys we expect to always be present.
    assert "sox_protocol_version" in payload
    assert "agent_id" in payload
    assert "backing_store" in payload
    assert "discovery" in payload
    assert payload["claude_code"]["mcp_server_registered"] is False
    assert payload["skill"]["present"] is False


def test_config_picks_up_mcp_json(tmp_path: Path) -> None:
    """When .mcp.json exists, config shows the discovered path and env."""
    mcp_json = tmp_path / ".mcp.json"
    mcp_json.write_text(json.dumps({
        "mcpServers": {
            "sox": {
                "type": "stdio",
                "command": "sox-mcp-server",
                "env": {
                    "SOX_BACKING_STORE": "sqlite:///tmp/configtest.db",
                    "SOX_AGENT_ID_SOURCE": "env:SOX_AGENT_NAME",
                },
            }
        }
    }))

    out = _cli("config", "--project-dir", str(tmp_path), "--compact")
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload["discovery"]["mcp_json_path"] == str(mcp_json)
    assert payload["env"]["SOX_AGENT_ID_SOURCE"] == "env:SOX_AGENT_NAME"
    assert payload["backing_store"]["uri"] == "sqlite:///tmp/configtest.db"


def test_two_separate_invocations_share_liveness(db_uri: str) -> None:
    """Heartbeats from two CLI invocations are visible to a third — the
    cross-process scenario that motivated the v1.3 schema bump.
    """
    env = {"SOX_BACKING_STORE": db_uri}
    _cli("channels", "heartbeat", "--agent-id", "alice", "--ttl", "60", "--compact", env=env)
    _cli("channels", "heartbeat", "--agent-id", "bob", "--ttl", "60", "--status", "busy", "--compact", env=env)

    listed = _cli("channels", "list-agents", "--compact", env=env)
    assert listed.returncode == 0, listed.stderr
    agents = json.loads(listed.stdout)["agents"]
    by_id = {a["agent_id"]: a for a in agents}
    assert set(by_id) == {"alice", "bob"}
    assert by_id["alice"]["presence_state"] == "online"
    assert by_id["bob"]["presence_state"] == "busy"
