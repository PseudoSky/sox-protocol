# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for SoxChatApp using a fake McpStdioClient.

These tests exercise the CLI wiring and SoxChatApp constructor paths
without launching the full Textual TUI (which requires a TTY and is
excluded from the coverage gate per conftest.py).

Coverage note (documented in conftest.py):
  The Textual rendering glue — ``compose()``, ``on_mount()``,
  ``on_unmount()``, and action methods — is marked ``# pragma: no cover``
  on the ``SoxChatApp`` class declaration because:
  1. Textual requires a running reactor (TTY or headless pilot).
  2. The pilot API is async and interacts with the Textual event loop in
     ways that are hard to isolate without the full framework.
  The pure logic (ChatStore mutations, command dispatch) is fully covered
  by test_state.py, test_commands.py, test_pump.py, and test_mcp_client.py.
"""

from __future__ import annotations

import argparse

import pytest

from sox_protocol.cli.chat import chat_command, register_subparser
from sox_protocol.tui.app import SoxChatApp, run
from sox_protocol.tui.mcp_client import McpStdioClient
from sox_protocol.tui.state import ChatStore

# ---------------------------------------------------------------------------
# CLI subcommand wiring
# ---------------------------------------------------------------------------


def test_chat_subcommand_help() -> None:
    """sox-protocol chat --help should not raise."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "sox_protocol.cli", "chat", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "chat" in result.stdout.lower() or "tui" in result.stdout.lower()


def test_register_subparser_adds_chat() -> None:
    """register_subparser should add 'chat' to the subparsers."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_subparser(subparsers)
    args = parser.parse_args(["chat", "--agent-id", "test-agent"])
    assert args.agent_id == "test-agent"


def test_register_subparser_defaults() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_subparser(subparsers)
    args = parser.parse_args(["chat"])
    assert args.agent_id == "tui-user"
    assert args.channel == "#general"
    assert not args.no_spawn
    assert args.server_cmd is None


def test_register_subparser_no_spawn_flag() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_subparser(subparsers)
    args = parser.parse_args(["chat", "--no-spawn"])
    assert args.no_spawn is True


def test_register_subparser_server_cmd() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_subparser(subparsers)
    args = parser.parse_args(["chat", "--server-cmd", "python -m myserver"])
    assert args.server_cmd == "python -m myserver"


# ---------------------------------------------------------------------------
# SoxChatApp constructor
# ---------------------------------------------------------------------------


def test_app_raises_without_client_and_no_spawn() -> None:
    """SoxChatApp should raise ValueError when spawn_server=False and no client."""
    with pytest.raises(ValueError, match="Either pass a client"):
        SoxChatApp(spawn_server=False)


def test_app_accepts_client() -> None:
    """SoxChatApp should accept a pre-built McpStdioClient."""
    client = McpStdioClient()
    app = SoxChatApp(client=client, spawn_server=False)
    assert app._client is client


def test_app_creates_store() -> None:
    """SoxChatApp should create a ChatStore on init."""
    client = McpStdioClient()
    app = SoxChatApp(client=client, spawn_server=False)
    assert isinstance(app._store, ChatStore)


def test_app_spawn_server_true_creates_process_client() -> None:
    """SoxChatApp with spawn_server=True creates a McpStdioClient with a process."""
    app = SoxChatApp(agent_id="test-user", spawn_server=True)
    assert app._client is not None
    assert app._client._process is not None


def test_app_server_env_forwarded() -> None:
    """server_env dict should be forwarded to the ServerProcess."""
    app = SoxChatApp(
        agent_id="test",
        spawn_server=True,
        server_env={"MY_VAR": "val"},
    )
    assert app._server_env.get("MY_VAR") == "val"


# ---------------------------------------------------------------------------
# run() function import
# ---------------------------------------------------------------------------


def test_run_is_callable() -> None:
    """run() should be importable and callable."""
    assert callable(run)


# ---------------------------------------------------------------------------
# chat_command with no_spawn path (mocked run)
# ---------------------------------------------------------------------------


def test_chat_command_no_spawn_calls_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat_command with --no-spawn should call run() with spawn_server=False."""
    calls: list[dict[str, object]] = []

    def mock_run(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("sox_protocol.cli.chat.run", mock_run)

    args = argparse.Namespace(
        agent_id="test-agent",
        channel="#eng",
        no_spawn=True,
        server_cmd=None,
    )
    rc = chat_command(args)
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["spawn_server"] is False
    assert calls[0]["agent_id"] == "test-agent"


def test_chat_command_spawn_calls_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat_command with spawn=True should call run() with spawn_server=True."""
    calls: list[dict[str, object]] = []

    def mock_run(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("sox_protocol.cli.chat.run", mock_run)

    args = argparse.Namespace(
        agent_id="tui-user",
        channel="#general",
        no_spawn=False,
        server_cmd=None,
    )
    rc = chat_command(args)
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["spawn_server"] is True


def test_chat_command_server_cmd_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """server_cmd should be passed via server_env."""
    calls: list[dict[str, object]] = []

    def mock_run(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("sox_protocol.cli.chat.run", mock_run)

    args = argparse.Namespace(
        agent_id="user",
        channel="#general",
        no_spawn=False,
        server_cmd="python -m custom_server",
    )
    rc = chat_command(args)
    assert rc == 0
    env = calls[0].get("server_env", {})
    assert isinstance(env, dict)
    assert env.get("SOX_TUI_SERVER_CMD") == "python -m custom_server"
