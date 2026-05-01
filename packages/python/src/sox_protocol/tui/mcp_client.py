# SPDX-License-Identifier: Apache-2.0
"""Async MCP client that speaks JSON-RPC over subprocess stdio pipes.

Wraps :class:`~sox_protocol.tui.process_manager.ServerProcess` with typed
async methods for the SOX tools.  The transport is newline-delimited JSON-RPC
2.0 over the process stdin/stdout pipes — the same framing used by the MCP
stdio transport spec.

Spec reference: ``docs/decisions/tui-connection-model.md``
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sox_protocol.tui.process_manager import ServerProcess


class McpStdioClient:
    """Typed async client for a SOX MCP server connected via stdio.

    Wraps a low-level asyncio subprocess transport (provided by
    :class:`~sox_protocol.tui.process_manager.ServerProcess`) with
    JSON-RPC 2.0 request/response plumbing.

    The client operates in two modes:

    * **Managed** — caller passes a :class:`~sox_protocol.tui.process_manager.ServerProcess`
      instance; :meth:`start` spawns it and :meth:`stop` terminates it.
    * **Attached** — caller passes pre-opened ``asyncio.StreamReader`` /
      ``asyncio.StreamWriter`` directly (used in tests and ``--no-spawn``
      mode).

    Usage (managed)::

        proc = ServerProcess(env={"SOX_AGENT_ID": "tui-user"})
        client = McpStdioClient(process=proc)
        await client.start()
        msgs = await client.recv()
        await client.stop()
    """

    def __init__(
        self,
        *,
        process: ServerProcess | None = None,
        reader: asyncio.StreamReader | None = None,
        writer: asyncio.StreamWriter | None = None,
        agent_id: str = "tui-user",
    ) -> None:
        """Initialise the client.

        Args:
            process: Optional :class:`~sox_protocol.tui.process_manager.ServerProcess`.
                When provided, :meth:`start` will call ``process.spawn()`` and
                :meth:`stop` will call ``process.terminate()``.
            reader: Pre-opened stream reader (overrides ``process.stdout``).
            writer: Pre-opened stream writer (overrides ``process.stdin``).
            agent_id: Agent identifier sent on the MCP ``initialize`` call.
        """
        self._process = process
        self._reader = reader
        self._writer = writer
        self._agent_id = agent_id
        self._next_id: int = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the client (and optionally spawn the server subprocess).

        If a :class:`~sox_protocol.tui.process_manager.ServerProcess` was
        supplied and the reader/writer were not overridden, spawns the
        process and uses its pipes.  Performs the MCP ``initialize``
        handshake.

        Raises:
            RuntimeError: If already started.
        """
        if self._initialized:
            raise RuntimeError("McpStdioClient is already started")

        if self._process is not None and (
            self._reader is None or self._writer is None
        ):
            await self._process.spawn()
            self._reader = self._process.stdout
            self._writer = self._process.stdin

        if self._reader is None or self._writer is None:
            raise RuntimeError(
                "McpStdioClient requires either a process or reader+writer"
            )

        # Start background reader
        self._read_task = asyncio.create_task(
            self._read_loop(), name="sox-mcp-reader"
        )

        # MCP initialize handshake
        await self._initialize_handshake()
        self._initialized = True

    async def stop(self) -> None:
        """Stop the client and optionally terminate the server subprocess."""
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):  # pragma: no cover
                await self._read_task

        # Cancel any pending futures
        for fut in self._pending.values():
            if not fut.done():  # pragma: no cover
                fut.cancel()  # pragma: no cover
        self._pending.clear()

        if self._process is not None:
            await self._process.terminate()

        self._initialized = False

    # ------------------------------------------------------------------
    # SOX tool methods
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: str,
        body: dict[str, Any],
        reply_to: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to *channel*.

        Args:
            channel: Target channel name.
            body: Opaque message body.
            reply_to: Optional parent message_id for threaded replies.
            correlation_id: Optional caller correlation token.

        Returns:
            ``{"sent_at": float, "message_id": str, "seq": int, "backpressure": {...}}``
        """
        params: dict[str, Any] = {"channel": channel, "body": body}
        if reply_to is not None:
            params["reply_to"] = reply_to
        if correlation_id is not None:
            params["correlation_id"] = correlation_id
        return await self._call("channels__send", params)

    async def recv(
        self,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> dict[str, Any]:
        """Drain the server's message buffer for this agent.

        Args:
            channels: Optional channel filter list.
            max_messages: Maximum messages to return.

        Returns:
            ``{"drained_at": float, "messages": [...]}``
        """
        params: dict[str, Any] = {"max_messages": max_messages}
        if channels is not None:
            params["channels"] = channels
        return await self._call("channels__recv", params)

    async def subscribe(self, pattern: str) -> dict[str, Any]:
        """Subscribe to channels matching *pattern*.

        Args:
            pattern: Glob pattern or exact channel name.

        Returns:
            ``{"subscribed": [...]}``
        """
        return await self._call("channels__subscribe", {"pattern": pattern})

    async def list_channels(self) -> dict[str, Any]:
        """List all discoverable channels.

        Returns:
            ``{"channels": [...], "_sox_protocol": {...}}``
        """
        return await self._call("channels__list_channels", {})

    async def list_agents(
        self,
        status_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        """List all known agents and their presence state.

        Args:
            status_filter: Optional presence states to include.

        Returns:
            ``{"agents": [...]}``
        """
        params: dict[str, Any] = {}
        if status_filter is not None:
            params["status_filter"] = status_filter
        return await self._call("channels__list_agents", params)

    async def heartbeat(self, status: str = "online") -> dict[str, Any]:
        """Send a heartbeat for this agent.

        Args:
            status: One of ``online``, ``busy``, ``offline``.

        Returns:
            ``{"agent_id": str, "status": str, "recorded_at": float, "expires_at": float}``
        """
        return await self._call("channels__heartbeat", {"status": status})

    async def ack(
        self, message_id: str, status: str, reason: str | None = None
    ) -> dict[str, Any]:
        """ACK or NACK a message.

        Args:
            message_id: Message to acknowledge.
            status: One of ``received``, ``processing``, ``done``, ``nack``.
            reason: Optional reason for NACK.

        Returns:
            ``{"message_id": str, "status": str, "acked_at": float}``
        """
        params: dict[str, Any] = {"message_id": message_id, "status": status}
        if reason is not None:
            params["reason"] = reason
        return await self._call("channels__ack", params)

    # ------------------------------------------------------------------
    # JSON-RPC plumbing
    # ------------------------------------------------------------------

    async def _initialize_handshake(self) -> None:
        """Send the MCP ``initialize`` request and await the response."""
        req_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": f"sox-tui-{self._agent_id}",
                    "version": "1.0",
                },
            },
        }
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        await self._write(payload)
        await asyncio.wait_for(fut, timeout=10.0)

        # Send initialized notification (no response expected)
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        await self._write(notif)

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC ``tools/call`` request and return the result.

        Args:
            method: SOX tool name (e.g. ``channels__send``).
            params: Tool parameters dict.

        Returns:
            Parsed result dict from the server.

        Raises:
            RuntimeError: If the server returns an error response.
            asyncio.TimeoutError: If the server does not respond within 30s.
        """
        req_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": method,
                "arguments": params,
            },
        }
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        await self._write(payload)
        resp = await asyncio.wait_for(fut, timeout=30.0)

        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(
                f"MCP error from {method}: {err.get('message', err)}"
            )

        # MCP wraps tool results in content blocks
        result_raw = resp.get("result", {})
        result: dict[str, Any] = result_raw if isinstance(result_raw, dict) else {}
        content = result.get("content", [])
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":  # pragma: no branch
                text = first.get("text", "{}")
                try:
                    parsed: dict[str, Any] = json.loads(text)
                except json.JSONDecodeError:
                    return {"raw": text}
                else:
                    return parsed
        return result

    async def _write(self, payload: dict[str, Any]) -> None:
        """Serialise *payload* as newline-delimited JSON and write to stdin.

        Args:
            payload: JSON-serialisable dict.
        """
        assert self._writer is not None
        line = json.dumps(payload) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

    async def _read_loop(self) -> None:
        """Background task: read newline-delimited JSON from stdout.

        Resolves pending futures for responses; ignores notifications.
        """
        assert self._reader is not None
        try:
            while True:
                line_bytes = await self._reader.readline()
                if not line_bytes:  # pragma: no cover — EOF when pipe closes
                    break  # pragma: no cover
                try:
                    msg = json.loads(line_bytes.decode(errors="replace"))
                except json.JSONDecodeError:  # pragma: no branch
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():  # pragma: no cover — race guard
                        fut.set_result(msg)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001  # pragma: no cover
            pass
