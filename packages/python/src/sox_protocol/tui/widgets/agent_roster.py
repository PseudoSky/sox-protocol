# SPDX-License-Identifier: Apache-2.0
"""Agent roster pane widget.

Renders connected agents with a presence indicator (live/stale/unknown)
sourced from heartbeat data and an unread DM badge.  Pressing Enter on
an agent emits :class:`AgentSelected` to trigger the ``/dm`` flow.

Spec reference: ``spec/primitives/presence.md``
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static

from sox_protocol.tui.state import AgentState, ChatStore


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
        for agent in self._agents:
            dot = _presence_dot(agent.presence)
            dm_badge = f" [{agent.unread_dm}]" if agent.unread_dm else ""
            label = f"{dot} {agent.agent_id}{dm_badge}"
            items.append(
                ListItem(
                    Static(label),
                    id=f"agent-{agent.agent_id.replace('/', '-')}",
                )
            )
        yield ListView(*items, id="agent-listview")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle Enter on an agent to emit :class:`AgentSelected`."""
        item_id = event.item.id or ""
        if item_id.startswith("agent-"):
            agent_id = item_id[6:].replace("-", "/", 1)
            self.post_message(AgentSelected(agent_id))
