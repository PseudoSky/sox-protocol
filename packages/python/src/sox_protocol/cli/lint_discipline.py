# SPDX-License-Identifier: Apache-2.0
"""``sox-protocol lint-discipline`` CLI subcommand.

Validates a discipline markdown file's anchor structure:

- Required headings present and in canonical order
- No concrete tool names leaked outside ``{{placeholder}}`` substitution

Used by spec authors to keep ``spec/discipline/discipline.md`` adapter-
neutral.  Returns ``0`` on pass, ``1`` on fail.

Migrated from ``sox_protocol/cli.py`` in 0.1.5.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Lint rules
# ---------------------------------------------------------------------------

_REQUIRED_HEADINGS = [
    "# Inter-agent channels",
    "## When to send",
    "## How to send",
    "## Polling cadence",
    "## The send-and-continue pattern",
    "## The speculative-then-reconcile recipe",
    "## Anti-patterns",
    "## What not to use channels for",
]

_CONCRETE_TOOL_NAMES = [
    "mcp__sox__channels__send",
    "mcp__sox__channels__recv",
    "mcp__sox__channels__subscribe",
    "mcp__sox__channels__list_channels",
    "channels__send",
    "channels__recv",
    "channels__subscribe",
    "channels__list_channels",
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lint_discipline(discipline_path: Path) -> int:
    """Validate a discipline markdown file.  Returns 0 on pass, 1 on fail."""
    if not discipline_path.exists():
        print(f"[FAIL] File not found: {discipline_path}")
        return 1

    content = discipline_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    errors: list[str] = []

    # Required headings: present + in canonical order.
    last_pos = -1
    for heading in _REQUIRED_HEADINGS:
        found = False
        for i, line in enumerate(lines):
            if line.strip() == heading:
                if i <= last_pos:
                    errors.append(
                        f"Heading '{heading}' appears out of order (line {i + 1})"
                    )
                else:
                    last_pos = i
                found = True
                break
        if not found:
            errors.append(f"Required heading missing: '{heading}'")

    # No concrete tool names — discipline must use {{placeholder}} tokens
    # that adapters substitute at install time.
    for tool_name in _CONCRETE_TOOL_NAMES:
        if tool_name in content:
            errors.append(
                f"Concrete tool name found (must use placeholder instead): '{tool_name}'"
            )

    if errors:
        print(f"Discipline lint FAILED: {discipline_path}")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"Discipline lint passed: {discipline_path}")
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def add_lint_discipline_subcommand(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``lint-discipline`` subcommand."""
    parser = subparsers.add_parser(
        "lint-discipline",
        help="Validate a discipline markdown file's anchor structure.",
        description=(
            "Spec-author tool: checks required heading presence + ordering, "
            "and ensures no concrete tool names leak outside {{placeholder}} "
            "substitution. Used to keep spec/discipline/discipline.md "
            "adapter-neutral."
        ),
    )
    parser.add_argument("path", type=Path, help="Path to the discipline.md file.")
    parser.set_defaults(func=lint_discipline_command)


def lint_discipline_command(args: argparse.Namespace) -> int:
    """Execute the ``lint-discipline`` subcommand."""
    return lint_discipline(args.path)
