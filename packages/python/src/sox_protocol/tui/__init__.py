# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol chat TUI package.

Public surface:

* :class:`~sox_protocol.tui.app.SoxChatApp` — Textual ``App`` subclass
  composing the four panes and owning the MCP client + pump lifecycle.
* :func:`~sox_protocol.tui.app.run` — convenience entry point used by
  the ``sox chat`` CLI subcommand.
"""

from sox_protocol.tui.app import SoxChatApp, run

__all__ = ["SoxChatApp", "run"]
