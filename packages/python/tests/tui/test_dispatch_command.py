# SPDX-License-Identifier: Apache-2.0
"""Tests for ``SoxChatApp._dispatch_command``.

Verifies that the compose-bar Enter path:
  1. Plain text → SendCommand → ``client.send(channel, body={"text": ...})``
  2. ``/reply <id> <text>`` → ReplyCommand → ``client.send(..., reply_to=...)``
  3. ``/dm <agent>`` → DmCommand → ``client.subscribe(...)`` + focus
  4. ``/join <channel>`` → JoinCommand → ``client.subscribe(...)`` + focus

And — critically — that errors from the underlying MCP call are surfaced
to the user via the compose bar's placeholder rather than swallowed
silently (the bug: pre-0.2.4 ``except: pass`` masked every send failure).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sox_protocol.tui.app import SoxChatApp
from sox_protocol.tui.commands import DmCommand, JoinCommand, ReplyCommand, SendCommand


def _build_app_with_mock_client() -> tuple[SoxChatApp, MagicMock]:
    """Construct a SoxChatApp with a mocked McpStdioClient."""
    client = MagicMock()
    client.send = AsyncMock(return_value={"message_id": "1", "seq": 1, "sent_at": 0.0})
    client.subscribe = AsyncMock(return_value=[])
    app = SoxChatApp(
        client=client,
        agent_id="alice",
        initial_channel="#general",
        spawn_server=False,
    )
    # Pretend the user is focused on #general so SendCommand picks it up.
    app._store.focus_channel("#general")
    return app, client


@pytest.mark.asyncio
async def test_dispatch_send_command_calls_client_send() -> None:
    app, client = _build_app_with_mock_client()
    await app._dispatch_command(SendCommand(text="hello world"))

    client.send.assert_awaited_once()
    call = client.send.await_args
    assert call.kwargs["channel"] == "#general"
    assert call.kwargs["body"] == {"text": "hello world"}


@pytest.mark.asyncio
async def test_dispatch_reply_command_passes_reply_to() -> None:
    app, client = _build_app_with_mock_client()
    await app._dispatch_command(
        ReplyCommand(reply_to="msg-42", text="response")
    )

    client.send.assert_awaited_once()
    call = client.send.await_args
    assert call.kwargs["body"] == {"text": "response"}
    assert call.kwargs["reply_to"] == "msg-42"


@pytest.mark.asyncio
async def test_dispatch_dm_command_subscribes_and_focuses() -> None:
    app, client = _build_app_with_mock_client()
    await app._dispatch_command(
        DmCommand(target_agent="bob", channel="dm/alice+bob", self_agent="alice")
    )

    client.subscribe.assert_awaited_once_with("dm/alice+bob")
    assert app._store.focused_channel == "dm/alice+bob"


@pytest.mark.asyncio
async def test_dispatch_join_command_subscribes_and_focuses() -> None:
    app, client = _build_app_with_mock_client()
    await app._dispatch_command(JoinCommand(channel="team/eng"))

    client.subscribe.assert_awaited_once_with("team/eng")
    assert app._store.focused_channel == "team/eng"


@pytest.mark.asyncio
async def test_dispatch_send_failure_does_not_raise() -> None:
    """A failed client.send must not propagate — the compose bar has to
    keep working even after a transient error."""
    app, client = _build_app_with_mock_client()
    client.send = AsyncMock(side_effect=RuntimeError("connection refused"))

    # Should NOT raise.
    await app._dispatch_command(SendCommand(text="test"))


@pytest.mark.asyncio
async def test_dispatch_send_falls_back_to_general_when_no_focused_channel() -> None:
    """If somehow no channel is focused (e.g. user did /quit then typed),
    the send falls back to #general rather than crashing."""
    app, client = _build_app_with_mock_client()
    app._store._focused_channel = None  # type: ignore[attr-defined]

    await app._dispatch_command(SendCommand(text="hello"))

    call = client.send.await_args
    assert call is not None
    assert call.kwargs["channel"] == "#general"


# ---------------------------------------------------------------------------
# Selection paths: clicking a channel / agent must subscribe + focus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_then_focus_subscribes_and_updates_focus() -> None:
    """Selecting a channel via the GUI subscribes the user, then focuses.

    Pre-0.2.4 ``on_channel_focused`` and ``on_agent_selected`` only
    called ``focus_channel``.  A user who clicked a channel they
    weren't already subscribed to could send into it but never receive
    incoming traffic.  And clicking an agent in the roster opened a
    ``dm/<sorted-pair>`` focus that neither party was subscribed to,
    so messages sent there were invisible on both ends.
    """
    app, client = _build_app_with_mock_client()

    await app._subscribe_then_focus("team/eng")

    client.subscribe.assert_awaited_once_with("team/eng")
    assert app._store.focused_channel == "team/eng"


@pytest.mark.asyncio
async def test_subscribe_then_focus_still_focuses_on_subscribe_failure() -> None:
    """If subscribe fails, focus is still updated and the error is surfaced.

    Without this, a transient MCP blip could leave the user stuck on
    a stale channel.  The error path runs through ``_surface_dispatch_error``
    so the failure is visible in the compose-bar placeholder.
    """
    app, client = _build_app_with_mock_client()
    client.subscribe = AsyncMock(side_effect=RuntimeError("subscribe blip"))

    # Should NOT raise.
    await app._subscribe_then_focus("team/eng")

    # Focus moved despite the failure.
    assert app._store.focused_channel == "team/eng"
