# SPDX-License-Identifier: Apache-2.0
"""Pytest fixtures for conformance runner tests."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

# Ensure tools/ is on sys.path so `import conformance_runner` works when
# pytest is invoked from the repo root (e.g. `pytest tools/conformance_runner_tests/`).
_tools_dir = Path(__file__).parent.parent
if str(_tools_dir) not in sys.path:
    sys.path.insert(0, str(_tools_dir))


@pytest.fixture()
def tmp_fixture_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for writing fixture YAML files."""
    d = tmp_path / "conformance"
    d.mkdir()
    return d


@pytest.fixture()
def minimal_fixture_yaml() -> str:
    """Return a minimal valid fixture YAML string."""
    return textwrap.dedent("""\
        name: minimal-test
        spec_ref: spec/protocol.md
        description: Minimal fixture for testing.
        agents:
          - id: agent-a
            credential: secret-a
        setup: []
        sequence:
          - id: step-1
            as_agent: agent-a
            operation: recv
            input: {}
            expected_output:
              drained_at: "{{any_number}}"
              messages: []
        assertions: []
    """)


@pytest.fixture()
def minimal_fixture_file(tmp_fixture_dir: Path, minimal_fixture_yaml: str) -> Path:
    """Write a minimal fixture file and return its path."""
    p = tmp_fixture_dir / "test-fixture.yaml"
    p.write_text(minimal_fixture_yaml, encoding="utf-8")
    return p


@pytest.fixture()
def pending_fixture_yaml() -> str:
    """Return a pending fixture YAML string."""
    return textwrap.dedent("""\
        name: pending-test
        spec_ref: spec/protocol.md
        description: Pending fixture.
        pending: true
        agents:
          - id: agent-pending
            credential: secret-pending
        sequence:
          - id: pending-step
            as_agent: agent-pending
            operation: recv
            input: {}
        assertions: []
    """)


@pytest.fixture()
def pending_fixture_file(tmp_fixture_dir: Path, pending_fixture_yaml: str) -> Path:
    """Write a pending fixture file and return its path."""
    sub = tmp_fixture_dir / "channels-collect"
    sub.mkdir()
    p = sub / "pending-fixture.yaml"
    p.write_text(pending_fixture_yaml, encoding="utf-8")
    return p


class FakeTarget:
    """Fake target that returns configurable responses for testing."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.started = False
        self.stopped = False

    def start(self, agent_id: str) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def call_tool(self, agent_id: str, operation: str, args: dict[str, Any]) -> Any:
        self.calls.append((agent_id, operation, args))
        key = f"{agent_id}:{operation}"
        if key in self.responses:
            return self.responses[key]
        if operation in self.responses:
            return self.responses[operation]
        # Sensible defaults
        if operation == "recv":
            return {"drained_at": 1234567890.0, "messages": []}
        if operation == "send":
            return {
                "sent_at": 1234567890.0,
                "message_id": "msg-1",
                "seq": 1,
                "backpressure": {"queue_depth": 0, "threshold": 1000, "state": "ok"},
            }
        if operation == "subscribe":
            return {"subscribed": []}
        if operation == "unsubscribe":
            return {"unsubscribed": []}
        if operation == "list_channels":
            return {"channels": [], "protocol_version": "1.0"}
        if operation == "channels_ack":
            return {"acked_at": 1234567890.0, "status": "received"}
        if operation == "channels_heartbeat":
            return {"recorded_at": 1234567890.0, "status": "online"}
        if operation == "replay":
            return {"messages": [], "has_more": False}
        return {}


@pytest.fixture()
def fake_target() -> FakeTarget:
    """Return a fresh FakeTarget instance."""
    return FakeTarget()
