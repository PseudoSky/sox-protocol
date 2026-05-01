# SPDX-License-Identifier: Apache-2.0
"""Subprocess lifecycle manager for the SOX MCP stdio server.

Spawns ``python -m sox_protocol.cli serve --transport stdio`` (or a
caller-supplied command), captures stderr line-by-line for crash diagnosis,
and provides a graceful shutdown path.

Spec reference: ``docs/decisions/tui-connection-model.md``
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import sys
from collections.abc import Sequence


class ServerProcess:
    """Manages the lifecycle of a spawned SOX MCP stdio server subprocess.

    The process communicates over stdin/stdout (JSON-RPC MCP framing).
    Stderr is drained asynchronously into a ring buffer; the last 20 lines
    are surfaced on unexpected exit so crash causes are not silently buried.

    Usage::

        proc = ServerProcess()
        await proc.spawn()
        # … use proc.stdin / proc.stdout …
        await proc.terminate()

    Attributes:
        stdin: Asyncio ``StreamWriter`` for the server's stdin pipe.
        stdout: Asyncio ``StreamReader`` for the server's stdout pipe.
    """

    _STDERR_RING: int = 20

    def __init__(
        self,
        cmd: Sequence[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialise but do not yet spawn.

        Args:
            cmd: Command + args to run.  Defaults to
                ``[sys.executable, "-m", "sox_protocol.cli", "serve",
                "--transport", "stdio"]``.
            env: Extra environment variables merged on top of the current
                process environment.  Useful for injecting ``SOX_AGENT_ID``,
                ``SOX_BACKING_STORE``, etc.
        """
        self._cmd: Sequence[str] = cmd or [
            sys.executable,
            "-m",
            "sox_protocol.cli",
            "serve",
            "--transport",
            "stdio",
        ]
        self._extra_env = env or {}
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_ring: collections.deque[str] = collections.deque(
            maxlen=self._STDERR_RING
        )
        self._stderr_task: asyncio.Task[None] | None = None
        self.stdin: asyncio.StreamWriter | None = None
        self.stdout: asyncio.StreamReader | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def spawn(self) -> None:
        """Spawn the server subprocess and start stderr capture.

        Raises:
            RuntimeError: If the process is already running.
            OSError: If the subprocess cannot be started (e.g. bad command).
        """
        if self._proc is not None and self._proc.returncode is None:
            raise RuntimeError("ServerProcess is already running")

        import os

        env = dict(os.environ)
        env.update(self._extra_env)

        self._proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        assert self._proc.stderr is not None

        self.stdin = self._proc.stdin
        self.stdout = self._proc.stdout

        # Drain stderr asynchronously into the ring buffer.
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(self._proc.stderr),
            name="sox-server-stderr",
        )

    async def terminate(self, timeout: float = 5.0) -> None:
        """Gracefully shut down the server subprocess.

        Sends SIGTERM and waits up to *timeout* seconds.  If the process
        has not exited, sends SIGKILL.  Cancels the stderr drain task.

        Args:
            timeout: Seconds to wait for clean exit before SIGKILL.
        """
        if self._proc is None:
            return

        if self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=timeout)
            except TimeoutError:  # pragma: no cover — slow-exit path
                self._proc.kill()  # pragma: no cover
                await self._proc.wait()  # pragma: no cover

        if self._stderr_task and not self._stderr_task.done():  # pragma: no cover
            self._stderr_task.cancel()  # pragma: no cover
            with contextlib.suppress(asyncio.CancelledError):  # pragma: no cover
                await self._stderr_task  # pragma: no cover

        self._proc = None
        self.stdin = None
        self.stdout = None

    def is_alive(self) -> bool:
        """Return True if the subprocess is currently running.

        Returns:
            ``True`` when the process exists and has not exited.
        """
        return self._proc is not None and self._proc.returncode is None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def last_stderr_lines(self) -> list[str]:
        """Return the last up-to-20 stderr lines captured from the server.

        Useful for surfacing crash causes when the server exits unexpectedly.

        Returns:
            List of stderr lines (no trailing newline).
        """
        return list(self._stderr_ring)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _drain_stderr(self, reader: asyncio.StreamReader) -> None:
        """Continuously read stderr and push lines into the ring buffer.

        Args:
            reader: Asyncio stream reader connected to the subprocess stderr.
        """
        try:
            while True:
                line_bytes = await reader.readline()
                if not line_bytes:
                    break
                self._stderr_ring.append(line_bytes.decode(errors="replace").rstrip())
        except asyncio.CancelledError:  # pragma: no cover
            pass  # pragma: no cover
        except Exception:  # noqa: BLE001  # pragma: no cover
            pass  # pragma: no cover
