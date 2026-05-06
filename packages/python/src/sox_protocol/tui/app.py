# SPDX-License-Identifier: Apache-2.0
"""SOX chat TUI application.

Composes the four panes, owns the :class:`~sox_protocol.tui.mcp_client.McpStdioClient`
and background :class:`~sox_protocol.tui.pump.RecvPump`, and wires the reactive
:class:`~sox_protocol.tui.state.ChatStore` into each widget.

Layout::

    ┌─ channel_list ─┬─── message_feed ────┬─ agent_roster ─┐
    │                │                     │                 │
    │  #general      │  ○ 09:01 agent-a:   │  ● agent-a      │
    │  dm/a+b  [2]   │    hey, review …[+] │  ◐ agent-b [1]  │
    │                │                     │                 │
    ├────────────────┴─────────────────────┴─────────────────┤
    │  Type a message or /command…                           │
    └─────────────────────────────────────────────────────────┘

Spec reference: ``spec/primitives/channels.md``,
``docs/decisions/tui-connection-model.md``
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding

from sox_protocol.tui.commands import (
    DmCommand,
    JoinCommand,
    QuitCommand,
    ReplyCommand,
    SendCommand,
)
from sox_protocol.tui.mcp_client import McpStdioClient
from sox_protocol.tui.process_manager import ServerProcess
from sox_protocol.tui.pump import RecvPump
from sox_protocol.tui.state import ChatStore
from sox_protocol.tui.widgets.agent_roster import AgentRosterWidget, AgentSelected
from sox_protocol.tui.widgets.channel_list import ChannelFocused, ChannelListWidget
from sox_protocol.tui.widgets.compose_bar import ComposeBarWidget, ComposeSubmitted
from sox_protocol.tui.widgets.message_feed import MessageFeedWidget

# How often the TUI re-polls list_agents / list_channels.  Tuned to be
# faster than the default heartbeat TTL (30s) so an agent that beats
# every 15s is reflected within ~5s of its first beat.  Net cost:
# two MCP tool calls every 5s — cheap.
_ROSTER_REFRESH_INTERVAL: float = 5.0


class SoxChatApp(App[None]):  # pragma: no cover
    """Textual TUI for the SOX Protocol chat.

    The ``SoxChatApp`` owns:

    * A :class:`~sox_protocol.tui.mcp_client.McpStdioClient` (connected to
      a local or remote SOX MCP server).
    * A background :class:`~sox_protocol.tui.pump.RecvPump` that polls
      ``recv()`` at 250 ms cadence.
    * A :class:`~sox_protocol.tui.state.ChatStore` shared reactively with
      all four pane widgets.

    Textual lifecycle hooks are excluded from the coverage gate — see
    ``conftest.py`` for the documented rationale.
    """

    TITLE = "SOX Chat"
    SUB_TITLE = "SOX Protocol inter-agent messaging"

    BINDINGS = [
        Binding("tab", "cycle_focus", "Next pane"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-row {
        layout: horizontal;
        height: 1fr;
    }
    MessageFeedWidget {
        width: 1fr;
    }
    """

    def __init__(
        self,
        client: McpStdioClient | None = None,
        agent_id: str = "tui-user",
        initial_channel: str = "#general",
        spawn_server: bool = True,
        server_env: dict[str, str] | None = None,
        **kwargs: Any,  # noqa: ANN401  -- Textual base class accepts opaque kwargs
    ) -> None:
        """Initialise the app.

        Args:
            client: Optional pre-built :class:`~sox_protocol.tui.mcp_client.McpStdioClient`.
                When ``None`` and ``spawn_server=True``, a new
                :class:`~sox_protocol.tui.process_manager.ServerProcess`
                and client are constructed automatically.
            agent_id: Agent identifier for this TUI session.
            initial_channel: Channel to focus on startup.
            spawn_server: When ``True`` (default), spawn a local SOX MCP
                server subprocess.  Set ``False`` to attach to an existing
                server via *client*.
            server_env: Extra environment variables forwarded to the spawned
                server process.
            **kwargs: Forwarded to :class:`textual.app.App`.
        """
        super().__init__(**kwargs)
        self._agent_id = agent_id
        self._initial_channel = initial_channel
        self._spawn_server = spawn_server
        self._server_env = server_env or {}
        self._store = ChatStore()
        self._pump: RecvPump | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        # Background task that re-polls channels__list_agents +
        # channels__list_channels at a fixed cadence so agents that
        # heartbeat AFTER the TUI started become visible without
        # requiring a TUI restart.  Pre-0.2.1 the TUI called list_agents
        # exactly once at on_mount(), so any later-joining agent was
        # invisible — the user-visible "agents pane is empty" symptom.
        self._roster_refresh_task: asyncio.Task[None] | None = None

        if client is not None:
            self._client = client
        elif spawn_server:
            proc = ServerProcess(
                env={
                    "SOX_AGENT_ID": agent_id,
                    "SOX_BACKING_STORE": "memory://",
                    **self._server_env,
                }
            )
            self._client = McpStdioClient(process=proc, agent_id=agent_id)
        else:
            raise ValueError(
                "Either pass a client= or set spawn_server=True"
            )

    def compose(self) -> ComposeResult:
        """Build the four-pane layout."""
        from textual.containers import Horizontal

        with Horizontal(id="main-row"):
            yield ChannelListWidget(store=self._store, id="channel-list-pane")
            yield MessageFeedWidget(store=self._store, id="message-feed-pane")
            yield AgentRosterWidget(store=self._store, id="agent-roster-pane")
        yield ComposeBarWidget(
            self_agent=self._agent_id, id="compose-bar-pane"
        )

    async def on_mount(self) -> None:
        """Start the MCP client, pump, and initial subscriptions."""
        await self._client.start()

        # Initial subscriptions and focus.  We also subscribe to
        # ``sox/presence`` so that heartbeat-driven presence events from
        # other agents land in our recv stream — this is the live signal
        # the AgentRoster pane reacts to alongside the periodic poll
        # below.  Spec: spec/primitives/presence.md §5.
        await self._client.subscribe(self._initial_channel)
        with contextlib.suppress(Exception):
            await self._client.subscribe("sox/presence")
        self._store.focus_channel(self._initial_channel)

        # Initial roster snapshot.
        await self._refresh_roster_once()

        # Start background pump
        self._pump = RecvPump(client=self._client, store=self._store)
        await self._pump.start()

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="sox-tui-heartbeat"
        )
        # Start roster refresh — agents that heartbeat after we mount
        # will appear within ``_ROSTER_REFRESH_INTERVAL`` seconds.
        self._roster_refresh_task = asyncio.create_task(
            self._roster_refresh_loop(), name="sox-tui-roster-refresh"
        )

    async def on_unmount(self) -> None:
        """Graceful shutdown: stop pump, stop client."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        if self._roster_refresh_task and not self._roster_refresh_task.done():
            self._roster_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._roster_refresh_task

        if self._pump:
            await self._pump.stop()

        await self._client.stop()

    async def _heartbeat_loop(self) -> None:
        """Send a heartbeat every 15 seconds."""
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                with contextlib.suppress(Exception):
                    await self._client.heartbeat("online")
                await asyncio.sleep(15)

    async def _refresh_roster_once(self) -> None:
        """Pull ``list_agents`` + ``list_channels`` and update the store.

        Called once at mount and then on a fixed cadence by
        :meth:`_roster_refresh_loop`.  Suppresses transient MCP errors
        (e.g. connection blips) so a single failure does not poison
        the periodic refresh.
        """
        with contextlib.suppress(Exception):
            channels_resp = await self._client.list_channels()
            self._store.update_channels(channels_resp.get("channels", []))
        with contextlib.suppress(Exception):
            agents_resp = await self._client.list_agents()
            self._store.update_agents(agents_resp.get("agents", []))

    async def _roster_refresh_loop(self) -> None:
        """Periodically poll list_agents / list_channels.

        Cadence is :data:`_ROSTER_REFRESH_INTERVAL` seconds.  Without
        this poll, agents that heartbeat after the TUI starts are
        invisible until the TUI is restarted — the dominant cause of
        the "agents pane is empty" report up through 0.2.0.
        """
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                await asyncio.sleep(_ROSTER_REFRESH_INTERVAL)
                await self._refresh_roster_once()

    # ------------------------------------------------------------------
    # Message handlers (from widgets)
    # ------------------------------------------------------------------

    def on_channel_focused(self, event: ChannelFocused) -> None:
        """Handle channel selection from the channel list."""
        self._store.focus_channel(event.channel)

    def on_agent_selected(self, event: AgentSelected) -> None:
        """Handle agent selection — open DM compose mode."""
        from sox_protocol.tui.commands import dm_channel

        channel = dm_channel(self._agent_id, event.agent_id)
        self._store.focus_channel(channel)

    def on_compose_submitted(self, event: ComposeSubmitted) -> None:
        """Handle compose bar submission — dispatch command to server."""
        asyncio.create_task(
            self._dispatch_command(event.command),
            name="sox-dispatch",
        )

    async def _dispatch_command(
        self, command: object
    ) -> None:
        """Dispatch a parsed command to the MCP server.

        Args:
            command: A :class:`~sox_protocol.tui.commands.Command` instance.
        """
        try:
            if isinstance(command, SendCommand):
                channel = self._store.focused_channel or "#general"
                await self._client.send(
                    channel=channel,
                    body={"text": command.text},
                )

            elif isinstance(command, ReplyCommand):
                channel = self._store.focused_channel or "#general"
                await self._client.send(
                    channel=channel,
                    body={"text": command.text},
                    reply_to=command.reply_to,
                )

            elif isinstance(command, (DmCommand, JoinCommand)):
                await self._client.subscribe(command.channel)
                self._store.focus_channel(command.channel)

            elif isinstance(command, QuitCommand):
                await self.action_quit()

        except Exception:  # noqa: BLE001
            pass

    def action_cycle_focus(self) -> None:
        """Tab through the four panes."""
        pane_ids = [
            "channel-list-pane",
            "message-feed-pane",
            "agent-roster-pane",
            "compose-bar-pane",
        ]
        focused = self.focused
        if focused is None:
            self.set_focus(self.query_one("#channel-list-pane"))
            return
        current_id = focused.id
        if current_id is None:
            idx = -1
        else:
            try:
                idx = pane_ids.index(current_id)
            except ValueError:
                idx = -1
        next_id = pane_ids[(idx + 1) % len(pane_ids)]
        self.set_focus(self.query_one(f"#{next_id}"))


def run(
    agent_id: str = "tui-user",
    initial_channel: str = "#general",
    spawn_server: bool = True,
    server_env: dict[str, str] | None = None,
) -> None:
    """Launch the SOX chat TUI.

    Convenience entry point used by ``sox chat`` CLI subcommand.

    Args:
        agent_id: Agent identifier for this session.
        initial_channel: Channel to focus on startup (default ``#general``).
        spawn_server: Spawn a local MCP server subprocess (default ``True``).
        server_env: Extra env vars forwarded to the spawned server.
    """
    app = SoxChatApp(
        agent_id=agent_id,
        initial_channel=initial_channel,
        spawn_server=spawn_server,
        server_env=server_env,
    )
    app.run()
