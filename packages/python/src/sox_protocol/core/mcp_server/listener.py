"""Background asyncio listener for the SOX MCP server.

Architecture — push at the network layer, pull at the LLM layer
(``DESIGN.md §5.1``):

- ``Listener`` starts an ``asyncio.Task`` via ``start()`` that drives the
  ``BackingStore.watch()`` generator for the agent's mailbox.
- Every message yielded by ``watch()`` is immediately placed into an
  ``asyncio.Queue`` (the *local buffer*).
- The ``channels__recv`` tool drains the queue non-blockingly using
  ``Queue.get_nowait()`` — it never awaits the listener task.
- The queue is **unbounded by default**.  Under sustained high-volume
  workloads this can grow without limit; operators who need backpressure
  should cap it by passing ``maxsize`` to ``Listener()``.  The
  ``DESIGN.md §5.1`` design note explicitly documents this trade-off:
  unbounded buffering is required to guarantee no message loss when no
  ``recv`` call is pending.

This module MUST NOT import from ``sox_protocol.adapters`` (import-linter
enforced).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sox_protocol.core.ports.backing_store import BackingStore

_log = logging.getLogger(__name__)


class Listener:
    """Drives a ``BackingStore.watch()`` loop in a background ``asyncio.Task``.

    The listener buffers every incoming message in ``self.queue`` so that
    ``channels__recv`` can drain the buffer synchronously (non-blocking) at any
    point, even when hundreds of messages have accumulated while the agent was
    busy.

    Memory note:
        ``queue`` is unbounded (``maxsize=0``) unless *maxsize* is specified.
        This guarantees no message loss but can consume unbounded memory if
        ``channels__recv`` is never called and messages keep arriving.  For
        production deployments with high-volume channels, pass a *maxsize* and
        add monitoring on ``queue.qsize()``.

    Args:
        store: A fully initialised ``BackingStore`` instance.
        agent_id: The agent whose subscriptions this listener watches.
        maxsize: ``asyncio.Queue`` capacity (``0`` = unbounded).
    """

    def __init__(
        self,
        store: BackingStore,
        agent_id: str,
        maxsize: int = 0,
    ) -> None:
        self._store = store
        self._agent_id = agent_id
        self.queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> asyncio.Task[None]:
        """Create the background asyncio task and return it.

        Should be called once, typically inside the FastMCP lifespan
        context manager so the task is cancelled cleanly when the server
        shuts down.

        Returns:
            The created ``asyncio.Task``; the caller is responsible for
            cancelling it on shutdown.
        """
        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.create_task(
            self._run(),
            name=f"sox-listener:{self._agent_id}",
        )
        return self._task

    async def stop(self) -> None:
        """Cancel the background task and wait for it to finish cleanly."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Main loop: drive watch() and put every message on the queue.

        Handles ``asyncio.CancelledError`` by re-raising after cleanup so
        the task exits cleanly.  Any other exception from the store is
        logged and causes the loop to retry after a brief backoff, so a
        transient store error does not silence the listener permanently.
        """
        _log.info("sox listener starting for agent=%s", self._agent_id)
        while True:
            try:
                async for message in self._store.watch(self._agent_id):
                    await self.queue.put(message)
                    _log.debug(
                        "sox listener buffered message_id=%s for agent=%s",
                        message.get("message_id"),
                        self._agent_id,
                    )
            except asyncio.CancelledError:
                _log.info("sox listener cancelled for agent=%s", self._agent_id)
                raise
            except Exception:
                _log.exception(
                    "sox listener error for agent=%s; retrying in 1 s",
                    self._agent_id,
                )
                await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Drain helper used by tools.py
    # ------------------------------------------------------------------

    def drain(self, max_messages: int = 50) -> list[dict[str, object]]:
        """Drain up to *max_messages* from the local buffer non-blockingly.

        This is a synchronous (non-async) helper intentionally.  ``recv``
        must be non-blocking (timeout=0 semantics); calling
        ``Queue.get_nowait()`` guarantees that.

        Args:
            max_messages: Upper bound on items to pop.

        Returns:
            A list of message dicts (possibly empty).
        """
        messages: list[dict[str, object]] = []
        while len(messages) < max_messages:
            try:
                messages.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages
