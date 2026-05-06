# SPDX-License-Identifier: Apache-2.0
"""Compose bar widget.

Single-line input at the bottom of the TUI.  On submission, parses the
text via :func:`~sox_protocol.tui.commands.parse` and emits
:class:`ComposeSubmitted` carrying the typed :class:`~sox_protocol.tui.commands.Command`.

Slash commands: ``/reply <id> <text>``, ``/dm <agent>``,
``/join <channel>``, ``/quit``.

Spec reference: ``spec/primitives/channels.md``
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input

from sox_protocol.tui.commands import Command, CommandParseError, parse


class ComposeSubmitted(Message):
    """Emitted when the user submits the compose bar.

    Attributes:
        command: Parsed :class:`~sox_protocol.tui.commands.Command` instance.
        raw: Raw text before parsing (for diagnostics).
    """

    def __init__(self, command: Command, raw: str) -> None:
        super().__init__()
        self.command = command
        self.raw = raw


class ComposeBarWidget(Widget):  # pragma: no cover
    """Bottom-pane compose bar.

    Textual lifecycle hooks are excluded from the coverage gate — see
    ``conftest.py`` for the documented rationale.  The parsing logic is
    fully covered in ``tests/tui/test_commands.py``.
    """

    # Layout notes:
    #   - Wrapper claims 3 rows total: 1 row of content inside a 2-row border.
    #   - Textual's Input widget defaults to height: 3 (its own border), which
    #     would overflow the wrapper by 2 rows.  We pin the Input to height: 1
    #     and disable its border so the visible chrome is the wrapper's
    #     border alone.  Pre-0.2.4 the Input borrowed its default sizing and
    #     spilled out the bottom of the compose pane.
    DEFAULT_CSS = """
    ComposeBarWidget {
        height: 3;
        border: solid $accent;
        padding: 0 1;
    }
    ComposeBarWidget > Input {
        height: 1;
        border: none;
        padding: 0;
    }
    """

    def __init__(self, self_agent: str = "tui-user", **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self._self_agent = self_agent

    def compose(self) -> ComposeResult:
        """Render the input field."""
        yield Input(placeholder="Type a message or /command…", id="compose-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Parse and emit :class:`ComposeSubmitted` on Enter.

        On :class:`~sox_protocol.tui.commands.CommandParseError`, surfaces
        the error in the placeholder and does NOT clear the input.

        Args:
            event: Textual ``Input.Submitted`` event.
        """
        raw = event.value.strip()
        if not raw:
            return
        try:
            cmd = parse(raw, self_agent=self._self_agent)
            self.post_message(ComposeSubmitted(command=cmd, raw=raw))
            event.input.value = ""
        except CommandParseError as exc:
            event.input.placeholder = f"Error: {exc.reason}"
