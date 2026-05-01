# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures and coverage configuration for TUI tests.

Coverage exclusions
-------------------
The following modules are excluded from the 100% coverage gate because
they contain Textual rendering glue (lifecycle hooks, widget composition,
and event dispatch wired to the Textual event loop) that is impractical
to reach via unit tests without a full Textual pilot environment:

* ``sox_protocol.tui.app`` — Textual ``App`` subclass; lifecycle hooks
  (``on_mount``, ``on_unmount``) and action methods require a running
  Textual reactor.  Covered at smoke-test level in
  ``test_app_pilot.py``.
* ``sox_protocol.tui.widgets.*`` — All four pane widgets; ``compose()``,
  ``on_mount()``, and ``on_*`` event handlers are Textual rendering glue.
  Logic tested indirectly via ``ChatStore`` mutations in ``test_state.py``.

The modules with 100% required coverage are:

* ``sox_protocol.tui.state``
* ``sox_protocol.tui.commands``
* ``sox_protocol.tui.pump``
* ``sox_protocol.tui.process_manager``
* ``sox_protocol.tui.mcp_client``

These are pure logic or async I/O modules with no Textual dependency and
are fully unit-tested in the corresponding test files.
"""
