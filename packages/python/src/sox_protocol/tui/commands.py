# SPDX-License-Identifier: Apache-2.0
"""Pure parser for compose-bar slash commands.

No I/O.  ``parse(text)`` returns a typed ``Command`` union or raises
``CommandParseError`` on unrecognised input.

DM channels follow the ``dm/<sorted-pair>`` convention from
``spec/primitives/dms.md``: the channel name is always
``dm/<lower>+<higher>`` where ``<lower>`` and ``<higher>`` are the two
agent IDs in lexicographic order.

Spec reference: ``spec/primitives/channels.md``, ``spec/primitives/dms.md``
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Command types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SendCommand:
    """Send a plain-text message to the focused channel.

    Attributes:
        text: Message body text.
    """

    text: str


@dataclass(frozen=True)
class ReplyCommand:
    """Send a threaded reply to an existing message.

    Attributes:
        reply_to: ``message_id`` of the parent message.
        text: Reply body text.
    """

    reply_to: str
    text: str


@dataclass(frozen=True)
class DmCommand:
    """Open (or switch to) a DM channel with another agent.

    The ``channel`` attribute is the resolved ``dm/<sorted-pair>`` name.

    Attributes:
        target_agent: The agent the user typed.
        channel: Resolved ``dm/<a>+<b>`` channel name (sorted pair).
        self_agent: The local agent ID used to compute the sorted pair.
    """

    target_agent: str
    channel: str
    self_agent: str


@dataclass(frozen=True)
class JoinCommand:
    """Subscribe to and focus a channel.

    Attributes:
        channel: Channel name to join.
    """

    channel: str


@dataclass(frozen=True)
class QuitCommand:
    """Exit the TUI."""


# Union type for all commands
Command = SendCommand | ReplyCommand | DmCommand | JoinCommand | QuitCommand


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CommandParseError(ValueError):
    """Raised when a slash command cannot be parsed.

    Attributes:
        raw: The original input string.
        reason: Human-readable explanation.
    """

    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(f"Cannot parse command {raw!r}: {reason}")
        self.raw = raw
        self.reason = reason


# ---------------------------------------------------------------------------
# DM channel helper
# ---------------------------------------------------------------------------


def dm_channel(agent_a: str, agent_b: str) -> str:
    """Return the canonical ``dm/<sorted-pair>`` channel name.

    Per ``spec/primitives/dms.md``: channel is always
    ``dm/<lower>+<higher>`` in lexicographic order.

    Args:
        agent_a: First agent ID.
        agent_b: Second agent ID.

    Returns:
        Canonical DM channel name.

    Example::

        >>> dm_channel("beta", "alpha")
        'dm/alpha+beta'
    """
    lo, hi = sorted([agent_a, agent_b])
    return f"dm/{lo}+{hi}"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse(text: str, self_agent: str = "tui-user") -> Command:
    """Parse *text* from the compose bar into a typed ``Command``.

    Plain text (no leading ``/``) becomes a :class:`SendCommand`.
    Slash-prefixed tokens are parsed as subcommands.

    Supported slash commands::

        /reply <message_id> <text…>
        /dm <agent_id>
        /join <channel>
        /quit

    Args:
        text: Raw compose-bar content (may be empty).
        self_agent: The local agent ID used for DM channel resolution.

    Returns:
        A :class:`Command` instance.

    Raises:
        :class:`CommandParseError`: If input is a ``/``-prefixed command
            with an unrecognised verb, missing arguments, or empty text.
    """
    stripped = text.strip()

    if not stripped.startswith("/"):
        if not stripped:
            raise CommandParseError(text, "empty message")
        return SendCommand(text=stripped)

    # Slash command — split on whitespace
    parts = stripped.split(None)  # split on any whitespace
    verb = parts[0].lower()

    if verb == "/quit":
        return QuitCommand()

    if verb == "/join":
        if len(parts) < 2:
            raise CommandParseError(text, "/join requires a channel name")
        return JoinCommand(channel=parts[1])

    if verb == "/dm":
        if len(parts) < 2:
            raise CommandParseError(text, "/dm requires an agent_id")
        target = parts[1]
        if not target:  # pragma: no cover  — unreachable via whitespace-split
            raise CommandParseError(text, "/dm agent_id cannot be empty")
        channel = dm_channel(self_agent, target)
        return DmCommand(target_agent=target, channel=channel, self_agent=self_agent)

    if verb == "/reply":
        if len(parts) < 3:
            raise CommandParseError(
                text, "/reply requires a message_id and reply text"
            )
        reply_to = parts[1]
        reply_text = " ".join(parts[2:])
        if not reply_text:  # pragma: no cover  — unreachable via whitespace-split
            raise CommandParseError(text, "/reply text cannot be empty")
        return ReplyCommand(reply_to=reply_to, text=reply_text)

    raise CommandParseError(text, f"unknown command verb {verb!r}")
