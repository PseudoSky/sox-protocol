# SPDX-License-Identifier: Apache-2.0
"""``sox-protocol channels`` CLI subcommand family.

One-shot shell access to the same operations the MCP server exposes as
``mcp__sox__channels__*`` tools.  Each subcommand:

  1. Discovers the project's backing-store URI from ``.mcp.json``
     (or ``SOX_BACKING_STORE`` env, or falls back to ``memory://``).
  2. Resolves the agent_id from ``--agent-id`` flag or the same
     ``SOX_AGENT_ID_SOURCE`` chain the MCP server uses.
  3. Opens the backing store directly and invokes the matching method.
  4. Prints the result as indented JSON (default) or single-line JSON (``--compact``).

This bypasses the MCP-over-stdio transport for speed; the side-effects
on the SQLite database are identical to what an MCP-mediated call would
produce.  Long-running commands (``listen``) construct the necessary
listener locally.

Subcommands and their MCP equivalents:

    send          ↔ channels__send
    recv          ↔ channels__recv
    subscribe     ↔ channels__subscribe
    unsubscribe   ↔ channels__unsubscribe
    ack           ↔ channels__ack
    heartbeat     ↔ channels__heartbeat
    list-agents   ↔ channels__list_agents
    list-channels ↔ channels__list_channels
    replay        ↔ channels__replay
    listen        ↔ background drain loop (no direct MCP equivalent)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sox_protocol.cli._session import (
    open_store,
    resolve_agent_id,
    resolve_backing_store_uri,
)
from sox_protocol.core.ports.backing_store import BackingStore

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _emit_json(obj: Any, *, pretty: bool = True) -> None:
    """Print *obj* as JSON to stdout."""
    if pretty:
        print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))
    else:
        print(json.dumps(obj, default=str, ensure_ascii=False))


def _parse_body(text: str | None, body_json: str | None) -> dict[str, Any]:
    """Resolve a message body from either ``--text`` or ``--body``."""
    if text is not None and body_json is not None:
        raise SystemExit("error: pass --text OR --body, not both")
    if body_json is not None:
        try:
            parsed = json.loads(body_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"error: --body must be valid JSON ({exc})") from exc
        if not isinstance(parsed, dict):
            raise SystemExit("error: --body must be a JSON object")
        return parsed
    if text is not None:
        return {"text": text}
    raise SystemExit("error: provide either --text or --body")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


async def _cmd_send(args: argparse.Namespace) -> int:
    body = _parse_body(args.text, args.body)
    agent_id = resolve_agent_id(args.agent_id)
    store = await open_store()
    try:
        message_id, sent_at, seq, backpressure = await store.send(
            channel=args.channel,
            sender=agent_id,
            body=body,
            correlation_id=args.correlation_id,
            reply_to=args.reply_to,
        )
    finally:
        await store.close()

    receipt = {
        "message_id": message_id,
        "channel": args.channel,
        "sender": agent_id,
        "sent_at": sent_at,
        "seq": seq,
        "backpressure": {
            "queue_depth": backpressure.queue_depth,
            "threshold": backpressure.threshold,
            "over_limit": backpressure.over_limit,
            "mode": backpressure.mode,
            "state": backpressure.state,
        }
        if backpressure
        else None,
    }
    _emit_json(receipt, pretty=not args.compact)
    return 0


async def _cmd_recv(args: argparse.Namespace) -> int:
    agent_id = resolve_agent_id(args.agent_id)
    channels = list(args.channel) if args.channel else None
    store = await open_store()
    try:
        # The store's recv() expects a non-empty channel list — when --channel
        # is omitted we pull the agent's subscriptions and drain those.
        if not channels:
            patterns = await store._get_patterns_for_agent(agent_id)  # type: ignore[attr-defined]
            channels = patterns or []
        if not channels:
            _emit_json({"messages": [], "note": "no subscriptions found"}, pretty=not args.compact)
            return 0
        messages = await store.recv(
            agent_id=agent_id,
            channels=channels,
            max_messages=args.max,
        )
    finally:
        await store.close()

    _emit_json({"agent_id": agent_id, "messages": messages}, pretty=not args.compact)
    return 0


async def _cmd_subscribe(args: argparse.Namespace) -> int:
    agent_id = resolve_agent_id(args.agent_id)
    store = await open_store()
    try:
        matched = await store.subscribe(agent_id, args.pattern)
    finally:
        await store.close()
    _emit_json(
        {"agent_id": agent_id, "pattern": args.pattern, "matched_channels": matched},
        pretty=not args.compact,
    )
    return 0


async def _cmd_unsubscribe(args: argparse.Namespace) -> int:
    agent_id = resolve_agent_id(args.agent_id)
    store = await open_store()
    try:
        removed_patterns, removed_count = await store.unsubscribe(
            agent_id, [args.pattern]
        )
    finally:
        await store.close()
    _emit_json(
        {
            "agent_id": agent_id,
            "removed_patterns": removed_patterns,
            "removed_count": removed_count,
        },
        pretty=not args.compact,
    )
    return 0


async def _cmd_ack(args: argparse.Namespace) -> int:
    agent_id = resolve_agent_id(args.agent_id)
    store = await open_store()
    try:
        result = await store.ack(
            agent_id=agent_id,
            message_id=args.message_id,
            status=args.status,
            reason=args.reason,
        )
    finally:
        await store.close()
    _emit_json(result, pretty=not args.compact)
    return 0


async def _cmd_heartbeat(args: argparse.Namespace) -> int:
    agent_id = resolve_agent_id(args.agent_id)
    store = await open_store()
    try:
        result = await store.heartbeat(agent_id, args.status, ttl=args.ttl)
    finally:
        await store.close()
    _emit_json(result, pretty=not args.compact)
    return 0


async def _cmd_list_agents(args: argparse.Namespace) -> int:
    store = await open_store()
    try:
        agents = await store.list_agents(
            status_filter=args.status or None,
            namespace=args.namespace,
        )
    finally:
        await store.close()
    _emit_json({"agents": agents}, pretty=not args.compact)
    return 0


async def _cmd_list_channels(args: argparse.Namespace) -> int:
    store = await open_store()
    try:
        channels = await store.list_channels(since=args.since)
    finally:
        await store.close()
    _emit_json({"channels": channels}, pretty=not args.compact)
    return 0


async def _cmd_replay(args: argparse.Namespace) -> int:
    store = await open_store()
    try:
        msgs, has_more = await store.replay(
            channel=args.channel,
            since=args.since,
            until=args.until,
            limit=args.limit,
        )
    finally:
        await store.close()
    _emit_json({"messages": msgs, "has_more": has_more}, pretty=not args.compact)
    return 0


async def _cmd_listen(args: argparse.Namespace) -> int:
    """Long-running drain — prints each message as it arrives.

    Subscribes the resolved agent_id to *args.channel* (or, if omitted,
    its existing subscription set), then awaits the store's ``watch()``
    generator emitting JSON-Lines to stdout.

    Sending to the channel from another process (or via
    ``sox-protocol channels send`` in another shell) yields a print here.

    Exits on Ctrl-C with code 0.
    """
    agent_id = resolve_agent_id(args.agent_id)
    store = await open_store()

    try:
        # Subscribe to anything the user asked for.  Existing subscriptions
        # are additive (subscribe is upsert).
        for pattern in args.channel or []:
            await store.subscribe(agent_id, pattern)

        if not args.channel:
            existing = await store._get_patterns_for_agent(agent_id)  # type: ignore[attr-defined]
            if not existing:
                print(
                    f"agent {agent_id!r} has no subscriptions; "
                    "pass --channel <pattern> to subscribe-and-listen",
                    file=sys.stderr,
                )
                return 1

        sys.stderr.write(
            f"listening as {agent_id!r}; press Ctrl-C to exit\n"
        )
        sys.stderr.flush()

        try:
            async for msg in store.watch(agent_id):
                # Single-line JSON for line-based grep / jq pipelines.
                print(json.dumps(msg, default=str, ensure_ascii=False), flush=True)
        except (asyncio.CancelledError, KeyboardInterrupt):
            return 0
    finally:
        await store.close()
    return 0


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def _add_compact_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact (single-line) JSON instead of indented.",
    )


def _add_agent_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--agent-id",
        default=None,
        metavar="ID",
        help=(
            "Agent identity for this call.  Defaults to the SOX_AGENT_ID_SOURCE "
            "resolution chain (see `sox-protocol install --agent-id-source`), "
            "then `cli-<whoami>`."
        ),
    )


def add_channels_subcommand(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``channels`` family of subcommands."""
    parser = subparsers.add_parser(
        "channels",
        help="Direct shell access to the SOX channels API (matches MCP tools).",
        description=(
            "One-shot CLI invocations of the same operations the MCP server "
            "exposes as `mcp__sox__channels__*` tools.  Each subcommand "
            "discovers the project's backing-store URI from `.mcp.json` and "
            "talks to the BackingStore port directly."
        ),
    )
    sub = parser.add_subparsers(dest="channels_command", required=True)

    # send -----------------------------------------------------------------
    p_send = sub.add_parser("send", help="Publish a message to a channel.")
    p_send.add_argument("channel", help="Channel name (e.g. agent/alice).")
    p_send.add_argument("--text", default=None, help="Message body as plain text (wrapped as {\"text\": ...}).")
    p_send.add_argument("--body", default=None, metavar="JSON", help="Message body as a JSON object literal.")
    p_send.add_argument("--correlation-id", default=None, dest="correlation_id", metavar="ID")
    p_send.add_argument("--reply-to", default=None, dest="reply_to", metavar="MSG_ID")
    _add_agent_flag(p_send)
    _add_compact_flag(p_send)
    p_send.set_defaults(func=lambda a: asyncio.run(_cmd_send(a)))

    # recv -----------------------------------------------------------------
    p_recv = sub.add_parser("recv", help="Drain pending messages from subscribed channels.")
    p_recv.add_argument(
        "--channel",
        action="append",
        default=None,
        metavar="CH",
        help="Channel(s) to drain.  Repeat for multiple.  Default: drain everything the agent is subscribed to.",
    )
    p_recv.add_argument("--max", type=int, default=50, help="Max messages to drain (default: 50).")
    _add_agent_flag(p_recv)
    _add_compact_flag(p_recv)
    p_recv.set_defaults(func=lambda a: asyncio.run(_cmd_recv(a)))

    # subscribe ------------------------------------------------------------
    p_sub = sub.add_parser("subscribe", help="Subscribe an agent to a channel pattern.")
    p_sub.add_argument("pattern", help="Channel name or glob (e.g. agent/alice or team/*).")
    _add_agent_flag(p_sub)
    _add_compact_flag(p_sub)
    p_sub.set_defaults(func=lambda a: asyncio.run(_cmd_subscribe(a)))

    # unsubscribe ----------------------------------------------------------
    p_unsub = sub.add_parser("unsubscribe", help="Remove an agent's subscription pattern.")
    p_unsub.add_argument("pattern", help="Channel pattern to remove.")
    _add_agent_flag(p_unsub)
    _add_compact_flag(p_unsub)
    p_unsub.set_defaults(func=lambda a: asyncio.run(_cmd_unsubscribe(a)))

    # ack ------------------------------------------------------------------
    p_ack = sub.add_parser("ack", help="Acknowledge a received message.")
    p_ack.add_argument("message_id")
    p_ack.add_argument(
        "--status",
        choices=["accept", "reject", "nack"],
        default="accept",
        help="Ack status (default: accept).",
    )
    p_ack.add_argument("--reason", default=None, help="Optional reason text (esp. for reject/nack).")
    _add_agent_flag(p_ack)
    _add_compact_flag(p_ack)
    p_ack.set_defaults(func=lambda a: asyncio.run(_cmd_ack(a)))

    # heartbeat ------------------------------------------------------------
    p_hb = sub.add_parser("heartbeat", help="Emit a presence heartbeat.")
    p_hb.add_argument(
        "--status",
        default="online",
        choices=["online", "busy", "offline"],
        help="Presence status (default: online).",
    )
    p_hb.add_argument(
        "--ttl",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "Per-call TTL.  Omit to use the server-side default "
            "(SOX_HEARTBEAT_TTL_DEFAULT, then backing-store default 30s)."
        ),
    )
    _add_agent_flag(p_hb)
    _add_compact_flag(p_hb)
    p_hb.set_defaults(func=lambda a: asyncio.run(_cmd_heartbeat(a)))

    # list-agents ----------------------------------------------------------
    p_la = sub.add_parser("list-agents", help="Print the cross-process liveness roster.")
    p_la.add_argument(
        "--status",
        action="append",
        default=None,
        choices=["online", "busy", "stale", "offline"],
        help="Filter by presence status (repeatable).",
    )
    p_la.add_argument("--namespace", default=None, help="Filter by namespace.")
    _add_compact_flag(p_la)
    p_la.set_defaults(func=lambda a: asyncio.run(_cmd_list_agents(a)))

    # list-channels --------------------------------------------------------
    p_lc = sub.add_parser("list-channels", help="Print known channels with subscriber counts.")
    p_lc.add_argument(
        "--since",
        type=float,
        default=None,
        metavar="EPOCH",
        help="Only consider messages with sent_at >= EPOCH (Unix seconds).  Default: last 24h.",
    )
    _add_compact_flag(p_lc)
    p_lc.set_defaults(func=lambda a: asyncio.run(_cmd_list_channels(a)))

    # replay ---------------------------------------------------------------
    p_re = sub.add_parser("replay", help="Replay messages from a channel by per-channel seq.")
    p_re.add_argument("channel")
    p_re.add_argument("--since", type=int, default=0, help="Starting seq (default: 0 = from start).")
    p_re.add_argument("--until", type=int, default=None, help="Ending seq (inclusive; default: latest).")
    p_re.add_argument("--limit", type=int, default=100, help="Max messages to return (default: 100).")
    _add_compact_flag(p_re)
    p_re.set_defaults(func=lambda a: asyncio.run(_cmd_replay(a)))

    # listen ---------------------------------------------------------------
    p_li = sub.add_parser(
        "listen",
        help="Long-running drain — print messages as they arrive (Ctrl-C to exit).",
    )
    p_li.add_argument(
        "--channel",
        action="append",
        default=None,
        metavar="CH",
        help="Subscribe to this channel before listening.  Repeat for multiple.  "
        "Optional: omit to use the agent's existing subscriptions.",
    )
    _add_agent_flag(p_li)
    p_li.set_defaults(func=lambda a: asyncio.run(_cmd_listen(a)))

    parser.set_defaults(func=lambda a: _print_help_and_exit(parser))


def _print_help_and_exit(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


# Re-export helpers for tests / future composition.
__all__ = [
    "add_channels_subcommand",
    "BackingStore",
    "resolve_backing_store_uri",
    "resolve_agent_id",
]


# Suppress unused-import lint for the explicit re-exports.
_ = (BackingStore, resolve_backing_store_uri, resolve_agent_id, Path)
