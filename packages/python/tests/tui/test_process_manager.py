# SPDX-License-Identifier: Apache-2.0
"""Tests for ``sox_protocol.tui.process_manager``.

Uses a stub ``python -c`` script as the fake server so no real SOX server
is required.  Tests cover: spawn, is_alive, terminate, crash-stderr capture.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from sox_protocol.tui.process_manager import ServerProcess

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _echo_server_cmd(script: str) -> list[str]:
    """Return a command that runs *script* via the current Python interpreter."""
    return [sys.executable, "-c", script]


# ---------------------------------------------------------------------------
# spawn / is_alive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_makes_process_alive() -> None:
    # A server that stays alive waiting on stdin
    cmd = _echo_server_cmd("import sys; sys.stdin.read()")
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    try:
        assert proc.is_alive()
    finally:
        await proc.terminate()


@pytest.mark.asyncio
async def test_is_alive_false_before_spawn() -> None:
    proc = ServerProcess()
    assert not proc.is_alive()


@pytest.mark.asyncio
async def test_spawn_twice_raises() -> None:
    cmd = _echo_server_cmd("import sys; sys.stdin.read()")
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            await proc.spawn()
    finally:
        await proc.terminate()


@pytest.mark.asyncio
async def test_terminate_stops_process() -> None:
    cmd = _echo_server_cmd("import sys; sys.stdin.read()")
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    assert proc.is_alive()
    await proc.terminate()
    assert not proc.is_alive()


@pytest.mark.asyncio
async def test_terminate_noop_when_not_running() -> None:
    proc = ServerProcess()
    # Should not raise
    await proc.terminate()


# ---------------------------------------------------------------------------
# stdin / stdout pipes available after spawn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_exposes_stdin_stdout() -> None:
    cmd = _echo_server_cmd("import sys; sys.stdin.read()")
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
    finally:
        await proc.terminate()


# ---------------------------------------------------------------------------
# stderr capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stderr_captured_into_ring_buffer(tmp_path: object) -> None:
    # Script writes known lines to stderr then exits
    script = (
        "import sys, time\n"
        "for i in range(3):\n"
        "    print(f'line{i}', file=sys.stderr, flush=True)\n"
        "sys.stdin.read()\n"
    )
    cmd = _echo_server_cmd(script)
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    # Give the stderr drain task time to capture
    await asyncio.sleep(0.3)
    await proc.terminate()
    lines = proc.last_stderr_lines()
    assert any("line0" in ln for ln in lines)


@pytest.mark.asyncio
async def test_stderr_ring_buffer_bounded() -> None:
    # Write 25 lines — ring should keep only last 20
    script = (
        "import sys\n"
        "for i in range(25):\n"
        "    print(f'L{i}', file=sys.stderr, flush=True)\n"
        "sys.stdin.read()\n"
    )
    cmd = _echo_server_cmd(script)
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    await asyncio.sleep(0.3)
    await proc.terminate()
    lines = proc.last_stderr_lines()
    assert len(lines) <= 20


# ---------------------------------------------------------------------------
# last_stderr_lines before spawn
# ---------------------------------------------------------------------------


def test_last_stderr_lines_empty_before_spawn() -> None:
    proc = ServerProcess()
    assert proc.last_stderr_lines() == []


# ---------------------------------------------------------------------------
# stderr drain task cancel path (covers process_manager.py lines 132, 180-181)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_cancels_active_stderr_drain() -> None:
    """Terminate a running process whose stderr drain is still active.

    This exercises the _stderr_task.cancel() path (line 132) and the
    asyncio.CancelledError handler in _drain_stderr (lines 180-181).
    """
    # A script that writes stderr continuously and waits on stdin
    script = (
        "import sys, time\n"
        "while True:\n"
        "    print('alive', file=sys.stderr, flush=True)\n"
        "    time.sleep(0.05)\n"
    )
    cmd = _echo_server_cmd(script)
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    # Let stderr drain task start and buffer some lines
    await asyncio.sleep(0.2)
    # Task should still be running (process hasn't exited)
    assert proc._stderr_task is not None
    assert not proc._stderr_task.done()
    # Terminate — should cancel the stderr drain task
    await proc.terminate()
    assert not proc.is_alive()


# ---------------------------------------------------------------------------
# is_alive after process exits naturally
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_alive_false_after_natural_exit() -> None:
    # Script exits immediately
    cmd = _echo_server_cmd("pass")
    proc = ServerProcess(cmd=cmd)
    await proc.spawn()
    # Wait for natural exit
    await asyncio.sleep(0.5)
    assert not proc.is_alive()
    await proc.terminate()  # should be a no-op


# ---------------------------------------------------------------------------
# env injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_injected_into_subprocess() -> None:
    # Script prints env var to stdout then exits
    script = "import os, sys; print(os.environ.get('TEST_VAR', 'missing'), flush=True)"
    cmd = _echo_server_cmd(script)
    proc = ServerProcess(cmd=cmd, env={"TEST_VAR": "hello123"})
    await proc.spawn()
    assert proc.stdout is not None
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
    assert b"hello123" in line
    await proc.terminate()
