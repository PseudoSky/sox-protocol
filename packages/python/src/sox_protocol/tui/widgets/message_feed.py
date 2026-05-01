# SPDX-License-Identifier: Apache-2.0
"""Message feed pane widget.

Renders messages for the focused channel in a scrollable view.  Threads
are collapsed by default; pressing Enter on a parent message expands the
inline reply chain.  Each message shows sender, timestamp, body summary,
and ACK/NACK/pending status icon.

Spec reference: ``spec/primitives/threads.md``
"""

from __future__ import annotations

import datetime
from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static

from sox_protocol.tui.state import ChatStore, MessageState


class ThreadExpanded(Message):
    """Emitted when a thread is toggled.

    Attributes:
        message_id: The parent message whose thread was expanded/collapsed.
    """

    def __init__(self, message_id: str) -> None:
        super().__init__()
        self.message_id = message_id


def _status_icon(status: str) -> str:
    """Return a single-char icon for a message ACK status.

    Args:
        status: One of ``ack``, ``nack``, ``pending``.

    Returns:
        Unicode icon character.
    """
    icons = {"ack": "✓", "nack": "✗", "pending": "○"}
    return icons.get(status, "?")


def _format_ts(sent_at: float) -> str:
    """Format a Unix timestamp as HH:MM.

    Args:
        sent_at: Unix epoch seconds.

    Returns:
        Human-readable time string.
    """
    return datetime.datetime.fromtimestamp(sent_at).strftime("%H:%M")


def _body_summary(body: dict[str, object], max_len: int = 80) -> str:
    """Extract a short summary from a message body dict.

    Args:
        body: Opaque message body.
        max_len: Maximum characters before truncation.

    Returns:
        Short summary string.
    """
    text = str(body.get("text", body.get("subject", str(body))))
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


class MessageFeedWidget(Widget):  # pragma: no cover
    """Centre-pane message feed.

    Watches ``ChatStore`` and re-renders whenever the focused channel's
    messages change.  Collapsible threads via Enter on a parent message.

    Textual lifecycle hooks are excluded from the coverage gate — see
    ``conftest.py`` for the documented rationale.
    """

    DEFAULT_CSS = """
    MessageFeedWidget {
        border: solid $accent;
        padding: 0 1;
    }
    """

    _messages: reactive[list[MessageState]] = reactive(list, recompose=True)

    def __init__(self, store: ChatStore, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self._store = store

    def on_mount(self) -> None:
        """Register store callback on mount."""
        self._store.on_change(self._refresh_from_store)
        self._refresh_from_store()

    def _refresh_from_store(self) -> None:
        """Pull focused messages from the store."""
        self._messages = list(self._store.focused_messages())

    def compose(self) -> ComposeResult:
        """Render message list."""
        channel = self._store.focused_channel or "(no channel)"
        yield Static(f"# {channel}", id="feed-header")

        # Build message index for thread lookup
        msg_map: dict[str, MessageState] = {m.message_id: m for m in self._messages}
        rendered: list[ListItem] = []

        for msg in self._messages:
            # Skip replies when parent is not expanded
            if msg.reply_to and msg.reply_to in msg_map:
                parent = msg_map[msg.reply_to]
                if not parent.thread_expanded:
                    continue

            icon = _status_icon(msg.ack_status)
            ts = _format_ts(msg.sent_at)
            summary = _body_summary(msg.body)
            indent = "  " if msg.reply_to else ""
            thread_marker = " [+]" if not msg.thread_expanded else " [-]"
            # Only show thread marker on root messages that have replies
            has_replies = any(
                m.reply_to == msg.message_id for m in self._messages
            )
            marker = thread_marker if has_replies and not msg.reply_to else ""
            label = f"{indent}{icon} {ts} {msg.sender}: {summary}{marker}"
            item = ListItem(
                Static(label),
                id=f"msg-{msg.message_id}",
            )
            rendered.append(item)

        lv = ListView(*rendered, id="message-listview")
        yield lv

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle Enter on a message to toggle its thread."""
        item_id = event.item.id or ""
        if item_id.startswith("msg-"):
            message_id = item_id[4:]
            self._store.toggle_thread(message_id)
            self.post_message(ThreadExpanded(message_id))
