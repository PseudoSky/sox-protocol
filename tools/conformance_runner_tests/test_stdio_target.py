# SPDX-License-Identifier: Apache-2.0
"""Tests for SharedMemoryTarget / StdioTarget: lifecycle, tool dispatch, recv polling."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conformance_runner import (
    SharedMemoryTarget,
    StdioTarget,
    _op_to_tool,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PKG = _REPO_ROOT / "packages" / "python"


class TestOpToTool:
    """Tests for _op_to_tool() name mapping."""

    def test_send_maps_correctly(self) -> None:
        assert _op_to_tool("send") == "channels__send"

    def test_recv_maps_correctly(self) -> None:
        assert _op_to_tool("recv") == "channels__recv"

    def test_subscribe_maps_correctly(self) -> None:
        assert _op_to_tool("subscribe") == "channels__subscribe"

    def test_unsubscribe_maps_correctly(self) -> None:
        assert _op_to_tool("unsubscribe") == "channels__unsubscribe"

    def test_list_channels_maps_correctly(self) -> None:
        assert _op_to_tool("list_channels") == "channels__list_channels"

    def test_channels_ack_maps_correctly(self) -> None:
        assert _op_to_tool("channels_ack") == "channels__ack"

    def test_channels_heartbeat_maps_correctly(self) -> None:
        assert _op_to_tool("channels_heartbeat") == "channels__heartbeat"

    def test_replay_maps_correctly(self) -> None:
        assert _op_to_tool("replay") == "channels__replay"

    def test_group_create_maps_correctly(self) -> None:
        assert _op_to_tool("group_create") == "channels__group_create"

    def test_unknown_op_gets_prefix(self) -> None:
        assert _op_to_tool("custom_op") == "channels__custom_op"


class TestSharedMemoryTargetLifecycle:
    """Tests for SharedMemoryTarget start/stop."""

    @pytest.mark.skipif(
        not _PYTHON_PKG.exists(), reason="packages/python not found"
    )
    def test_start_initialises_store(self) -> None:
        target = SharedMemoryTarget(_PYTHON_PKG)
        target.start("agent-test")
        assert target._store is not None
        target.stop()

    @pytest.mark.skipif(
        not _PYTHON_PKG.exists(), reason="packages/python not found"
    )
    def test_stop_is_idempotent(self) -> None:
        target = SharedMemoryTarget(_PYTHON_PKG)
        target.start("agent-test")
        target.stop()
        target.stop()  # Should not raise

    def test_start_bad_path_raises(self, tmp_path: Path) -> None:
        target = SharedMemoryTarget(tmp_path / "nonexistent")
        with pytest.raises((RuntimeError, Exception)):
            target.start("agent-x")


class TestSharedMemoryTargetDispatch:
    """Tests for SharedMemoryTarget.call_tool() dispatch."""

    @pytest.fixture(autouse=True)
    def setup_target(self) -> None:  # type: ignore[return]
        if not _PYTHON_PKG.exists():
            pytest.skip("packages/python not found")
        self.target = SharedMemoryTarget(_PYTHON_PKG)
        self.target.start("agent-dispatch")
        yield
        self.target.stop()

    def test_subscribe_returns_subscribed_list(self) -> None:
        result = self.target.call_tool("agent-dispatch", "subscribe", {"pattern": "test:*"})
        assert "subscribed" in result
        assert isinstance(result["subscribed"], list)

    def test_recv_returns_empty_initially(self) -> None:
        self.target.call_tool("agent-dispatch", "subscribe", {"pattern": "test:recv-empty"})
        result = self.target.call_tool("agent-dispatch", "recv", {})
        assert result["messages"] == []
        assert "drained_at" in result

    def test_send_returns_seq_and_message_id(self) -> None:
        result = self.target.call_tool("agent-a", "send", {
            "channel": "test:send",
            "body": {"type": "status_update", "subject": "hello"},
        })
        assert result["seq"] == 1
        assert result["message_id"]
        assert "backpressure" in result

    def test_send_then_recv_delivers_message(self) -> None:
        self.target.call_tool("agent-dispatch", "subscribe", {"pattern": "test:roundtrip"})
        send_result = self.target.call_tool("agent-sender", "send", {
            "channel": "test:roundtrip",
            "body": {"type": "status_update", "subject": "rt"},
        })
        recv_result = self.target.call_tool("agent-dispatch", "recv", {})
        assert len(recv_result["messages"]) == 1
        assert recv_result["messages"][0]["channel"] == "test:roundtrip"
        assert recv_result["messages"][0]["sender"] == "agent-sender"

    def test_seq_starts_at_one_per_channel(self) -> None:
        r1 = self.target.call_tool("agent-seq", "send", {
            "channel": "test:seq-new-channel",
            "body": {"x": 1},
        })
        assert r1["seq"] == 1

    def test_seq_increments_per_channel(self) -> None:
        for i in range(3):
            r = self.target.call_tool("agent-seq", "send", {
                "channel": "test:seq-inc",
                "body": {"i": i},
            })
            assert r["seq"] == i + 1

    def test_list_channels_returns_protocol_version(self) -> None:
        result = self.target.call_tool("agent-dispatch", "list_channels", {})
        assert "protocol_version" in result
        assert result["protocol_version"] == "1.0"

    def test_channels_ack_returns_acked_at(self) -> None:
        result = self.target.call_tool("agent-dispatch", "channels_ack", {
            "message_id": "msg-1",
            "status": "received",
        })
        assert "acked_at" in result

    def test_channels_heartbeat_emits_presence(self) -> None:
        self.target.call_tool("agent-dispatch", "subscribe", {"pattern": "sox/presence"})
        self.target.call_tool("agent-hb", "channels_heartbeat", {"status": "online"})
        recv = self.target.call_tool("agent-dispatch", "recv", {})
        assert any(m["channel"] == "sox/presence" for m in recv["messages"])

    def test_replay_returns_messages_since_seq(self) -> None:
        for i in range(4):
            self.target.call_tool("agent-replay", "send", {
                "channel": "test:replay-dispatch",
                "body": {"n": i + 1},
            })
        result = self.target.call_tool("agent-replay", "replay", {
            "channel": "test:replay-dispatch",
            "since_seq": 3,
        })
        assert "messages" in result
        assert len(result["messages"]) == 2

    def test_replay_beyond_last_seq_returns_empty(self) -> None:
        self.target.call_tool("agent-replay", "send", {
            "channel": "test:replay-beyond",
            "body": {"n": 1},
        })
        result = self.target.call_tool("agent-replay", "replay", {
            "channel": "test:replay-beyond",
            "since_seq": 999,
        })
        assert result["messages"] == []
        assert result["has_more"] is False

    def test_unsubscribe_removes_pattern(self) -> None:
        self.target.call_tool("agent-dispatch", "subscribe", {"pattern": "test:unsub-dispatch"})
        result = self.target.call_tool("agent-dispatch", "unsubscribe", {
            "patterns": ["test:unsub-dispatch"],
        })
        assert "unsubscribed" in result

    def test_unknown_operation_returns_error(self) -> None:
        result = self.target.call_tool("agent-dispatch", "totally_unknown_op", {})
        assert "_rpc_error" in result

    def test_group_lifecycle(self) -> None:
        create = self.target.call_tool("agent-owner", "group_create", {"group_id": "grp-dispatch"})
        assert "group_id" in create

        invite = self.target.call_tool("agent-owner", "group_invite", {
            "group_id": "group/grp-dispatch",
            "agent_id": "agent-member",
        })
        assert invite["invited_agent"] == "agent-member"

        join = self.target.call_tool("agent-member", "group_join", {
            "group_id": "group/grp-dispatch",
        })
        assert "joined_at" in join

        members = self.target.call_tool("agent-owner", "group_list_members", {
            "group_id": "group/grp-dispatch",
        })
        assert "members" in members

        leave = self.target.call_tool("agent-member", "group_leave", {
            "group_id": "group/grp-dispatch",
        })
        assert "left_at" in leave


class TestStdioTargetRpcParsing:
    """Tests for StdioTarget JSON-RPC framing logic (unit-level, mocked subprocess)."""

    def test_op_to_tool_send(self) -> None:
        assert _op_to_tool("send") == "channels__send"

    def test_stdio_target_instantiated(self) -> None:
        target = StdioTarget(_PYTHON_PKG)
        assert target._package_path == _PYTHON_PKG

    def test_next_id_increments(self) -> None:
        target = StdioTarget(_PYTHON_PKG)
        id1 = target._next_id()
        id2 = target._next_id()
        assert id2 == id1 + 1

    def test_stop_when_not_started_is_safe(self) -> None:
        target = StdioTarget(_PYTHON_PKG)
        target.stop()  # Should not raise


class TestHttpTargetInstantiation:
    """Tests for HttpTarget instantiation and basic attributes."""

    def test_http_target_stores_base_url(self) -> None:
        from conformance_runner import HttpTarget
        t = HttpTarget("http://localhost:9999")
        assert t._base_url == "http://localhost:9999"

    def test_http_target_strips_trailing_slash(self) -> None:
        from conformance_runner import HttpTarget
        t = HttpTarget("http://localhost:9999/")
        assert t._base_url == "http://localhost:9999"

    def test_http_target_stop_when_not_started(self) -> None:
        from conformance_runner import HttpTarget
        t = HttpTarget("http://localhost:9999")
        t.stop()  # Should not raise

    def test_http_target_call_tool_without_start_raises(self) -> None:
        from conformance_runner import HttpTarget
        t = HttpTarget("http://localhost:9999")
        with pytest.raises(RuntimeError, match="not started"):
            t.call_tool("agent-x", "recv", {})
