# Decision: groups-model

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q4

## Context
Groups are part of the core pitch ("group chat for agents — groups are first-class"). They can be modeled as managed channels (server creates and owns the channel, enforces membership on send/subscribe, all delivery via the existing channel path) or as a first-class entity with its own table, verbs, and delivery semantics. This decision depends on dm-semantics (Q1): if DMs are channels-with-convention, groups should follow the same model to produce the unified "addressable destinations" abstraction the vision doc calls for.

## Decision
**Option A — Group = managed channel.** A group is a channel with name prefix `group/<group-id>` whose membership is maintained by the server in a separate membership table. The server enforces, on every `send` and `subscribe`, that the calling agent is a current member. All message delivery flows through the existing channel path — same envelope, same `seq`, same threading, same replay, same enforcer. Group lifecycle (create, add member, remove member, archive) is exposed via dedicated tools (`groups__create`, `groups__add_member`, etc.) that mutate the membership table; messaging itself uses the standard `channels__send` / `channels__recv` verbs against the group's channel name.

## Rationale
Together with Q1, this produces the unifying "addressable destinations" model the vision doc explicitly asks for: every message goes to a channel; some channels are open (regular `<name>`), some are pairwise (`dm/<sorted-pair>`), some are membership-managed (`group/<group-id>`). One delivery path, one envelope, one conformance test surface. Option B (separate entity with its own delivery path) would double the cross-cutting work for replay, threading, ack tracking, audit, federation-awareness, and conformance — and produce two pitches ("agent-to-agent" and "agent-to-group") that need separate explanation. Trade-off accepted: groups can't have radically different delivery semantics from channels (e.g. fan-out limits, per-recipient ack matrices) without extending the channel model itself; that's the right place for those features anyway.

## Consequences
- Positive: Single delivery path. Conformance suite covers groups for free.
- Positive: "Group chat for agents" pitch maps to one mental model: addressable destinations with different membership policies.
- Positive: Threading inside a group is just channel threading. DMs inside a group context (e.g. "reply privately to one member") are just opening a `dm/` channel.
- Negative: Group-specific features (member roles, admin/owner distinction, per-member mute) live in the membership-table layer, not in the message layer. Must be designed there or via middleware hooks.
- Negative: `group/` becomes a second reserved name prefix alongside `dm/`. Reserved-prefix rule in the spec must be defined once and used by both.
- Spec impact: `spec/groups.md` defines the `group/<group-id>` convention, the membership-table contract, and the lifecycle verbs. `spec/channels.md` "reserved name prefixes" section (introduced by Q1) extends to cover `group/`. `ports/store.md` adds the membership-table contract. No new envelope fields or message types.

## Open questions for follow-up
- Whether `group-id` is human-chosen (`group/eng-team`) or server-assigned opaque (`group/01HXYZ...`) — recommend allowing both with a creation-time choice; pin during spec extraction.
- Whether "broadcast to all subscribers without a membership list" (open channel) and "broadcast to membership list" (group) need to converge into a single subscription model later — defer to addressable-destinations design pass.
- Member roles (owner, admin, member, observer) — out of scope for v1 spec; can be a middleware/hook layer concern.
