# SPDX-License-Identifier: Apache-2.0
"""``sox-protocol upgrade`` CLI subcommand.

End-to-end upgrade flow for a SOX-installed Claude Code project:

1. **PyPI check.** Compare the installed versions of ``sox-protocol`` and
   ``sox-plugin-schema-strict`` against PyPI's latest. If newer is
   available, run ``pip install --upgrade`` on the affected packages.
   After pip changes anything, re-exec ourselves so the rest of the
   upgrade runs against the new code (``--skip-pip`` prevents the loop).
2. **File refresh.** Re-run ``sox-protocol install`` (idempotent — only
   rewrites files that actually changed: ``SKILL.md`` from the latest spec,
   hook scripts, ``.mcp.json``, ``.claude/settings.json``).
3. **SQLite migration.** Locate the backing store from ``.mcp.json`` and
   run the schema-migration chain forward to the latest version.
   Migrations are additive (e.g. v1.1→v1.2 was ``ALTER TABLE messages ADD
   COLUMN reply_to``) so existing data survives.
4. Print a summary of pip changes, files rewritten, and migrations run.

The SQLite migration ALSO runs lazily on the first MCP server connection.
``upgrade`` makes it explicit + visible (and lets you upgrade without
launching an MCP client first).

Use cases::

    sox-protocol upgrade               # full pipeline: pip → files → migrate
    sox-protocol upgrade --check-only  # report only — no side effects
    sox-protocol upgrade --skip-pip    # skip PyPI/pip; refresh files + migrate
    sox-protocol upgrade --no-migrate  # skip SQLite migration step
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from sox_protocol import __version__ as _runtime_version
from sox_protocol.adapters.runtimes.claude_code.install import install

_log = logging.getLogger(__name__)

# Packages tracked for the pip-upgrade step. Add to this list as new SOX
# plugins enter the canonical install set. (Third-party plugins discovered
# via the ``sox_protocol.plugins`` entry-point group are NOT touched —
# users opted in to those manually.)
_TRACKED_PACKAGES = ("sox-protocol", "sox-plugin-schema-strict")


# ---------------------------------------------------------------------------
# Backing-store discovery
# ---------------------------------------------------------------------------


def _discover_db_path(project_dir: Path) -> Path | None:
    """Return the SQLite path from ``.mcp.json``'s ``mcpServers.sox.env``.

    Returns ``None`` if the project doesn't have an ``.mcp.json``, or the
    backing store is non-SQLite (memory://, a custom URI), or the
    SOX_BACKING_STORE env var is missing.
    """
    # 1. Project's .mcp.json (the canonical place after `sox-protocol install`).
    mcp_path = project_dir / ".mcp.json"
    backing_store_url: str | None = None
    if mcp_path.is_file():
        try:
            with mcp_path.open(encoding="utf-8") as fh:
                cfg = json.load(fh)
            backing_store_url = (
                cfg.get("mcpServers", {})
                .get("sox", {})
                .get("env", {})
                .get("SOX_BACKING_STORE")
            )
        except (OSError, json.JSONDecodeError) as exc:
            _log.debug("Could not read %s: %s", mcp_path, exc)

    # 2. Fall back to the user's shell env if .mcp.json didn't have it.
    if not backing_store_url:
        backing_store_url = os.environ.get("SOX_BACKING_STORE")

    if not backing_store_url:
        return None

    # Parse only sqlite:// URLs — memory:// and other schemes have no
    # on-disk file to migrate.
    if not backing_store_url.startswith(("sqlite:///", "sqlite://")):
        return None

    parsed = urlparse(backing_store_url)
    db_path_str = parsed.path
    if not db_path_str or db_path_str in ("/:memory:", ":memory:"):
        return None

    # ``urlparse("sqlite:////abs/path").path`` returns ``"//abs/path"`` (it
    # treats the first ``/`` as the netloc separator), which is technically
    # POSIX-valid but ugly to display.  Collapse a leading ``//`` to ``/``.
    if db_path_str.startswith("//"):
        db_path_str = db_path_str[1:]

    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = project_dir / db_path_str.lstrip("/")
    return db_path


# ---------------------------------------------------------------------------
# PyPI version check + pip-upgrade
# ---------------------------------------------------------------------------


def _fetch_latest_pypi_version(package: str, *, timeout: float = 5.0) -> str | None:
    """Return the latest version of *package* on PyPI, or ``None`` on any error.

    Uses the public PyPI JSON API.  Errors (network, JSON parse, missing
    package) are logged at DEBUG level and swallowed — the upgrade flow
    continues with whatever it knows locally.
    """
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        req = Request(url, headers={"User-Agent": f"sox-protocol/{_runtime_version}"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed PyPI URL
            data = json.load(resp)
    except Exception as exc:  # network/JSON/etc — best-effort
        _log.debug("PyPI lookup failed for %s: %s", package, exc)
        return None
    info = data.get("info") or {}
    latest = info.get("version")
    return latest if isinstance(latest, str) else None


def _local_version(package: str) -> str | None:
    """Return the installed version of *package*, or ``None`` if not installed."""
    try:
        return _installed_version(package)
    except PackageNotFoundError:
        return None


def _check_packages(
    packages: tuple[str, ...] = _TRACKED_PACKAGES,
) -> list[tuple[str, str | None, str | None, bool]]:
    """For each package, return ``(name, local, latest, is_outdated)``.

    ``is_outdated`` is True iff both versions are present and parse as PEP 440
    versions and ``latest > local``.  Pre-release ordering follows
    ``packaging.version`` rules.
    """
    rows: list[tuple[str, str | None, str | None, bool]] = []
    for name in packages:
        local = _local_version(name)
        latest = _fetch_latest_pypi_version(name)
        outdated = False
        if local and latest:
            try:
                outdated = Version(latest) > Version(local)
            except InvalidVersion:
                outdated = False
        rows.append((name, local, latest, outdated))
    return rows


def _pip_upgrade(packages: list[str], *, quiet: bool) -> int:
    """Run ``python -m pip install --upgrade <packages>``.  Returns the exit code."""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *packages]
    if quiet:
        cmd.insert(4, "--quiet")
    if not quiet:
        print(f"  $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _reexec_self(*extra_args: str) -> None:
    """Replace this process with a fresh ``sox-protocol upgrade`` invocation.

    The current Python interpreter has the OLD package code loaded in
    memory.  After ``pip install --upgrade`` writes new files to disk, only
    a re-exec swaps in the new code for the file-refresh + migration
    phases.  We pass ``--skip-pip`` so the new process doesn't loop on the
    PyPI check.
    """
    # Reconstruct: python -m sox_protocol.cli upgrade <existing-flags> --skip-pip
    new_argv = [
        sys.executable,
        "-m",
        "sox_protocol.cli",
        "upgrade",
        *extra_args,
        "--skip-pip",
    ]
    os.execv(sys.executable, new_argv)


# ---------------------------------------------------------------------------
# Migration driver
# ---------------------------------------------------------------------------


async def _run_migration(db_path: Path) -> tuple[str, list[str], str]:
    """Open *db_path*, run the migration chain, return ``(starting, applied, target)``.

    The target version is sourced from
    ``SqliteStore.schema_version`` so the upgrade always converges on the
    same shape that a fresh ``SqliteStore.initialize()`` would produce.
    """
    import aiosqlite

    from sox_protocol.adapters.backing_stores.sqlite.migration_runner import (
        get_persisted_version,
        migrate,
    )
    from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

    target = SqliteStore.schema_version

    # Use SqliteStore.initialize() if the DB doesn't exist yet — that path
    # also creates the schema.sql shape and stamps the meta table.
    if not db_path.exists():
        store = SqliteStore(str(db_path))
        async with store:
            pass  # initialize() runs in __aenter__
        return ("0.0", [], target)

    # Otherwise open a raw aiosqlite connection and run migrate() directly.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        starting = await get_persisted_version(conn)
        starting_returned, applied = await migrate(conn, target)
        await conn.commit()
        return (starting if starting != "0.0" else starting_returned, applied, target)


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def add_upgrade_subcommand(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``upgrade`` subcommand."""
    parser = subparsers.add_parser(
        "upgrade",
        help="Refresh installed files + run SQLite schema migrations.",
        description=(
            "Run after `pip install --upgrade sox-protocol`.  Refreshes "
            "the project's SOX install (SKILL.md, hooks, .mcp.json, "
            "settings.json — idempotent) and runs the SQLite schema "
            "migration chain forward to the latest version.  Migrations "
            "are additive; existing data survives.  Equivalent to "
            "`sox-protocol install` plus an explicit migration step that "
            "would otherwise run lazily on the first MCP server connection."
        ),
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to the Claude Code project root (default: current directory).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-step log; still print the final summary.",
    )
    parser.add_argument(
        "--no-migrate",
        action="store_true",
        help=(
            "Skip the SQLite schema migration step.  Useful when the "
            "backing store is non-SQLite or the DB lives on a remote host."
        ),
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help=(
            "Skip the PyPI version check + pip-upgrade phase.  "
            "Use when you've already upgraded the packages manually, "
            "or are running offline.  (Internal: also passed by the "
            "automatic re-exec after a successful pip upgrade.)"
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "Report what would be upgraded (PyPI version drift only) and exit. "
            "No pip changes, no file writes, no migration."
        ),
    )
    parser.add_argument(
        "--auto-subscribe",
        action="store_true",
        help=(
            "Re-render SKILL.md with the auto-subscribe activation block. "
            "See `sox-protocol install --auto-subscribe`.  Default "
            "preserves whatever shape the existing SKILL.md has."
        ),
    )
    parser.add_argument(
        "--channel",
        action="append",
        dest="default_channels",
        metavar="CHANNEL",
        help=(
            "Extra channel for the auto-subscribe block.  Repeat for "
            "multiple channels.  Ignored without --auto-subscribe."
        ),
    )
    parser.add_argument(
        "--no-permissions",
        action="store_true",
        help=(
            "Skip refreshing the SOX MCP tool names in "
            "`.claude/settings.json` `permissions.allow`.  Default behavior "
            "is to ensure all 15 SOX tools are present in the allow list."
        ),
    )
    parser.set_defaults(func=upgrade_command)


def upgrade_command(args: argparse.Namespace) -> int:
    """Execute the ``upgrade`` subcommand."""
    project_dir: Path = (args.project_dir or Path.cwd()).resolve()
    quiet: bool = args.quiet
    skip_migrate: bool = args.no_migrate
    skip_pip: bool = args.skip_pip
    check_only: bool = args.check_only

    if not quiet:
        print(f"sox-protocol upgrade — version {_runtime_version}")
        print(f"  Project dir: {project_dir}")
        print()

    # ── Step 1/3: PyPI version check + optional pip-upgrade ────────────────
    if not skip_pip or check_only:
        if not quiet:
            print("Step 1/3: checking PyPI for newer versions…")
        rows = _check_packages()
        outdated_pkgs: list[str] = []
        for name, local, latest, is_outdated in rows:
            local_str = local or "(not installed)"
            latest_str = latest or "(unreachable)"
            marker = "  → upgrade available" if is_outdated else ""
            if not quiet:
                print(f"  {name:30s}  local={local_str:12s}  latest={latest_str:12s}{marker}")
            if is_outdated:
                outdated_pkgs.append(name)

        if check_only:
            if not quiet:
                print()
                if outdated_pkgs:
                    print(f"  {len(outdated_pkgs)} package(s) outdated. Run `sox-protocol upgrade` to apply.")
                else:
                    print("  All tracked packages are up to date.")
            return 0

        if outdated_pkgs:
            if not quiet:
                print()
                print(f"  Upgrading {len(outdated_pkgs)} package(s) via pip…")
            rc = _pip_upgrade(outdated_pkgs, quiet=quiet)
            if rc != 0:
                if not quiet:
                    print(f"  [FAIL] pip install --upgrade exited with code {rc}.")
                return rc
            if not quiet:
                print("  pip upgrade complete; re-launching with the new code…")
                print()
            # Hand off to a fresh process loaded from the just-installed
            # files — the current interpreter still has the old code in memory.
            extra: list[str] = []
            if args.project_dir is not None:
                extra += ["--project-dir", str(args.project_dir)]
            if quiet:
                extra.append("--quiet")
            if skip_migrate:
                extra.append("--no-migrate")
            _reexec_self(*extra)
            return 0  # pragma: no cover — execv replaces the process
        if not quiet:
            print("  All tracked packages are up to date.")
            print()
    elif not quiet:
        print("Step 1/3: PyPI check SKIPPED (--skip-pip).")
        print()

    # ── Step 2/3: file refresh via the existing installer (idempotent) ─────
    if not quiet:
        print("Step 2/3: refreshing installed files…")
    install(
        project_dir=project_dir,
        verbose=not quiet,
        auto_subscribe=getattr(args, "auto_subscribe", False),
        default_channels=getattr(args, "default_channels", None),
        inject_permissions=not getattr(args, "no_permissions", False),
    )
    if not quiet:
        print()

    # ── Step 3/3: SQLite schema migration ──────────────────────────────────
    if skip_migrate:
        if not quiet:
            print("Step 3/3: SQLite migration SKIPPED (--no-migrate).")
        return 0

    if not quiet:
        print("Step 3/3: SQLite schema migration…")

    db_path = _discover_db_path(project_dir)
    if db_path is None:
        if not quiet:
            print(
                "  No SQLite backing store found in .mcp.json or env "
                "(non-SQLite backing store, or store not yet configured)."
            )
            print("  Skipping migration step.")
        return 0

    if not quiet:
        print(f"  DB path: {db_path}")

    try:
        starting, applied, target = asyncio.run(_run_migration(db_path))
    except Exception as exc:
        print(f"  [FAIL] Migration error: {exc!r}")
        return 1

    if not quiet:
        if applied:
            print(f"  Migrated {starting} → {target} ({len(applied)} step(s)):")
            for step in applied:
                print(f"    - {step}")
        elif starting == target:
            print(f"  Already at target version {target}; no migration needed.")
        else:
            print(f"  Stamped fresh DB at version {target}.")

    if not quiet:
        print()
        print("Upgrade complete. Run `sox-protocol verify` to confirm health.")
    return 0
