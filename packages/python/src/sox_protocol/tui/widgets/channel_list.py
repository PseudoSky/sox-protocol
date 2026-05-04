# SPDX-License-Identifier: Apache-2.0
"""Channel list pane widget.

Renders all subscribed channels grouped by prefix (``group/``, ``dm/``,
``sox/``, and free-form).  Highlights the active channel; shows unread
badge and subscriber count.  Emits :class:`ChannelFocused` on selection.

Spec reference: ``spec/primitives/channels.md``
"""

from __future__ import annotations

import re
from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static

from sox_protocol.tui.state import ChannelState, ChatStore

# Textual widget ids must match [a-zA-Z_][a-zA-Z0-9_-]* — letters, numbers,
# underscores, hyphens; must not start with a digit.  Channel names contain
# `/`, `#`, and other characters that aren't id-safe (e.g. ``#general``,
# ``group/live-e2e-test``, ``dm/alice/bob``).  We strip non-id-safe chars
# to underscores when generating widget ids, and keep a dict mapping the
# sanitized id back to the original channel name so selection events can
# recover the unmodified channel name without fragile reverse-string-mapping.
_INVALID_ID_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def _channel_to_widget_id(channel: str) -> str:
    """Convert a channel name to a Textual-safe widget id.

    Returns a string of the form ``ch-<sanitized>`` where every character
    outside ``[a-zA-Z0-9_-]`` is replaced with ``_``.  The leading ``ch-``
    prefix guarantees the id never starts with a digit.

    Note: this is intentionally lossy — two distinct channels could collide
    under sanitization (e.g. ``a#b`` and ``a/b`` both → ``ch-a_b``).  The
    widget instance maintains an id→channel map so the reverse lookup is
    exact for whichever channel was last bound to that id.  Practical
    collisions are unlikely because channel names follow the spec's prefix
    convention (``group/``, ``dm/``, ``sox/``).
    """
    return "ch-" + _INVALID_ID_CHARS.sub("_", channel)


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
        # Sanitized-id → original-channel-name map.  Rebuilt on every
        # compose() so it always reflects the currently-rendered list.
        self._id_to_channel: dict[str, str] = {}

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
        self._id_to_channel = {}
        for ch in self._channels:
            badge = f" [{ch.unread}]" if ch.unread else ""
            sub = f" ({ch.subscriber_count})" if ch.subscriber_count else ""
            label = f"{'> ' if ch.focused else '  '}{ch.name}{badge}{sub}"
            widget_id = _channel_to_widget_id(ch.name)
            self._id_to_channel[widget_id] = ch.name
            items.append(ListItem(Static(label), id=widget_id))
        lv: ListView = ListView(*items, id="channel-listview")
        yield lv

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle channel selection and emit :class:`ChannelFocused`."""
        item_id = event.item.id or ""
        channel = self._id_to_channel.get(item_id)
        if channel is not None:
            self.post_message(ChannelFocused(channel))
