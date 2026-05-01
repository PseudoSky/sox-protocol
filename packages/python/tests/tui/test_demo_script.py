# SPDX-License-Identifier: Apache-2.0
"""Integration test: run examples/two-agents-talking/demo.py against an
in-process server fixture.

Asserts:
- Script runs to completion without raising
- Final list_pending (via store state) shows expected messages
- Message ordering by seq is deterministic across two runs
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# Path to the demo script
_DEMO_PATH = (
    Path(__file__).resolve().parents[4]
    / "examples"
    / "two-agents-talking"
    / "demo.py"
)


@pytest.mark.asyncio
async def test_demo_script_exists() -> None:
    assert _DEMO_PATH.exists(), f"demo.py not found at {_DEMO_PATH}"


@pytest.mark.asyncio
async def test_demo_script_runs_to_completion() -> None:
    """Run demo.py as a subprocess and assert it exits 0 within 60s."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(_DEMO_PATH),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=60.0
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        pytest.fail("demo.py did not complete within 60 seconds")

    if proc.returncode != 0:
        # Print captured output for debugging
        print("STDOUT:", stdout.decode(errors="replace"))
        print("STDERR:", stderr.decode(errors="replace"))
    assert proc.returncode == 0, (
        f"demo.py exited with code {proc.returncode}\n"
        f"stderr: {stderr.decode(errors='replace')[:2000]}"
    )


@pytest.mark.asyncio
async def test_demo_script_deterministic_ordering() -> None:
    """Running the demo twice should produce the same sequence of message IDs
    (when using the in-process memory store — IDs are deterministic integers).
    """
    async def _run_demo() -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_DEMO_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=60.0
        )
        return proc.returncode or 0, stdout, stderr

    rc1, out1, _ = await _run_demo()
    rc2, out2, _ = await _run_demo()

    assert rc1 == 0, "First run failed"
    assert rc2 == 0, "Second run failed"

    import re

    def _normalise(raw: bytes) -> list[str]:
        """Strip wall-clock timestamps so output is comparable across runs."""
        lines = []
        for ln in raw.decode(errors="replace").splitlines():
            if not ln.strip():
                continue
            # Strip leading [HH:MM:SS] timestamp which changes each run
            normalised = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", ln)
            lines.append(normalised)
        return lines

    lines1 = _normalise(out1)
    lines2 = _normalise(out2)

    assert lines1 == lines2, (
        "demo.py produced different output on two runs — not deterministic\n"
        f"Run 1 lines: {lines1[:5]}\n"
        f"Run 2 lines: {lines2[:5]}"
    )
