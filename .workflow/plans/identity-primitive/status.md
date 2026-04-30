---
slug: identity-primitive
state: initialized
bucket: protocol+implementation
stream: B
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: critical
unblocks: [hooks-middleware]
depends_on: []
---

# Engagement: identity-primitive

## Objective
Resolve the credential primitive question (shared secret vs. asymmetric keypair vs. server-issued JWT) and ship a minimum-viable verified-identity layer so `agent_id` is no longer self-asserted.

## Acceptance criteria
- [ ] ADR at `docs/adr/0002-agent-identity-primitive.md` recording the decision and rationale
- [ ] Spec section `spec/ports/identity.md` defining the protocol-level *guarantee* (verified sender, no impersonation) without mandating a specific credential format
- [ ] Reference implementation: per-agent credential registry; `send()` and all mutating ops reject if credential does not match claimed `agent_id`
- [ ] Identity check runs as the first middleware — unverified callers rejected before backing-store access
- [ ] Audit log for identity failures (timestamp, claimed agent_id, operation, reason)
- [ ] Test coverage: identity-failure paths, credential mismatch, missing credential, expired credential (if applicable)
- [ ] Migration story for existing agents that have no credentials — explicit one-line config change, documented

## Inputs
- TODO.md §1 (top priority section, already detailed)
- Patent-landscape finding for any constraint (Apache 2.0 patent grant implications for identity tech)

## Outputs
- ADR
- Spec section
- Code in `packages/python/src/sox_protocol/core/identity/`
- Tests in `packages/python/tests/identity/`

## Suggested executor
`architect-reviewer` for ADR; `backend-developer` or `python-pro` for implementation.

## State transitions
- 2026-04-29 initialized — workflow-architect
