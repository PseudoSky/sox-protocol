# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol — canonical reference agent.

This file is the authoritative answer to "how do I write a SOX agent?".
Every lifecycle step from spec/protocol.md is implemented here with one
comment per ≤3 code lines so adopters can read the code and the spec
side-by-side without losing context.

Spec refs at a glance
----------------------
bootstrap        spec/protocol.md §bootstrap-sequence, spec/primitives/namespace.md
main_loop        spec/primitives/sequence-numbers.md, spec/primitives/channels.md
thread_handling  spec/primitives/threads.md, spec/primitives/sequence-numbers.md
ack_nack         spec/primitives/ack-nack.md
presence         spec/primitives/presence.md
graceful_stop    spec/protocol.md §graceful-stop, spec/primitives/presence.md
recovery         spec/operations/replay, spec/primitives/sequence-numbers.md
group_lifecycle  spec/primitives/groups.md §5.1-§5.5
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

from fastmcp import Client

# SeqState handles atomic {channel: last_seq} JSON persistence for recovery.
# It uses a temp-file + os.replace() pattern for crash-safe writes.
from state import SeqState

# ---------------------------------------------------------------------------
# Module-level logger — agents should use structured logging in production.
# ---------------------------------------------------------------------------
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

# The SOX server_version we are willing to talk to (spec/protocol.md §versioning).
SUPPORTED_PROTOCOL_VERSION: str = "1.0"

# Default heartbeat interval in seconds (spec/primitives/presence.md §3).
DEFAULT_HEARTBEAT_INTERVAL: int = 10

# Default poll cadence for the main recv loop in seconds.
DEFAULT_POLL_INTERVAL: float = 0.5

# ACK status constants — forward-only state machine (spec/primitives/ack-nack.md §3).
ACK_RECEIVED: str = "received"
ACK_PROCESSING: str = "processing"
ACK_DONE: str = "done"
ACK_NACK: str = "nack"


class ReferenceAgent:
    """Fully-annotated SOX reference agent.

    Demonstrates every protocol lifecycle step:
    bootstrap → recover → main_loop (with thread_handling, ack_nack,
    presence_heartbeat) → graceful_stop.

    Also exposes group lifecycle helpers (group_create, group_invite, etc.)
    used by the integration test to cover spec/primitives/groups.md §5.

    Args:
        client:     A connected FastMCP ``Client`` instance.
        agent_id:   Unique string identity for this agent.
        namespace:  SOX namespace (default ``"reference"``).
        state_dir:  Directory for seq.json recovery state.
    """

    def __init__(
        self,
        client: "Client[Any]",
        *,
        agent_id: str,
        namespace: str = "reference",
        state_dir: Path,
    ) -> None:
        # The FastMCP client used to call SOX MCP tools.
        self._client = client
        self._agent_id = agent_id
        self._namespace = namespace

        # SeqState persists {channel: last_seq} to disk for crash recovery.
        self._seq_state = SeqState(state_dir / "seq.json")

        # In-memory seq cursor; loaded from disk in recover_from_state().
        self._last_seq: dict[str, int] = {}

        # Pending message set: message_ids we have ACK'd received/processing
        # but not yet done/nack'd. Graceful stop checks this is empty.
        self._pending: set[str] = set()

        # Stop flag: set by graceful_stop() or SIGTERM handler.
        self._stop_event: asyncio.Event = asyncio.Event()

        # Presence status mirrors the server-side liveness record.
        self._presence_status: str = "online"

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 1 — bootstrap
    # PRIMITIVE COVERAGE: namespace
    # spec/protocol.md §bootstrap-sequence, spec/primitives/namespace.md
    # -----------------------------------------------------------------------

    async def bootstrap(self) -> None:
        """Establish the SOX session following the prescribed bootstrap sequence.

        Steps (per spec/protocol.md §bootstrap-sequence):
        1. list_channels — read ``_sox_protocol`` for version compatibility.
        2. subscribe — register interest in ticket:*, dm/<self>~*, sox/presence.
        3. list_agents — log current peers for situational awareness.
        4. recv (initial drain) — consume any messages queued during offline period.

        Raises:
            RuntimeError: If the server's protocol version is incompatible.
        """
        # --- Step 1: version handshake via list_channels (fail-fast on mismatch) ---
        _log.info("bootstrap: calling list_channels for version handshake")
        result = await self._client.call_tool("channels__list_channels", {})
        # Extract the _sox_protocol block — always present per spec §versioning.
        sox_block: dict[str, Any] = result.data.get("_sox_protocol", {})
        server_version: str = str(sox_block.get("server_version", "unknown"))
        # Reject connections where MAJOR version doesn't match ours.
        if not server_version.startswith(SUPPORTED_PROTOCOL_VERSION.split(".")[0]):
            raise RuntimeError(
                f"SOX version mismatch: server={server_version!r}, "
                f"client supports={SUPPORTED_PROTOCOL_VERSION!r}. "
                "Check spec/protocol.md §versioning for upgrade path."
            )
        _log.info("bootstrap: server version %s — compatible", server_version)

        # --- Step 2: subscribe to the channels this agent needs ---
        # ticket:* — all work-item channels (the primary work surface).
        # Glob subscriptions are allowed on non-reserved prefixes.
        await self._client.call_tool(
            "channels__subscribe", {"pattern": "ticket:*"}
        )
        # sox/presence — server-emitted presence events for peer visibility.
        # The sox/ prefix is reserved for server-emitted channels (read-only).
        await self._client.call_tool(
            "channels__subscribe", {"pattern": "sox/presence"}
        )
        # NOTE: DM subscriptions use exact channel names (spec/primitives/dms.md).
        # The dm/ prefix is reserved and wildcards on it are forbidden by the server.
        # To receive DMs, subscribe to the exact channel name: dm/<sorted-pair>.
        # Example: dm/agent-a~agent-b where names are lexicographically sorted.
        # The integration test subscribes to specific DM channels directly.
        _log.info("bootstrap: subscriptions established for agent_id=%s", self._agent_id)

        # --- Step 3: discover current peers via list_agents ---
        agents_result = await self._client.call_tool("channels__list_agents", {})
        agents: list[dict[str, Any]] = agents_result.data.get("agents", [])
        _log.info("bootstrap: %d peer(s) known to server", len(agents))

        # --- Step 4: emit first heartbeat to register as online ---
        # This is the signal that other agents see when they call list_agents.
        await self._client.call_tool(
            "channels__heartbeat", {"status": "online"}
        )
        _log.info(
            "bootstrap: heartbeat(online) emitted for agent_id=%s namespace=%s",
            self._agent_id,
            self._namespace,
        )

        # --- Step 5: initial drain — flush messages queued during offline period ---
        # Per spec §bootstrap-sequence step 4, the first recv drains pre-existing msgs.
        drain = await self._client.call_tool("channels__recv", {})
        pre_existing: list[dict[str, Any]] = drain.data.get("messages", [])
        _log.info(
            "bootstrap: drained %d pre-existing message(s) from prior session",
            len(pre_existing),
        )
        # Discard pre-existing messages silently during bootstrap; the main loop
        # will process messages from the recovered seq cursor onward.

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 2 — main_loop
    # spec/primitives/sequence-numbers.md, spec/primitives/channels.md
    # -----------------------------------------------------------------------

    async def main_loop(self) -> None:
        """Pull-based drain loop: recv → handle_message → ack lifecycle.

        The loop runs until ``_stop_event`` is set (by graceful_stop or SIGTERM).
        On each cycle it drains the mailbox, advances the seq cursor, and hands
        each message to ``handle_message`` which drives the ack state machine.
        """
        _log.info("main_loop: starting poll loop (interval=%.2fs)", DEFAULT_POLL_INTERVAL)
        while not self._stop_event.is_set():
            # Drain the mailbox — non-blocking; returns [] when empty.
            # The backing-store listener pushes new messages into a queue;
            # recv drains that queue atomically, marking each message delivered.
            recv_result = await self._client.call_tool("channels__recv", {})
            messages: list[dict[str, Any]] = recv_result.data.get("messages", [])

            # Flip presence to busy while we process a non-empty batch.
            # This signals peers that we are active without skipping a heartbeat.
            if messages:
                await self._set_presence("busy")

            for envelope in messages:
                # ACK(received) immediately upon retrieving the message.
                msg_id: str = str(envelope.get("message_id", ""))
                await self.ack(msg_id, ACK_RECEIVED)

                # Process the message; ACK transitions happen inside handle_message.
                try:
                    await self.handle_message(envelope)
                except Exception as exc:
                    # NACK on unhandled exception so the sender knows we failed.
                    _log.exception("main_loop: unhandled error for %s", msg_id)
                    await self.ack(msg_id, ACK_NACK, reason=str(exc))

                # Advance the per-channel seq cursor for recovery continuity.
                channel: str = str(envelope.get("channel", ""))
                seq: int = int(envelope.get("seq", 0))
                if channel and seq:
                    self._last_seq[channel] = seq
                    # Persist the new cursor after successful processing.
                    self._seq_state.update(channel, seq)

            # Return to online status after draining the batch.
            # online = idle and ready; set before sleeping so peers see it promptly.
            if messages:
                await self._set_presence("online")

            # Yield control between polls — avoids busy-spinning on empty inbox.
            # asyncio.sleep is cooperative; other tasks (heartbeat) run during this.
            await asyncio.sleep(DEFAULT_POLL_INTERVAL)

        _log.info("main_loop: stop event set — exiting poll loop")

    async def handle_message(self, envelope: dict[str, Any]) -> None:
        """Dispatch an incoming message to the appropriate handler.

        This is the single entry point for all inbound messages. It reads
        ``body.type`` and routes to the correct handler. Adopters extend
        this method to add their own message types.

        Args:
            envelope: Wire-format message dict as returned by channels__recv.
        """
        # Extract the body — it is opaque per spec but we inspect body.type.
        body: dict[str, Any] = envelope.get("body") or {}
        msg_type: str = str(body.get("type", ""))
        msg_id: str = str(envelope.get("message_id", ""))

        # ACK(processing) as soon as we begin interpreting the message.
        await self.ack(msg_id, ACK_PROCESSING)

        _log.info(
            "handle_message: channel=%s msg_id=%s type=%s",
            envelope.get("channel"),
            msg_id,
            msg_type or "(none)",
        )

        # Route by message type — adopters add elif branches here.
        # Extending: copy the clarification_request branch as a template.
        if msg_type == "clarification_request":
            # Thread-handling path — see thread_handling step below.
            await self._handle_clarification_request(envelope)
        elif msg_type == "clarification_reply":
            # Integrate a late-arriving reply non-destructively.
            await self._handle_clarification_reply(envelope)
        else:
            # Unknown type: log and ACK done (don't NACK unknown types by default).
            # Adopters may choose to NACK here for strict domain enforcement.
            _log.info("handle_message: unrecognised type %r — ACK done", msg_type)
            await self.ack(msg_id, ACK_DONE)

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 3 — thread_handling
    # PRIMITIVE COVERAGE: reply_to threading
    # spec/primitives/threads.md, spec/primitives/sequence-numbers.md
    # -----------------------------------------------------------------------

    async def _handle_clarification_request(
        self, envelope: dict[str, Any]
    ) -> None:
        """Handle a clarification_request using the speculative-execute discipline.

        The SOX threading model (spec/primitives/threads.md) says a reply MUST
        set ``reply_to`` = parent ``message_id`` and stay on the same channel.
        We also set ``correlation_id`` so observers can link related messages.

        The speculative-execute discipline: continue under a best-guess while
        sending the question; integrate the reply non-destructively when it
        arrives. We do NOT block waiting for the answer here.
        """
        msg_id: str = str(envelope.get("message_id", ""))
        channel: str = str(envelope.get("channel", ""))
        body: dict[str, Any] = envelope.get("body") or {}

        _log.info(
            "thread_handling: clarification_request on channel=%s msg_id=%s",
            channel,
            msg_id,
        )

        # Build a clarification_reply with reply_to pointing at the parent.
        # Per spec/primitives/threads.md §4 replies stay on the SAME channel,
        # not a sub-channel.
        reply_body: dict[str, Any] = {
            "type": "clarification_reply",
            "subject": body.get("subject", ""),
            "answer": (
                "Acknowledged. Continuing under best-guess assumption while "
                "clarification is processed. Will reconcile when your answer arrives."
            ),
        }

        # Send reply on the same channel with reply_to = parent message_id.
        await self.reply_to_request(envelope, reply_body)

        # Mark the clarification request as done after replying.
        await self.ack(msg_id, ACK_DONE)

    async def reply_to_request(
        self,
        parent: dict[str, Any],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a reply message threaded to *parent*.

        Sets ``reply_to`` = parent's ``message_id`` so the server can build
        the wait-graph for deadlock detection (spec/protocol.md §deadlock).
        Uses the parent's ``correlation_id`` so observers can link the pair.

        Args:
            parent: The parent envelope (from channels__recv).
            body:   The reply body dict.

        Returns:
            The send tool response dict (contains ``message_id``, ``seq``, etc.).
        """
        # Stay on the same channel — replies do not create sub-channels in SOX.
        channel: str = str(parent.get("channel", ""))
        parent_msg_id: str = str(parent.get("message_id", ""))
        # Propagate the original correlation_id so observers can link messages.
        raw_corr = parent.get("correlation_id")
        # Cast to str|None — the wire envelope always carries string or null here.
        correlation_id: str | None = str(raw_corr) if raw_corr is not None else None

        _log.debug(
            "reply_to_request: reply on channel=%s reply_to=%s",
            channel,
            parent_msg_id,
        )

        # Embed reply_to in the body so receivers can link this to the parent.
        # The channels__send tool does not expose reply_to as a parameter in v1;
        # the convention is to carry it in body or use correlation_id for linking.
        # Per spec/protocol.md the wire envelope reply_to is server-populated from
        # correlation_id routing in future; for now we embed it in the body.
        reply_body = dict(body)
        reply_body["_reply_to"] = parent_msg_id

        # Build the send args: only channel, body, and optional correlation_id.
        send_args: dict[str, Any] = {
            "channel": channel,
            "body": reply_body,
        }
        # Only pass correlation_id if the parent had one (avoid null confusion).
        if correlation_id:
            send_args["correlation_id"] = correlation_id

        result = await self._client.call_tool("channels__send", send_args)
        return dict(result.data)

    async def _handle_clarification_reply(
        self, envelope: dict[str, Any]
    ) -> None:
        """Integrate a clarification_reply non-destructively.

        Speculative-execute discipline: we already continued under a best guess.
        When the reply arrives, we log it for reconciliation without undoing work.
        In a real agent, this is where you would compare reply.body.answer
        against your assumption and apply corrections.
        """
        msg_id: str = str(envelope.get("message_id", ""))
        body: dict[str, Any] = envelope.get("body") or {}
        answer: str = str(body.get("answer", ""))

        # Log the answer so adopters can see the reconciliation point.
        _log.info(
            "thread_handling: clarification_reply integrated; "
            "reply_to=%s answer=%r",
            envelope.get("reply_to"),
            answer[:80],
        )

        # ACK done — the reply has been fully processed.
        await self.ack(msg_id, ACK_DONE)

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 4 — ack_nack
    # PRIMITIVE COVERAGE: channels_ack
    # spec/primitives/ack-nack.md
    # -----------------------------------------------------------------------

    async def ack(
        self,
        message_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        """Issue a channels__ack tool call — the ONLY correct way to ACK.

        CRITICAL: ACK is a TOOL CALL, not a channel message. Never send
        a message with body.type='sox-ack' to a channel. Doing so would
        be the "ACK-as-message" anti-pattern explicitly called out in the
        README. See spec/primitives/ack-nack.md §1 and §5.

        ACK status lifecycle (forward-only state machine):
            pending → received → processing → done
                                           → nack

        Args:
            message_id: The message being acknowledged.
            status:     One of received / processing / done / nack.
            reason:     Optional human-readable explanation (required for nack).
        """
        # Guard: skip ACK for empty message_id (can happen in bootstrap drain).
        if not message_id:
            return

        _log.debug("ack: message_id=%s status=%s", message_id, status)

        # Build the tool call arguments; only include reason when present.
        ack_args: dict[str, Any] = {
            "message_id": message_id,
            "status": status,
        }
        # Include reason for nack (SHOULD per spec/primitives/ack-nack.md §4).
        if reason is not None:
            ack_args["reason"] = reason

        # Call the control-plane tool — this does NOT write to any channel.
        await self._client.call_tool("channels__ack", ack_args)

        # Track pending state: remove when reaching terminal status (done/nack).
        if status in (ACK_RECEIVED, ACK_PROCESSING):
            self._pending.add(message_id)
        elif status in (ACK_DONE, ACK_NACK):
            # Terminal status: remove from pending set (unblocks graceful_stop).
            self._pending.discard(message_id)

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 5 — presence_heartbeat
    # spec/primitives/presence.md
    # -----------------------------------------------------------------------

    async def heartbeat_loop(self, interval: int = DEFAULT_HEARTBEAT_INTERVAL) -> None:
        """Background asyncio task: emit channels__heartbeat every *interval* seconds.

        Spec/primitives/presence.md §3: default interval is 10 seconds.
        Status flips to 'busy' when mid-task (set by main_loop), 'online'
        otherwise. The heartbeat fires unconditionally — it is NOT gated on
        main loop liveness so a slow message does not cause a false 'stale'.
        """
        _log.info("heartbeat_loop: starting (interval=%ds)", interval)
        while not self._stop_event.is_set():
            # Emit the current presence status to the server liveness record.
            try:
                await self._client.call_tool(
                    "channels__heartbeat", {"status": self._presence_status}
                )
                _log.debug("heartbeat_loop: heartbeat(%s) sent", self._presence_status)
            except Exception as exc:
                # Log but do not crash the heartbeat loop on transient errors.
                _log.warning("heartbeat_loop: failed to send heartbeat: %s", exc)

            # Sleep using monotonic-clock semantics (asyncio.sleep is monotonic).
            await asyncio.sleep(interval)

        _log.info("heartbeat_loop: stop event set — exiting")

    async def _set_presence(self, status: str) -> None:
        """Update the in-process presence cache and emit a heartbeat immediately.

        Args:
            status: One of ``online``, ``busy``, or ``offline``.
        """
        # Update the cached status so the next heartbeat_loop tick uses it.
        self._presence_status = status
        try:
            # Emit immediately so the state transition is visible without delay.
            await self._client.call_tool(
                "channels__heartbeat", {"status": status}
            )
        except Exception as exc:
            _log.warning("_set_presence: heartbeat failed: %s", exc)

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 6 — graceful_stop
    # spec/protocol.md §graceful-stop, spec/primitives/presence.md
    # -----------------------------------------------------------------------

    async def graceful_stop(self) -> None:
        """Stop the agent cleanly after all pending messages reach a terminal state.

        Per spec/protocol.md §graceful-stop the agent MUST NOT exit while any
        message is still in received or processing state. Only done/nack are
        terminal. After draining pending: emit heartbeat(offline), unsubscribe,
        then set _stop_event so main_loop and heartbeat_loop exit.
        """
        _log.info(
            "graceful_stop: initiated; %d message(s) still pending",
            len(self._pending),
        )

        # Wait for all in-flight messages to reach terminal status.
        while self._pending:
            _log.info(
                "graceful_stop: waiting for %d pending message(s): %s",
                len(self._pending),
                self._pending,
            )
            # Poll; in a real agent you might use an asyncio.Event here.
            await asyncio.sleep(0.1)

        # Emit offline heartbeat so peers see the state transition immediately.
        _log.info("graceful_stop: all messages settled — emitting heartbeat(offline)")
        await self._client.call_tool(
            "channels__heartbeat", {"status": "offline"}
        )

        # Unsubscribe all patterns to discard the queued-but-unread backlog.
        # This discards pending messages for removed subscriptions (spec §3.4).
        _log.info("graceful_stop: unsubscribing all patterns")
        await self._client.call_tool(
            "channels__unsubscribe",
            {
                "patterns": [
                    "ticket:*",
                    "sox/presence",
                ]
            },
        )

        # Signal the main_loop and heartbeat_loop to exit on the next cycle.
        self._stop_event.set()
        _log.info("graceful_stop: complete")

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 7 — recovery
    # spec/operations/replay.input.schema.json, spec/primitives/sequence-numbers.md
    # -----------------------------------------------------------------------

    async def recover_from_state(self) -> None:
        """Replay missed messages using persisted seq cursors.

        This is the canonical recovery recipe (spec/primitives/sequence-numbers.md §7):
        for every channel in the state file, call replay(since=last_seq) until
        has_more=False, then process each message so the seq cursor advances.

        Call this BEFORE main_loop so no message is ever skipped across restarts.
        """
        # Load the last-known seq for each channel from the state file.
        persisted = self._seq_state.load()
        _log.info(
            "recovery: loaded seq state for %d channel(s): %s",
            len(persisted),
            persisted,
        )

        # Initialise the in-memory cursor from the persisted state.
        self._last_seq = dict(persisted)

        for channel, last_seq in persisted.items():
            _log.info(
                "recovery: replaying channel=%s since seq=%d",
                channel,
                last_seq,
            )
            # Replay in pages until has_more=False.
            has_more = True
            # The backing store uses seq >= since (inclusive), so we start
            # from last_seq + 1 to avoid re-delivering the last seen message.
            since = last_seq + 1
            while has_more:
                # Pass since as the inclusive lower bound for the replay cursor.
                replay_result = await self._client.call_tool(
                    "channels__replay",
                    {"channel": channel, "since": since, "limit": 100},
                )
                replayed: list[dict[str, Any]] = replay_result.data.get(
                    "messages", []
                )
                has_more = bool(replay_result.data.get("has_more", False))

                _log.info(
                    "recovery: channel=%s got %d message(s) has_more=%s",
                    channel,
                    len(replayed),
                    has_more,
                )

                # Process each replayed message through the normal handler.
                for envelope in replayed:
                    await self.handle_message(envelope)
                    # Advance the seq cursor after successful processing.
                    seq = int(envelope.get("seq", 0))
                    if seq:
                        since = seq
                        self._last_seq[channel] = seq
                        # Persist immediately so a crash here does not re-replay.
                        self._seq_state.update(channel, seq)

        _log.info("recovery: complete")

    # -----------------------------------------------------------------------
    # LIFECYCLE STEP 8 — group_lifecycle
    # PRIMITIVE COVERAGE: groups
    # spec/primitives/groups.md §5.1-§5.5
    # -----------------------------------------------------------------------

    async def group_create(self, group_id: str | None = None) -> dict[str, Any]:
        """Create a group and return ``{"group_id": ..., "created_at": ...}``.

        The calling agent is automatically added as the first active member.
        Per spec/primitives/groups.md §5.1, group_id is optional; if omitted
        the server assigns an opaque ID.
        """
        # Only pass group_id if provided — server assigns one otherwise.
        # The returned group_id will be "group/<bare-name>" with the prefix.
        args: dict[str, Any] = {}
        if group_id is not None:
            # Bare name only — the server prepends "group/" automatically.
            args["group_id"] = group_id
        result = await self._client.call_tool("group__create", args)
        # Log so adopters can trace the group lifecycle in action.
        _log.info("group_create: result=%s", result.data)
        return dict(result.data)

    async def group_invite(self, group_id: str, invitee_id: str) -> dict[str, Any]:
        """Invite *invitee_id* to *group_id*. Caller must be an active member.

        Per spec §5.2, the invited agent's status is set to ``invited``;
        they must call group_join() to become ``active``.
        """
        # The server verifies the caller is active — non-members get an error.
        result = await self._client.call_tool(
            "group__invite", {"group_id": group_id, "agent_id": invitee_id}
        )
        # Result contains: {"invited": True, "agent_id": invitee_id, "invited_at": float}
        _log.info("group_invite: %s → %s result=%s", self._agent_id, invitee_id, result.data)
        return dict(result.data)

    async def group_join(self, group_id: str) -> dict[str, Any]:
        """Accept an invitation and transition to ``active`` membership.

        Per spec §5.3, this transitions the calling agent from invited → active.
        After joining, the agent can send and recv on the group channel.
        """
        # group_join transitions invited → active; the store also adds the
        # group channel to the agent's subscription list automatically.
        result = await self._client.call_tool(
            "group__join", {"group_id": group_id}
        )
        # Result contains: {"joined": True, "group_id": str, "member_count": int}
        _log.info("group_join: %s joined %s result=%s", self._agent_id, group_id, result.data)
        return dict(result.data)

    async def group_leave(self, group_id: str) -> dict[str, Any]:
        """Leave *group_id*. The server removes the agent from the membership table.

        Per spec §5.4, after leaving the agent can no longer send/recv on
        the group channel (server enforces GROUP_MEMBERSHIP_REQUIRED).
        """
        # After leaving, the group channel is removed from the agent's subscriptions.
        result = await self._client.call_tool(
            "group__leave", {"group_id": group_id}
        )
        # Result contains: {"left": True, "group_id": str, "left_at": float}
        _log.info("group_leave: %s left %s result=%s", self._agent_id, group_id, result.data)
        return dict(result.data)

    async def group_list_members(self, group_id: str) -> list[dict[str, Any]]:
        """Return the membership list for *group_id*. Caller must be active.

        Per spec §5.5, returns a list of ``{agent_id, status, joined_at}``.
        Used after invite+join to verify the expected membership.
        """
        # The server enforces that only active members can query membership.
        result = await self._client.call_tool(
            "group__list_members", {"group_id": group_id}
        )
        # Extract the members list from the result envelope.
        members: list[dict[str, Any]] = result.data.get("members", [])
        _log.info(
            "group_list_members: group=%s member_count=%d",
            group_id,
            len(members),
        )
        return members

    # -----------------------------------------------------------------------
    # TOP-LEVEL COMPOSITION — run()
    # -----------------------------------------------------------------------

    async def run(self, *, once: bool = False) -> None:
        """Compose the full lifecycle: bootstrap → recover → main_loop + heartbeat.

        This is the entry point called by cli.py. In ``--once`` mode we run
        exactly one drain cycle and exit; useful for run_standalone.sh and CI.

        Args:
            once: If True, run a single drain cycle then stop cleanly.
        """
        # Install SIGTERM handler so container orchestrators trigger graceful stop.
        # The lambda schedules graceful_stop as a new task so the signal handler
        # (which runs synchronously) does not need to await the coroutine directly.
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(
            signal.SIGTERM,
            lambda: asyncio.create_task(self.graceful_stop()),
        )

        # Step 1: Bootstrap — version check, subscribe, first heartbeat, initial drain.
        await self.bootstrap()

        # Step 2: Recovery — replay any messages missed since last known seq cursor.
        # This must happen AFTER bootstrap so subscriptions are live before replay.
        await self.recover_from_state()

        if once:
            # One-shot mode: drain once, process, then stop gracefully.
            # Used by run_standalone.sh and CI to verify the agent boots correctly.
            _log.info("run: --once mode — single drain cycle")
            recv_result = await self._client.call_tool("channels__recv", {})
            messages: list[dict[str, Any]] = recv_result.data.get("messages", [])
            # Process each message through the normal ACK lifecycle.
            for envelope in messages:
                msg_id: str = str(envelope.get("message_id", ""))
                # ACK received before handle_message (spec: ack immediately on recv).
                await self.ack(msg_id, ACK_RECEIVED)
                await self.handle_message(envelope)
                # Advance the per-channel seq cursor after successful processing.
                channel: str = str(envelope.get("channel", ""))
                seq: int = int(envelope.get("seq", 0))
                if channel and seq:
                    # Persist the cursor so recovery starts from here on next run.
                    self._seq_state.update(channel, seq)
            # Graceful stop after the single cycle — emits offline heartbeat.
            await self.graceful_stop()
            return

        # Normal mode: start heartbeat background task, then enter main loop.
        # The heartbeat task is independent so slow messages don't miss a beat.
        heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        try:
            # main_loop runs until _stop_event is set by graceful_stop or SIGTERM.
            await self.main_loop()
        finally:
            # Always cancel the heartbeat task when main_loop exits, even on error.
            heartbeat_task.cancel()
            try:
                # Await the cancellation so asyncio does not log spurious warnings.
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        _log.info("run: agent exiting cleanly")
