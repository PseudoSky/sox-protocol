# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures for reference agent tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure examples/reference-agent/ is importable in all test modules.
_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for seq.json state files."""
    d = tmp_path / "state"
    d.mkdir()
    return d
