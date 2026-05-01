# SPDX-License-Identifier: Apache-2.0
"""Background asyncio task that polls ``McpStdioClient.recv()`` and feeds
messages into ``ChatStore``.

The pump runs at a 250 ms cadence — fast enough for interactive feel,
cheap enough to not overwhelm the server.  It is forward-compatible with
a future ``watch()`` push API: when that lands the pump can be replaced
by a push handler without changing any other TUI code.

Spec reference: ``spec/primitives/channels.md``
"""

from __future__ import annotations

import asyncio
import contextlib

from sox_protocol.tui.mcp_client import McpStdioClient
from sox_protocol.tui.state import ChatStore

_POLL_INTERVAL: float = 0.25  # seconds


class RecvPump:
    """Drains ``McpStdioClient.recv()`` and feeds results to ``ChatStore``.

    The pump is cancellation-safe: :meth:`stop` cancels the background
    task and awaits it, so callers can ``await pump.stop()`` without
    worrying about dangling tasks.

    Usage::

        pump = RecvPump(client=client, store=store)
        await pump.start()
        # … TUI runs …
        await pump.stop()
    """

    def __init__(
        self,
        client: McpStdioClient,
        store: ChatStore,
        poll_interval: float = _POLL_INTERVAL,
    ) -> None:
        """Initialise the pump.

        Args:
            client: Connected :class:`~sox_protocol.tui.mcp_client.McpStdioClient`.
            store: :class:`~sox_protocol.tui.state.ChatStore` to feed messages into.
            poll_interval: Seconds between ``recv()`` polls (default 0.25).
        """
        self._client = client
        self._store = store
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background poll loop.

        Raises:
            RuntimeError: If already running.
        """
        if self._task is not None and not self._task.done():
            raise RuntimeError("RecvPump is already running")
        self._task = asyncio.create_task(self._loop(), name="sox-recv-pump")

    async def stop(self) -> None:
        """Cancel the poll loop and await its completion."""
        if self._task is None:
            return
        if not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    def is_running(self) -> bool:
        """Return ``True`` if the pump task is active.

        Returns:
            ``True`` while the background task is alive.
        """
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Poll ``recv()`` in a tight async loop, feeding the store."""
        try:
            while True:
                try:
                    result = await self._client.recv()
                    messages = result.get("messages", [])
                    for msg in messages:
                        self._store.ingest_message(msg)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    # Transient errors (e.g. timeout spike) — keep running
                    pass
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            pass
