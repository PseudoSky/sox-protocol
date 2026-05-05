# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol — Claude Code runtime adapter installer.

Invocation::

    python -m sox_protocol.adapters.runtimes.claude_code install [--project-dir PATH]

This module implements ``DisciplineRenderer`` + ``EnforcerBinding`` installation
for the Claude Code runtime.  Running ``install`` is idempotent: executing it
twice MUST NOT duplicate content or break the project.

What it does
------------
1. Reads ``spec/discipline/discipline.md`` (bundled into the wheel).
2. Renders ``skill/SKILL.md.template`` with the discipline body.
3. Substitutes ``{{placeholder}}`` tokens with Claude Code tool names.
4. Writes ``<project>/.claude/skills/inter-agent-channels/SKILL.md``.
5. Copies hook scripts to ``<project>/tools/sox-hooks/`` and makes them executable.
6. Updates ``<project>/.claude/settings.json``:
   - Registers ``PostToolUse``, ``Stop``, ``SubagentStop`` hooks.
   - Registers the SOX MCP server (SQLite backing store at ``.sox/messages.db``).
7. Inserts the bootstrap line into each ``<project>/.claude/agents/*.md`` file
   that does not already contain it.

Spec reference: CONTRACTS.md §7.1 (DisciplineRenderer) and §7.2 (EnforcerBinding).
"""

from __future__ import annotations

import importlib.resources
import json
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tool-name substitution map
# Claude Code MCP tool names follow the pattern mcp__<server>__<tool>
# ---------------------------------------------------------------------------

TOOL_SUBSTITUTIONS: dict[str, str] = {
    "{{send_tool}}": "mcp__sox__channels__send",
    "{{recv_tool}}": "mcp__sox__channels__recv",
    "{{subscribe_tool}}": "mcp__sox__channels__subscribe",
    "{{list_tool}}": "mcp__sox__channels__list_channels",
    # discipline.md also uses {{send_tool}} inside code blocks; handled by the
    # same substitution pass.
}

# The one-line bootstrap snippet inserted into agent system prompts.
# CONTRACTS.md §2 / USAGE.md §1.3 — exactly one line.
BOOTSTRAP_LINE = (
    "For coordination with other agents (clarification, broadcasts, peer questions), "
    "load the `inter-agent-channels` skill when blocked, broadcasting, or seeking "
    "peer input."
)

# Sentinel used to detect whether the bootstrap line is already present.
# We match on the unique substring rather than the exact full line so minor
# whitespace / line-ending variations don't cause duplication.
_BOOTSTRAP_SENTINEL = "load the `inter-agent-channels` skill"

# MCP server name registered in settings.json
_MCP_SERVER_NAME = "sox"

# Default backing-store path relative to the project root
_DEFAULT_DB_RELPATH = ".sox/messages.db"

# Default agent-id source for newly-written .mcp.json entries.
# Claude Code runtime exports CLAUDE_AGENT_NAME per session; that's our default.
_DEFAULT_AGENT_ID_SOURCE = "claude_code_agent_name"

# Default heartbeat cadence baked into the auto-subscribe activation block.
# These values can be overridden per-install via --heartbeat-interval /
# --heartbeat-ttl.  TTL must exceed interval so a slightly-late beat doesn't
# flap the agent's online status.
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15
_DEFAULT_HEARTBEAT_TTL_SECONDS = 30

# Hooks registered in settings.json
_HOOK_EVENTS = ["PostToolUse", "Stop", "SubagentStop"]

# Tool names registered by the SOX MCP server, in the Claude Code namespace
# (``mcp__<server>__<tool>``).  Used by ``_update_settings`` to inject
# ``permissions.allow`` entries so the agent can call them without
# per-call approval prompts.  Mirrors ``core/mcp_server/tools.py``'s
# ``register_tools()``.
_SOX_MCP_TOOL_NAMES: tuple[str, ...] = (
    "mcp__sox__channels__send",
    "mcp__sox__channels__recv",
    "mcp__sox__channels__subscribe",
    "mcp__sox__channels__unsubscribe",
    "mcp__sox__channels__ack",
    "mcp__sox__channels__heartbeat",
    "mcp__sox__channels__list_agents",
    "mcp__sox__channels__list_channels",
    "mcp__sox__channels__replay",
    "mcp__sox__channels__collect",
    "mcp__sox__group__create",
    "mcp__sox__group__invite",
    "mcp__sox__group__join",
    "mcp__sox__group__leave",
    "mcp__sox__group__list_members",
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _skills_dir(project_dir: Path) -> Path:
    return project_dir / ".claude" / "skills" / "inter-agent-channels"


def _hooks_install_dir(project_dir: Path) -> Path:
    return project_dir / "tools" / "sox-hooks"


def _settings_path(project_dir: Path) -> Path:
    return project_dir / ".claude" / "settings.json"


def _mcp_json_path(project_dir: Path) -> Path:
    return project_dir / ".mcp.json"


def _agents_dir(project_dir: Path) -> Path:
    return project_dir / ".claude" / "agents"


# ---------------------------------------------------------------------------
# Bundled resource helpers
# ---------------------------------------------------------------------------


def _bundled_discipline() -> str:
    """Return the contents of the bundled ``spec/discipline/discipline.md``."""
    try:
        # Installed wheel: spec/ is under sox_protocol package data
        pkg_ref = importlib.resources.files("sox_protocol")
        discipline_path = pkg_ref / "spec" / "discipline" / "discipline.md"
        return discipline_path.read_text(encoding="utf-8")
    except (FileNotFoundError, TypeError):
        pass

    # Development layout: walk up from this file to the repo root
    here = Path(__file__).parent
    for ancestor in [here, *here.parents]:
        candidate = ancestor / "spec" / "discipline" / "discipline.md"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")

    raise FileNotFoundError(
        "Cannot locate spec/discipline/discipline.md. "
        "If running from a source checkout, ensure the repo root contains spec/. "
        "If running from a wheel, file a bug — the wheel may be missing package data."
    )


def _bundled_template() -> str:
    """Return the contents of ``skill/SKILL.md.template``."""
    template_path = Path(__file__).parent / "skill" / "SKILL.md.template"
    return template_path.read_text(encoding="utf-8")


def _hook_source_dir() -> Path:
    """Return the directory containing the bundled hook shell scripts."""
    return Path(__file__).parent / "hooks"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _substitute_placeholders(text: str) -> str:
    """Replace all ``{{placeholder}}`` tokens with Claude Code tool names."""
    for placeholder, tool_name in TOOL_SUBSTITUTIONS.items():
        text = text.replace(placeholder, tool_name)
    return text


def _render_activation_section(
    auto_subscribe: bool,
    default_channels: list[str] | None,
) -> str:
    """Render the optional auto-subscribe section appended to SKILL.md.

    When ``auto_subscribe`` is False, returns an empty string — the skill
    is purely descriptive (loads the discipline + tool reference, doesn't
    take action on load).

    When ``auto_subscribe`` is True, returns a Markdown block that
    instructs the LLM to subscribe + drain + heartbeat-loop on first use.
    Includes any extra channels in *default_channels* alongside the agent's
    personal inbox (``agent/<your-agent-id>``).  Heartbeat numbers are the
    bundled defaults (``_DEFAULT_HEARTBEAT_INTERVAL_SECONDS`` /
    ``_DEFAULT_HEARTBEAT_TTL_SECONDS``); server-side overrides via
    ``SOX_HEARTBEAT_TTL_DEFAULT`` apply at runtime when the agent calls
    ``channels__heartbeat`` with ``ttl=None``.

    Args:
        auto_subscribe: Toggles the activation block on/off.
        default_channels: Optional list of channel patterns to subscribe to
            in addition to the personal inbox.  Empty / None ⇒ inbox only.

    Returns:
        Empty string or a Markdown block.  No leading newline (the template
        ends with one already).
    """
    if not auto_subscribe:
        return ""

    extras = list(default_channels or [])
    inbox_line = (
        '   `mcp__sox__channels__subscribe(channels=["agent/<your-agent-id>"])`'
    )
    if extras:
        # Render channels list as a JSON-style array for the example call.
        all_channels = ['"agent/<your-agent-id>"'] + [f'"{c}"' for c in extras]
        inbox_line = (
            "   `mcp__sox__channels__subscribe(channels=["
            + ", ".join(all_channels)
            + "])`"
        )

    heartbeat_ttl_seconds = _DEFAULT_HEARTBEAT_TTL_SECONDS
    heartbeat_interval_seconds = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS

    return f"""

## Activation (auto-subscribe)

This skill was installed with **auto-subscribe** enabled.  When this skill is
loaded into your context, your first actions in this session MUST be:

### 0. Pre-flight: tool availability

Check that the required MCP tools are present in your tool surface:

- ``mcp__sox__channels__subscribe``
- ``mcp__sox__channels__recv``
- ``mcp__sox__channels__heartbeat``

If **any** of these tools are missing, the SOX MCP server is not connected to
this session.  STOP — do **not** attempt steps 1–4.  Instead, tell the user:

> "I tried to auto-activate the inter-agent-channels skill, but the
> ``mcp__sox__channels__*`` tools aren't in my tool surface.  Run
> ``sox-protocol verify`` in this project root to diagnose, or
> ``sox-protocol install`` if you haven't installed SOX here yet.  Then
> restart this session."

This usually means one of:
- This project hasn't run ``sox-protocol install``.
- The ``.mcp.json`` exists but Claude Code didn't pick it up — restart the session.
- The session has a different MCP setup that excludes the ``sox`` server.

### 1. Subscribe to your inbox

Once the tools are confirmed present, subscribe so other agents can reach you:

{inbox_line}

Replace ``<your-agent-id>`` with the value of your agent-id env var (the
installer wires this to ``CLAUDE_AGENT_NAME`` by default; some hosts wire
``SOX_AGENT_NAME`` or another name via ``SOX_AGENT_ID_SOURCE=env:VARNAME``).
The MCP server already knows your identity — pass it explicitly for clarity.

### 2. Drain any pending messages

Once before continuing with your task:

`mcp__sox__channels__recv(channels=null, max_messages=50)`

``channels=null`` drains every channel you're subscribed to; iterate through
the messages, ack/nack as appropriate, then proceed.

### 3. Heartbeat once

So other agents see you as online:

`mcp__sox__channels__heartbeat(status="online", ttl={heartbeat_ttl_seconds})`

### 4. Keep heartbeating while you work

Your presence record expires **{heartbeat_ttl_seconds} seconds** after the
last beat — without ongoing heartbeats other agents will see you as
offline and the TUI roster will drop you.  Maintain liveness as follows:

- After **every** tool call or model turn that takes more than a few
  seconds, call:

  `mcp__sox__channels__heartbeat(status="online", ttl={heartbeat_ttl_seconds})`

- Aim for **one heartbeat at least every {heartbeat_interval_seconds} seconds**
  while you are actively working in this session.  The cadence hooks installed
  alongside this skill will remind you on every ``PostToolUse`` event — when
  you receive a reminder that mentions heartbeat, emit one.
- Set ``status="busy"`` if you are mid-task and won't read your inbox for
  a while; ``status="offline"`` is implicit when you stop heartbeating, do
  not call it manually unless you're winding down the session intentionally.
- TTL is per-call (default {heartbeat_ttl_seconds}s).  An operator can
  override the *server-side* default by exporting
  ``SOX_HEARTBEAT_TTL_DEFAULT=<seconds>`` in the MCP server's ``env`` block
  (in ``.mcp.json``); from the agent's perspective, just keep beating at
  the recommended cadence and the server will compute the right expiry.

### After activation

Follow the polling-cadence rules above for ongoing participation.  Do NOT
auto-subscribe to other channels without an explicit instruction in your
task — the auto-subscribe is one-shot, not a license to listen on every
channel forever.
"""


def render_skill_md(
    *,
    auto_subscribe: bool = False,
    default_channels: list[str] | None = None,
) -> str:
    """Render the full SKILL.md content ready for writing to disk.

    Args:
        auto_subscribe: When True, append an activation block telling the
            LLM to subscribe + drain + heartbeat-loop on first skill load.
            Default False keeps the skill purely descriptive (historical).
        default_channels: Extra channels to include in the auto-subscribe
            instruction alongside the personal inbox.  Ignored when
            ``auto_subscribe`` is False.

    Returns:
        The rendered Markdown string with frontmatter and substituted body.

    Note:
        The activation block bakes in the *bundled* default heartbeat
        TTL and interval (``_DEFAULT_HEARTBEAT_TTL_SECONDS`` /
        ``_DEFAULT_HEARTBEAT_INTERVAL_SECONDS``).  Server-side overrides
        via ``SOX_HEARTBEAT_TTL_DEFAULT`` apply at runtime when an agent
        sends a heartbeat with ``ttl=None``; the rendered SKILL.md numbers
        are the recommended cadence, not the enforced cadence.
    """
    template = _bundled_template()
    discipline_body = _bundled_discipline()
    substituted_body = _substitute_placeholders(discipline_body)
    skill_md = template.replace("{{discipline_body}}", substituted_body)
    activation = _render_activation_section(
        auto_subscribe,
        default_channels,
    )
    skill_md = skill_md.replace("{{activation_section}}", activation)
    return skill_md


# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------


def _write_skill(
    project_dir: Path,
    *,
    dry_run: bool = False,
    auto_subscribe: bool = False,
    default_channels: list[str] | None = None,
) -> bool:
    """Write SKILL.md. Returns True if the file was written (new or changed).

    Args:
        project_dir: Project root.
        dry_run: When True, compute idempotency-equality without writing.
        auto_subscribe: When True, the rendered SKILL.md includes an
            activation block that tells the LLM to subscribe + drain +
            heartbeat-loop on first load.  See ``_render_activation_section``.
        default_channels: Extra channels to include in the activation
            block alongside the agent's personal inbox.
    """
    skill_dir = _skills_dir(project_dir)
    skill_file = skill_dir / "SKILL.md"

    content = render_skill_md(
        auto_subscribe=auto_subscribe,
        default_channels=default_channels,
    )

    if skill_file.exists() and skill_file.read_text(encoding="utf-8") == content:
        return False  # already up-to-date

    if not dry_run:
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(content, encoding="utf-8")
    return True


def _write_hooks(project_dir: Path, *, dry_run: bool = False) -> bool:
    """Copy hook scripts to <project>/tools/sox-hooks/. Returns True if any changed."""
    src_dir = _hook_source_dir()
    dst_dir = _hooks_install_dir(project_dir)

    changed = False
    for hook_file in src_dir.glob("*.sh"):
        dst_file = dst_dir / hook_file.name
        src_content = hook_file.read_bytes()

        if dst_file.exists() and dst_file.read_bytes() == src_content:
            continue  # already identical

        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hook_file, dst_file)
            # Ensure executable bits are set
            current_mode = dst_file.stat().st_mode
            dst_file.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        changed = True

    return changed


def _load_settings(settings_path: Path) -> dict[str, Any]:
    """Load settings.json, returning an empty dict if the file does not exist."""
    if not settings_path.exists():
        return {}
    raw = settings_path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)  # type: ignore[no-any-return]


def _build_hook_entry(project_dir: Path, event: str) -> dict[str, Any]:
    """Construct a single hook entry for settings.json (Claude Code ≥0.2 format)."""
    hook_script_name = _event_to_script_name(event)
    hook_path = _hooks_install_dir(project_dir) / hook_script_name
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": str(hook_path)}],
    }


def _event_to_script_name(event: str) -> str:
    """Map a hook event name to the corresponding shell script filename."""
    mapping = {
        "PostToolUse": "post_tool_use.sh",
        "Stop": "stop.sh",
        "SubagentStop": "stop.sh",
    }
    return mapping.get(event, f"{event.lower()}.sh")


def _update_mcp_json(
    project_dir: Path,
    *,
    dry_run: bool = False,
    agent_id_source: str = _DEFAULT_AGENT_ID_SOURCE,
) -> bool:
    """Idempotently write/update .mcp.json with the SOX server entry.

    Args:
        project_dir: Project root.
        dry_run: When True, compute idempotency-equality without writing.
        agent_id_source: Value written to ``SOX_AGENT_ID_SOURCE`` in the
            MCP server's ``env`` block.  Recognized values: ``"claude_code_agent_name"``
            (default — read CLAUDE_AGENT_NAME), ``"env:VARNAME"`` (read
            arbitrary env var, e.g. ``env:SOX_AGENT_NAME``), or empty string
            (historical: SOX_AGENT_ID then CLAUDE_AGENT_NAME).
    """
    mcp_json_path = _mcp_json_path(project_dir)
    existing: dict[str, Any] = {}
    if mcp_json_path.exists():
        raw = mcp_json_path.read_text(encoding="utf-8").strip()
        if raw:
            existing = json.loads(raw)
    original = json.dumps(existing, sort_keys=True)

    servers: dict[str, Any] = existing.setdefault("mcpServers", {})
    if _MCP_SERVER_NAME not in servers:
        db_path = str(project_dir / _DEFAULT_DB_RELPATH)
        servers[_MCP_SERVER_NAME] = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "sox_protocol.core.mcp_server"],
            "env": {
                "SOX_BACKING_STORE": f"sqlite:///{db_path}",
                # Per spec/ports/identity.md §6: credential lives on the
                # connection seam, not in tool-call inputs.  This env var
                # documents to the MCP server which runtime channel supplies
                # the verified agent_id.  Default is "claude_code_agent_name"
                # (CLAUDE_AGENT_NAME); pass --agent-id-source env:VARNAME
                # to read a different env var (e.g. SOX_AGENT_NAME) when the
                # host already exports its own agent-id under another name.
                "SOX_AGENT_ID_SOURCE": agent_id_source,
            },
        }

    if json.dumps(existing, sort_keys=True) == original:
        return False

    if not dry_run:
        mcp_json_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return True


def _update_settings(
    project_dir: Path,
    *,
    dry_run: bool = False,
    inject_permissions: bool = True,
    agent_id_source: str = _DEFAULT_AGENT_ID_SOURCE,
) -> bool:
    """Idempotently update .claude/settings.json. Returns True if changed.

    Args:
        project_dir: Project root.
        dry_run: When True, compute idempotency-equality without writing.
        inject_permissions: When True (default), add the SOX MCP tool names
            to ``permissions.allow`` so agents can call them without
            per-call approval prompts.  Set False to keep the historical
            "ask on every call" UX.  Existing entries in ``permissions.allow``
            are preserved — we only append the SOX tools that aren't there.
        agent_id_source: Value written to ``SOX_AGENT_ID_SOURCE`` in the
            settings.json MCP server entry.  See ``_update_mcp_json`` for
            the recognized values.
    """
    settings_path = _settings_path(project_dir)
    settings = _load_settings(settings_path)
    original = json.dumps(settings, sort_keys=True)

    # --- Hooks ---
    hooks_section: dict[str, Any] = settings.setdefault("hooks", {})
    for event in _HOOK_EVENTS:
        hook_entry = _build_hook_entry(project_dir, event)
        target_cmd = hook_entry["hooks"][0]["command"]
        # Migrate: remove any old-format entries (bare {"type","command"}) for our script
        event_hooks_raw: list[dict[str, Any]] = hooks_section.setdefault(event, [])
        hooks_section[event] = [
            h for h in event_hooks_raw
            if h.get("command") != target_cmd  # drop old-format entries for our script
        ]
        event_hooks = hooks_section[event]
        # Idempotency: skip if new-format entry already present
        already_registered = any(
            any(h2.get("command") == target_cmd for h2 in h.get("hooks", []))
            for h in event_hooks
        )
        if not already_registered:
            event_hooks.append(hook_entry)

    # --- MCP server ---
    mcp_servers: dict[str, Any] = settings.setdefault("mcpServers", {})
    if _MCP_SERVER_NAME not in mcp_servers:
        db_path = str(project_dir / _DEFAULT_DB_RELPATH)
        mcp_servers[_MCP_SERVER_NAME] = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "sox_protocol.core.mcp_server"],
            "env": {
                "SOX_BACKING_STORE": f"sqlite:///{db_path}",
                # See _update_mcp_json for the agent_id_source semantics.
                "SOX_AGENT_ID_SOURCE": agent_id_source,
            },
        }

    # --- Explicit allowlist entry ---
    # Ensures the server is callable in all permission modes, not just 'auto'.
    allowed: list[dict[str, Any]] = settings.setdefault("allowedMcpServers", [])
    if not any(e.get("serverName") == _MCP_SERVER_NAME for e in allowed):
        allowed.append({"serverName": _MCP_SERVER_NAME})

    # --- permissions.allow ---
    # Inject the SOX MCP tool names so agents can call them without per-call
    # approval prompts.  Additive: existing entries (the user's, or other
    # plugins') are preserved.
    if inject_permissions:
        permissions: dict[str, Any] = settings.setdefault("permissions", {})
        allow_list_raw = permissions.setdefault("allow", [])
        if isinstance(allow_list_raw, list):
            existing = {entry for entry in allow_list_raw if isinstance(entry, str)}
            for tool_name in _SOX_MCP_TOOL_NAMES:
                if tool_name not in existing:
                    allow_list_raw.append(tool_name)
                    existing.add(tool_name)

    updated = json.dumps(settings, sort_keys=True)
    if updated == original:
        return False

    if not dry_run:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return True


def _insert_bootstrap(project_dir: Path, *, dry_run: bool = False) -> list[Path]:
    """Insert bootstrap line into agent .md files that lack it.

    Returns:
        List of Path objects for files that were modified (or would be if dry_run).
    """
    agents_dir = _agents_dir(project_dir)
    if not agents_dir.exists():
        return []

    modified: list[Path] = []
    for agent_file in sorted(agents_dir.glob("*.md")):
        content = agent_file.read_text(encoding="utf-8")
        if _BOOTSTRAP_SENTINEL in content:
            continue  # already present — idempotent

        # Append bootstrap line as a new paragraph at the end of the file
        separator = "\n\n" if content and not content.endswith("\n\n") else "\n"
        new_content = content.rstrip("\n") + separator + BOOTSTRAP_LINE + "\n"

        if not dry_run:
            agent_file.write_text(new_content, encoding="utf-8")
        modified.append(agent_file)

    return modified


# ---------------------------------------------------------------------------
# Public install entry point
# ---------------------------------------------------------------------------


def install(
    project_dir: Path | None = None,
    *,
    verbose: bool = True,
    auto_subscribe: bool = False,
    default_channels: list[str] | None = None,
    inject_permissions: bool = True,
    agent_id_source: str = _DEFAULT_AGENT_ID_SOURCE,
) -> None:
    """Install the SOX Claude Code adapter into *project_dir*.

    Idempotent: safe to call multiple times.  Only writes files when content
    has actually changed.

    Args:
        project_dir: Root of the target Claude Code project.  Defaults to
            ``Path.cwd()``.
        verbose: When ``True``, print a summary of actions taken to stdout.
        auto_subscribe: When ``True``, append an "Activation" section to
            ``SKILL.md`` that tells the LLM to subscribe to its personal
            inbox, drain pending messages, and emit periodic heartbeats on
            first skill load.  Default ``False`` keeps the historical
            purely-descriptive skill.
        default_channels: Extra channels to include in the auto-subscribe
            instruction (in addition to ``agent/<your-id>``).  Ignored when
            ``auto_subscribe`` is False.
        inject_permissions: When ``True`` (default), add the SOX MCP tool
            names to ``permissions.allow`` in ``.claude/settings.json`` so
            agents can call them without per-call approval prompts.  Set
            ``False`` to keep the historical "ask on every call" behavior.
        agent_id_source: Value written to ``SOX_AGENT_ID_SOURCE`` in the
            generated ``.mcp.json`` and ``settings.json`` MCP entries.
            Default ``"claude_code_agent_name"`` reads ``CLAUDE_AGENT_NAME``;
            pass ``"env:VARNAME"`` (e.g. ``"env:SOX_AGENT_NAME"``) to read
            an arbitrary env var instead, for hosts that already export
            their own agent-id under another name.

    Heartbeat cadence (TTL + interval) is configured at server runtime via
    ``SOX_HEARTBEAT_TTL_DEFAULT`` / ``SOX_HEARTBEAT_INTERVAL_HINT`` env vars
    on the MCP server's process — set them in the ``.mcp.json`` ``env`` block
    after install when you need to override the bundled defaults.  See
    :func:`sox_protocol.core.mcp_server.server.main` for the recognized vars.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    project_dir = project_dir.resolve()

    actions: list[str] = []

    # 1. Skill
    if _write_skill(
        project_dir,
        auto_subscribe=auto_subscribe,
        default_channels=default_channels,
    ):
        actions.append(f"  Wrote SKILL.md → {_skills_dir(project_dir) / 'SKILL.md'}")
    else:
        actions.append("  SKILL.md already up-to-date")

    # 2. Hooks
    if _write_hooks(project_dir):
        actions.append(f"  Wrote hook scripts → {_hooks_install_dir(project_dir)}/")
    else:
        actions.append("  Hook scripts already up-to-date")

    # 3. .mcp.json  (project MCP server discovery — read by Claude Code at startup)
    if _update_mcp_json(project_dir, agent_id_source=agent_id_source):
        actions.append(f"  Written {_mcp_json_path(project_dir)}")
    else:
        actions.append("  .mcp.json already up-to-date")

    # 4. settings.json  (hooks + allowedMcpServers)
    if _update_settings(
        project_dir,
        inject_permissions=inject_permissions,
        agent_id_source=agent_id_source,
    ):
        actions.append(f"  Updated {_settings_path(project_dir)}")
    else:
        actions.append("  settings.json already up-to-date")

    # 5. Bootstrap lines
    modified_agents = _insert_bootstrap(project_dir)
    if modified_agents:
        for af in modified_agents:
            actions.append(f"  Inserted bootstrap line → {af}")
    else:
        actions.append("  Bootstrap lines already present (or no agent files found)")

    if verbose:
        print("SOX Protocol — Claude Code adapter installed.")
        for action in actions:
            print(action)


# ---------------------------------------------------------------------------
# __main__ support: python -m sox_protocol.adapters.runtimes.claude_code install
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for ``python -m sox_protocol.adapters.runtimes.claude_code``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m sox_protocol.adapters.runtimes.claude_code",
        description="Install the SOX inter-agent-channels skill into a Claude Code project.",
    )
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Install the SOX adapter.")
    install_parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to the Claude Code project root (default: current directory).",
    )
    install_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output.",
    )
    install_parser.add_argument(
        "--auto-subscribe",
        action="store_true",
        help="Append an auto-subscribe Activation block to SKILL.md.",
    )
    install_parser.add_argument(
        "--channel",
        action="append",
        dest="default_channels",
        metavar="CHANNEL",
        help=(
            "Extra channel for the auto-subscribe block. Repeat for "
            "multiple channels. Ignored without --auto-subscribe."
        ),
    )
    install_parser.add_argument(
        "--no-permissions",
        action="store_true",
        help=(
            "Skip injecting SOX MCP tool names into "
            ".claude/settings.json's permissions.allow."
        ),
    )
    install_parser.add_argument(
        "--agent-id-source",
        default=_DEFAULT_AGENT_ID_SOURCE,
        metavar="SOURCE",
        help=(
            "Value written to SOX_AGENT_ID_SOURCE in the generated MCP "
            "server entries.  Default 'claude_code_agent_name' reads "
            "CLAUDE_AGENT_NAME; pass 'env:VARNAME' (e.g. "
            "'env:SOX_AGENT_NAME') to read an arbitrary env var instead."
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "install":
        install(
            project_dir=args.project_dir,
            verbose=not args.quiet,
            auto_subscribe=getattr(args, "auto_subscribe", False),
            default_channels=getattr(args, "default_channels", None),
            inject_permissions=not getattr(args, "no_permissions", False),
            agent_id_source=getattr(args, "agent_id_source", _DEFAULT_AGENT_ID_SOURCE),
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()  # pragma: no cover
