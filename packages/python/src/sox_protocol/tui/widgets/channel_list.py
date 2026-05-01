# SPDX-License-Identifier: Apache-2.0
"""Channel list pane widget.

Renders all subscribed channels grouped by prefix (``group/``, ``dm/``,
``sox/``, and free-form).  Highlights the active channel; shows unread
badge and subscriber count.  Emits :class:`ChannelFocused` on selection.

Spec reference: ``spec/primitives/channels.md``
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static

from sox_protocol.tui.state import ChannelState, ChatStore


class ChannelFocused(Message):
    """Emitted when the user selects a channel.

    Attributes:
        channel: The channel name that was selected.
    """

    def __init__(self, channel: str) -> None:
        super().__init__()
        self.channel = channel


class ChannelListWidget(Widget):  # pragma: no cover
    """Left-pane channel list.

    Watches ``ChatStore`` for changes and rebuilds the ``ListView``
    contents reactively.

    Textual lifecycle hooks (``on_mount``, ``compose``, event handlers)
    are excluded from the coverage gate via the ``# pragma: no cover``
    annotation on the class — the rendering glue is tested indirectly
    through the pilot smoke test.  Pure logic lives in ``state.py`` and
    ``commands.py`` which have 100% coverage.
    """

    DEFAULT_CSS = """
    ChannelListWidget {
        width: 24;
        border: solid $accent;
        padding: 0 1;
    }
    """

    _channels: reactive[list[ChannelState]] = reactive(list, recompose=True)

    def __init__(self, store: ChatStore, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self._store = store

    def on_mount(self) -> None:
        """Register store change callback on mount."""
        self._store.on_change(self._refresh_from_store)
        self._refresh_from_store()

    def _refresh_from_store(self) -> None:
        """Pull latest channels from the store and update reactive."""
        self._channels = list(self._store.channels)

    def compose(self) -> ComposeResult:
        """Render the channel list."""
        yield Static("Channels", id="channel-list-header")
        items: list[ListItem] = []
        for ch in self._channels:
            badge = f" [{ch.unread}]" if ch.unread else ""
            sub = f" ({ch.subscriber_count})" if ch.subscriber_count else ""
            label = f"{'> ' if ch.focused else '  '}{ch.name}{badge}{sub}"
            items.append(ListItem(Static(label), id=f"ch-{ch.name.replace('/', '-')}"))
        lv: ListView = ListView(*items, id="channel-listview")
        yield lv

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle channel selection and emit :class:`ChannelFocused`."""
        item_id = event.item.id or ""
        if item_id.startswith("ch-"):
            channel = item_id[3:].replace("-", "/", 1)
            self.post_message(ChannelFocused(channel))
