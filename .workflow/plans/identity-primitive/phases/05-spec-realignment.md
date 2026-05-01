---
phase_id: 05-spec-realignment
title: Reconcile shipped identity layer with post-2f3d8f3 spec changes
agent: python-pro
profile: code-with-spec
estimated_effort: 1-2 days
prereqs: [03-implement]
unblocks: [04-review]
parallelizable_with: [hooks-middleware:05-op-coverage]
writes: ["packages/python/src/sox_protocol/core/identity/**", "packages/python/src/sox_protocol/core/middleware/plugins/auth.py", "packages/python/tests/identity/**", "packages/python/tests/middleware/**"]
reads:  ["spec/ports/identity.md", "spec/schemas/message.schema.json", "spec/envelopes/sox-*.schema.json", ".workflow/plans/SALVAGE-AUDIT-2026-04-30.md"]
context_size: medium
---

# 05 — Spec realignment (salvage)

## Inputs

- `spec/ports/identity.md` (ground truth)
- `spec/schemas/message.schema.json` (12-field wire envelope per `3bdafc2`)
- `spec/envelopes/sox-error.schema.json` and `sox-ack.schema.json`, `sox-nack.schema.json`
- `spec/operations/list_agents.input.schema.json` (now v1 MUST per `9f3e11e`)
- `docs/adr/0002-agent-identity-primitive.md`
- `.workflow/plans/SALVAGE-AUDIT-2026-04-30.md`

## Background

Step 2 shipped at commit `f28b858` (76/76, 100% cov). Core guarantee (server overwrites `sender`) and Ed25519 reference impl conform. The spec moved (`9f3e11e`, `3bdafc2`, `ab1c954`) creating 5 drifts to remediate.

## Prompt (verbatim)

```text
Reconcile the shipped identity layer with current spec/. Read SALVAGE-AUDIT-2026-04-30.md for evidence.

DELIVER (5 fixes):

1. Add list_agents to identity enforcement set
   - core/identity/middleware.py: extend _IDENTITY_ENFORCED_OPERATIONS to include "list_agents".
   - Spec §4 says send/subscribe/recv MUST verify; list_agents was added to v1 MUST in commit 9f3e11e — treat it as MUST verify (same as send/recv/subscribe).
   - Add a test that an unauthenticated list_agents returns identity_failure sox-error.

2. Surface origin_server through VerifiedIdentity
   - Extend VerifiedIdentity dataclass with origin_server: Optional[str] = None.
   - In bind_for_send: also inject origin_server into the request envelope per spec §7 12-field wire envelope.
   - For v1, origin_server is always None (no federation yet) — but the field MUST be present in the envelope so envelope §7 v1 contract is observable end-to-end.
   - Update message.schema.json conformance: ensure outbound messages include origin_server: null.

3. Move signed_request off the tool-call dict
   - Spec §6: "agent_id field does NOT appear in any tool call input schema; runtime adapters MUST configure credential in MCP server launch parameters."
   - Currently signed_request is read from request["signed_request"] inside the tool input dict — this VIOLATES §6.
   - Rewire: credential is read from a connection-bound seam (MCP launch param SOX_CREDENTIAL or transport context attribute), NOT from the tool input.
   - Remove signed_request from any input schema if it leaked there.
   - Update the MCP server launch path (core/mcp_server/server.py) to pull credential from launch params and bind it to the connection context, then have the identity middleware read from that context.
   - Reference: stdio transport already has a connection-context concept; extend it.

4. Emit middleware_timings entry from AuthMiddleware
   - Spec ab1c954 pinned _meta shape to {trace_id, middleware_timings, server_node_id}.
   - core/middleware/plugins/auth.py must record an entry in ctx._meta.middleware_timings on each invocation: {"middleware": "auth", "duration_ms": <int>, "verdict": "ok"|"reject"}.
   - Verify pipeline.py is appending these entries to the response _meta block.

5. Reconcile IdentityMiddleware shim vs canonical AuthMiddleware
   - The plan called for an IdentityMiddleware shim; post-Step 2 there is also a canonical core/middleware/plugins/auth.AuthMiddleware referenced by docstrings.
   - Decide canonical path (recommend: AuthMiddleware is the Middleware-port plugin; IdentityMiddleware shim is deprecated).
   - Either delete the shim or document it as a thin alias; update docstrings; update default_chain.py to register the canonical one.

HARD CONSTRAINTS:
- All existing 76 identity tests still pass.
- 100% coverage on core/identity/ and core/middleware/plugins/auth.py.
- mypy --strict clean.
- lint-imports clean.
- ruff clean.
- Audit log behavior unchanged (still writes JSONL; still no secret/public_key leakage).
- Replay-window default unchanged (5 min).

DO NOT:
- Change ADR 0002 (Ed25519 reference impl decision stays).
- Change the §2 core guarantee (server still overwrites sender).
- Add federation logic — origin_server is null in v1, that's the whole point.

EXIT CRITERIA:
- pytest packages/python/tests/identity/ packages/python/tests/middleware/ → all green
- grep -c "list_agents" packages/python/src/sox_protocol/core/identity/middleware.py → ≥1
- grep -c "origin_server" packages/python/src/sox_protocol/core/identity/ → ≥2 (declaration + binding)
- grep -c "signed_request" packages/python/src/sox_protocol/core/mcp_server/tools.py → 0 (must not appear in tool-call surface)
- grep -c "middleware_timings" packages/python/src/sox_protocol/core/middleware/plugins/auth.py → ≥1
- coverage on core/identity/ and core/middleware/plugins/auth.py → 100%

ON COMPLETION:
- Mark 05-spec-realignment DONE in STATE.md
- Promote 04-review to READY
- Commit with trailer: feat(identity-primitive:05-spec-realignment)
```

## Acceptance criteria (machine-checkable)

See EXIT CRITERIA in the prompt block above.
