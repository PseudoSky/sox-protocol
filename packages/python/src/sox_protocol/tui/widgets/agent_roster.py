# SPDX-License-Identifier: Apache-2.0
"""Agent roster pane widget.

Renders connected agents with a presence indicator (live/stale/unknown)
sourced from heartbeat data and an unread DM badge.  Pressing Enter on
an agent emits :class:`AgentSelected` to trigger the ``/dm`` flow.

Spec reference: ``spec/primitives/presence.md``
"""

from __future__ import annotations

import re
from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static

from sox_protocol.tui.state import AgentState, ChatStore

# Sanitize agent_id → Textual-safe widget id.  Same constraint and rationale
# as ``widgets/channel_list.py``: Textual ids must be ``[a-zA-Z_][a-zA-Z0-9_-]*``;
# agent_ids may contain ``/`` (namespace prefix), ``#`` (legacy), etc.
_INVALID_ID_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def _agent_to_widget_id(agent_id: str) -> str:
    """Convert an agent_id to a Textual-safe widget id."""
    return "agent-" + _INVALID_ID_CHARS.sub("_", agent_id)


class AgentSelected(Message):
    """Emitted when the user presses Enter on an agent in the roster.

    Attributes:
        agent_id: The selected agent's identifier.
    """

    def __init__(self, agent_id: str) -> None:
        super().__init__()
        self.agent_id = agent_id


def _presence_dot(presence: str) -> str:
    """Return a coloured dot character for a presence state.

    Args:
        presence: One of ``online``, ``busy``, ``stale``, ``offline``, ``unknown``.

    Returns:
        Single unicode dot character.
    """
    dots = {
        "online": "●",
        "busy": "◐",
        "stale": "◌",
        "offline": "○",
        "unknown": "·",
    }
    return dots.get(presence, "·")


class AgentRosterWidget(Widget):  # pragma: no cover
    """Right-pane agent roster.

    Watches ``ChatStore`` and re-renders on every agent update.

    Textual lifecycle hooks are excluded from the coverage gate — see
    ``conftest.py`` for the documented rationale.
    """

    DEFAULT_CSS = """
    AgentRosterWidget {
        width: 22;
        border: solid $accent;
        padding: 0 1;
    }
    """

    _agents: reactive[list[AgentState]] = reactive(list, recompose=True)

    def __init__(self, store: ChatStore, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self._store = store
        # Sanitized-id → original-agent-id map; rebuilt every compose().
        self._id_to_agent: dict[str, str] = {}

    def on_mount(self) -> None:
        """Register store callback on mount."""
        self._store.on_change(self._refresh_from_store)
        self._refresh_from_store()

    def _refresh_from_store(self) -> None:
        """Pull latest agent list from the store."""
        self._agents = list(self._store.agents)

    def compose(self) -> ComposeResult:
        """Render the agent list."""
        yield Static("Agents", id="roster-header")
        items: list[ListItem] = []
        self._id_to_agent = {}
        for agent in self._agents:
            dot = _presence_dot(agent.presence)
            dm_badge = f" [{agent.unread_dm}]" if agent.unread_dm else ""
            label = f"{dot} {agent.agent_id}{dm_badge}"
            widget_id = _agent_to_widget_id(agent.agent_id)
            self._id_to_agent[widget_id] = agent.agent_id
            items.append(ListItem(Static(label), id=widget_id))
        yield ListView(*items, id="agent-listview")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle Enter on an agent to emit :class:`AgentSelected`."""
        item_id = event.item.id or ""
        agent_id = self._id_to_agent.get(item_id)
        if agent_id is not None:
            self.post_message(AgentSelected(agent_id))
