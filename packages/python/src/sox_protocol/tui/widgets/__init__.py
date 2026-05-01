# SPDX-License-Identifier: Apache-2.0
"""SOX TUI widget package.

Re-exports all four pane widgets for convenient import from ``app.py``.
"""

from sox_protocol.tui.widgets.agent_roster import AgentRosterWidget, AgentSelected
from sox_protocol.tui.widgets.channel_list import ChannelFocused, ChannelListWidget
from sox_protocol.tui.widgets.compose_bar import ComposeBarWidget, ComposeSubmitted
from sox_protocol.tui.widgets.message_feed import MessageFeedWidget, ThreadExpanded

__all__ = [
    "ChannelListWidget",
    "ChannelFocused",
    "MessageFeedWidget",
    "ThreadExpanded",
    "AgentRosterWidget",
    "AgentSelected",
    "ComposeBarWidget",
    "ComposeSubmitted",
]
