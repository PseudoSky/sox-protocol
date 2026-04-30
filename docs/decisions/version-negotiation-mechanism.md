# Decision: version-negotiation-mechanism

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q5 (protocol versioning)

## Context
Protocol version negotiation needs a well-defined entry point so clients and servers can detect mismatch before exchanging real traffic. A dedicated `channels__negotiate` tool is explicit but adds a round-trip; embedding `server_version`, `supported_versions`, `min_client_version` in the existing `list_channels` response is zero overhead because that call is already conventional-first. Decision shapes the spec's handshake section and every implementation's startup sequence.

## Decision
**Option B — embed version metadata in the `list_channels` response, and require all servers to include it.** The response gains a top-level `_sox_protocol` block (sibling to channel data) carrying `server_version`, `supported_versions`, `min_client_version`. Clients are required to read it on first call and fail-fast if the intersection with their own supported range is empty. No dedicated negotiation tool is shipped in v1.

## Rationale
The convention of `list_channels` as the first call is already established in the reference implementation; embedding makes negotiation free for every well-behaved client. A dedicated tool adds a round-trip on every session start for a check that almost always succeeds, and it splits a single concern (handshake) across two surfaces. Option C (both) is rejected as premature surface area — the spec should ship one mechanism and add the second only if a real client need emerges. The risk of coupling discovery and negotiation is overstated: `list_channels` is already the de-facto handshake, so the coupling already exists informally; this just makes it explicit. Trade-off accepted: if `list_channels` is ever deprecated or split, the version block must move with the new first-call tool, and that migration must be planned.

## Consequences
- Positive: Zero round-trip cost. Every client that already calls `list_channels` (i.e. all of them) gets version info for free.
- Positive: Single handshake tool, single conformance test for the negotiation behaviour.
- Positive: Misversioned clients fail-fast on their first real call, not silently mid-session.
- Negative: Couples protocol-version metadata to the discovery response — if `list_channels` evolves, the version block constrains the change.
- Negative: Clients that for some reason skip `list_channels` get a default version assumption; spec must define what that default is and warn against skipping.
- Spec impact: `spec/handshake.md` (new, short) defines the `_sox_protocol` block schema. `spec/list-channels.md` declares the block mandatory in every response. `spec/versioning.md` defines version-string format (semver-like) and the intersection rule for `supported_versions` × `min_client_version`. Conformance suite tests (a) block presence, (b) mismatch fail-fast, (c) compatible-range success.

## Open questions for follow-up
- Whether to allow servers to expose `_sox_protocol` on every response (would harmonise with observability-meta-mode default-on posture). Defer.
- Whether feature flags (e.g. `supports_threading: true`) belong in the handshake block or in a separate capabilities surface — defer to post-v1.
- Default-version assumption for clients that skip `list_channels` — likely "latest server version, caveat emptor"; ratify during spec extraction.
