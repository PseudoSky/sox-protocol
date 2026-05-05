# SPDX-License-Identifier: Apache-2.0
"""Tests to cover __main__.py entry points that call main() directly.

These modules just do:
    from sox_protocol.xxx import main
    main()

Lines 4-6 are covered by executing those exact statements in-process with
main() mocked to be a no-op.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _exec_main_module(module_path: str) -> None:
    """Execute a __main__.py file's lines in-process for coverage."""
    spec = importlib.util.spec_from_file_location("__main__", module_path)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    mod.__name__ = "__main__"
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]


_ENFORCER_MAIN = (
    Path(__file__).resolve().parents[2]
    / "src" / "sox_protocol" / "enforcer" / "__main__.py"
)

_MCP_MAIN = (
    Path(__file__).resolve().parents[2]
    / "src" / "sox_protocol" / "core" / "mcp_server" / "__main__.py"
)


_CLI_MAIN = (
    Path(__file__).resolve().parents[2]
    / "src" / "sox_protocol" / "cli" / "__main__.py"
)

def test_enforcer_main_module_lines_covered() -> None:
    """Covers enforcer/__main__.py lines 4-6 by executing them with main() mocked."""
    with patch("sox_protocol.enforcer.cli.main") as mock_main:
        _exec_main_module(str(_ENFORCER_MAIN))
    mock_main.assert_called_once()


def test_mcp_server_main_module_lines_covered() -> None:
    """Covers core/mcp_server/__main__.py lines 4-6 by executing them with main() mocked."""
    with patch("sox_protocol.core.mcp_server.server.main"):
        _exec_main_module(str(_MCP_MAIN))


def test_cli_main_module_line_45_covered() -> None:
    """Covers cli/__main__.py line 45 (sys.exit(main())) by executing it with main() mocked."""
    # The __main__.py calls sys.exit(main()). We patch sys.argv to [] so main()
    # returns 0 (no subcommand → print help → return 0).
    with patch.object(sys, "argv", ["sox"]), pytest.raises(SystemExit) as exc_info:
        _exec_main_module(str(_CLI_MAIN))
    assert exc_info.value.code == 0


