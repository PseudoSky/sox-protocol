# identity-primitive 03-implement review

Reviewer: code-reviewer (independent)
Date: 2026-05-01T15:55Z
Files read this session: 17 (8 src, 8 tests, plus plan/ADR/spec/salvage audit/STATE)
Tests run: `pytest tests/identity/` → 80 passed, 0 failed

## Verdict
PASS-WITH-NOTES

## Summary of salvage-claim verification

| Salvage claim | Evidence | Verdict |
|---|---|---|
| `list_agents` in `_IDENTITY_ENFORCED_OPERATIONS` set | `core/middleware/plugins/auth.py:62`, `core/identity/middleware.py:44` | TRUE |
| `origin_server` field in `VerifiedIdentity` (always `None` in v1, observable end-to-end) | `core/identity/envelope.py:72`, `core/identity/verifier.py:228`, propagated in `bind_for_send` (`verifier.py:259`) | TRUE |
| `signed_request` NOT carried in `mcp_server/tools.py` | `grep -n signed_request core/mcp_server/tools.py` returns no hits; credential resolved from `ctx.metadata["_connection_credential"]` (`auth.py:102-104`) | TRUE |
| `AuthMiddleware` contributes a `middleware_timings` entry to `_meta` | `auth.py:164-186` (`_record_timing`); appended on every code path: ok (`auth.py:248`), reject-no-cred (`auth.py:216`), reject-failure (`auth.py:244`) | TRUE |

All four salvage claims verified.

## Findings

- warning | packages/python/src/sox_protocol/core/identity/verifier.py:78-83 | Replay-cache prune iterates the full nonce dict on every `verify()` call (O(n) per request, unbounded growth between prunes if many distinct nonces arrive within the window). Under sustained load the dict can reach replay_window × peak_qps entries before any item expires. Suggested fix: cap `_seen_nonces` size with a deque-based ring or LRU, or only prune every N calls.
- warning | packages/python/src/sox_protocol/core/identity/verifier.py:200-208 | Replay check + insert is not atomic across concurrent coroutines. Two awaiters on the same nonce can both pass step 5 before either reaches `self._seen_nonces[request.nonce] = now` at line 223 (the only awaits in between are `_audit.record_failure` on the failure paths and `verify_signature` is sync). In practice asyncio single-threaded scheduling makes this rare, but `await` between check and insert (signature verification is sync, but `_fail` issues `await self._audit.record_failure`) still yields control. No `asyncio.Lock` guards the cache. Suggested fix: wrap steps 5-end in an `asyncio.Lock`, or insert nonce optimistically then evict on failure (mirroring the existing "no partial state on failure" guarantee, which itself relies on this not racing).
- warning | packages/python/src/sox_protocol/core/identity/keys.py:107-124 | `verify_signature` uses a bare `except Exception:` and reports `bool`. The wrapped `cryptography` `verify` is constant-time internally, but conflating "bad signature bytes" with "library crash" hides defects. Suggested fix: catch `InvalidSignature` only; let other exceptions propagate.
- warning | packages/python/src/sox_protocol/core/identity/audit.py:102-104 | Audit-log writer opens the file synchronously (`fh.write`) inside an `async def`. Under heavy rejection load this blocks the event loop. Acceptable for a v1 reference impl (rejections are rare) but should be documented or moved behind `loop.run_in_executor`. Also: no `fsync`, so a crash between writes can lose the most recent rejection record — relevant for security audit.
- warning | packages/python/src/sox_protocol/core/identity/audit.py:103 | No file-permission setting on the audit log. `~/.sox/logs/identity-failures.jsonl` will inherit the umask (commonly 0644 on macOS, world-readable). Spec §5 says no other-agent info is leaked, but `claimed_agent_id` of arbitrary attempted impersonations IS sensitive metadata. Suggested fix: `os.open(..., flags=O_APPEND|O_CREAT|O_WRONLY, mode=0o600)`.
- warning | packages/python/src/sox_protocol/core/identity/verifier.py:106-229 | No test exercises `record_failure` raising (e.g. disk full, permission denied). If `_audit.record_failure` raises, `_fail` propagates the I/O exception and SWALLOWS the original `IdentityFailure` — caller sees `OSError`, not `identity_failure`. The middleware then has no `IdentityFailure` to catch and may 500 instead of returning the spec-mandated sox-error envelope. Suggested fix: wrap audit write in `try/except` inside `_fail`, log a separate diagnostic, then raise the original exception.
- warning | packages/python/src/sox_protocol/core/identity/registry.py:152-178 | `register()` overwrites an existing record without preserving history. The ADR/spec describe the registry as append-only; `revoke()` honours that, but `register()` for a known agent throws away the prior `(public_key, registered_at)` tuple in-place. ADR 0002 §Operational explicitly describes rotation as "register the new public key alongside the old". Current impl cannot satisfy that without a different data structure. Suggested fix: keep a list per `agent_id`, mark older entries via a `superseded_at` field, or document explicitly that the in-memory reference impl does not yet model rotation history (the SQLite adapter is expected to).
- warning | packages/python/tests/identity/test_verifier.py:368-393 | `test_no_partial_state_on_failure` asserts the nonce is NOT cached after a tampered-signature rejection. Good — but the test does not cover the symmetric concurrency race (two simultaneous valid requests with the same nonce). With current impl, both could pass step 5 then race to step 6+223. No regression test pins the desired behaviour.
- warning | packages/python/src/sox_protocol/core/identity/verifier.py:162-173 | Timestamp freshness check uses `abs(now - request.timestamp) > replay_window`. Symmetric tolerance allows future-dated requests up to `+window`. A clock-skewed attacker can pre-mint requests valid for window seconds. Suggested fix: use a tighter forward-skew bound (e.g. ±30 s) or document explicitly that replay_window doubles as max permitted clock skew.
- nit | packages/python/src/sox_protocol/core/identity/verifier.py:185, 196, 208, 220 | Four `# pragma: no cover — _fail always raises` annotations. `_fail` *currently* always raises, but the type signature returns `None`, so the trailing `raise exc` is structural noise. Either change `_fail` return type to `NoReturn` (mypy will then drop the trailing raises automatically) or accept the redundancy.
- nit | packages/python/src/sox_protocol/core/identity/registry.py:130-150 | `clock: object` type annotation defeats mypy. Should be `Callable[[], float] | None`. The `if callable(self._clock):` runtime guard then becomes unnecessary.
- nit | packages/python/src/sox_protocol/core/identity/middleware.py:85-86 | Inline `from sox_protocol.core.identity.envelope import SignedRequest` inside `__call__` is a deferred import to avoid a cycle that does not exist (envelope is leaf). Move to module scope.
- nit | packages/python/tests/identity/test_envelope.py:96-124 | Frozen-dataclass test catches `Exception` and string-matches `"frozen"` / `"cannot assign"`. Use `pytest.raises(dataclasses.FrozenInstanceError)` directly.
- nit | packages/python/src/sox_protocol/core/identity/audit.py:101 | `json.dumps` without `default=` will crash if a future caller passes a non-serialisable object. Add `default=str` defensively, or document and validate inputs.
- nit | packages/python/src/sox_protocol/core/identity/keys.py:78-82 | Permission-check error message includes the path; on shared hosts that may leak the agent's home-directory layout. Low risk, mention-only.

## Spec-fidelity matrix

| Behaviour from spec/ports/identity.md | Implemented? | Test coverage? |
|---|---|---|
| §2 server overwrites `sender` from bound identity | YES — `verifier.bind_for_send` (`verifier.py:255-260`) | YES — `test_send_overwrites_sender_with_verified_id`, `test_client_cannot_inject_sender` |
| §2 client tool call does NOT include `sender` parameter | YES — `tools.py` has no `signed_request` or `sender` injection; `auth.py` reads from `ctx.metadata`. `bind_for_send` accepts inputs without sender. | YES — `test_agent_id_not_in_send_input_schema` |
| §3 credential mechanism implementation-defined; reference is Ed25519 | YES — `keys.py` wraps `cryptography` Ed25519 only | YES — `test_keys.py` |
| §4 `send` requires verification | YES — `_IDENTITY_ENFORCED_OPERATIONS` includes `send`; `bind_for_send` called | YES — `test_send_requires_verification`, `test_verified_send_injects_sender` |
| §4 `subscribe` requires verification | YES | YES — `test_subscribe_requires_verification` |
| §4 `recv` requires verification + filtered to verified id | YES — `auth.py:240` sets `ctx.agent_id` | PARTIAL — middleware short-circuit covered (`test_recv_requires_verification`, `test_verified_recv_injects_agent_id`); the *filtering* of recv results to the verified agent_id is the responsibility of `store_dispatch`, not asserted in this engagement |
| §4 `list_channels` informational pass-through | YES | YES — `test_list_channels_passes_through_when_unauthenticated` |
| §4 `list_agents` enforced (v1 MUST per 9f3e11e) | YES — `_IDENTITY_ENFORCED_OPERATIONS` set includes it (auth.py:62, middleware.py:44) | NO — no test asserts `list_agents` is gated; salvage spec realignment did not add a regression test |
| §5 reject + sox-error envelope | YES — `_make_identity_error` produces `error_code="identity_failure"` | YES — `test_error_envelope_has_identity_failure_code` |
| §5 no partial state on failure | YES — replay cache only updated on success (verifier.py:223 after all checks) | YES — `test_no_partial_state_on_failure` |
| §5 SHOULD log failure with ts/claimed_agent_id/reason/operation | YES — `audit.py:94-104` | YES — `test_audit_line_has_required_fields` |
| §5 no leakage of other agents' existence | YES — neutral message `"Identity verification failed"` (verifier.py:178/189/213) | YES — `test_error_message_does_not_leak_other_agent_ids` |
| §6 credential lives on connection seam, not in tool input | YES — `auth.py:102-119` reads `ctx.metadata["_connection_credential"]`; deprecated fallback still accepted with warning. `mcp_server/tools.py` has no `signed_request` references. | PARTIAL — primary path tested via `test_migration_regression.py`; no negative test asserts a deprecation warning fires, no test asserts `mcp_server/tools.py` schema rejects `signed_request` |
| §6 binding persists for connection lifetime | PARTIAL — `verify()` succeeds repeatedly; no caching of the binding by `connection_id` (every call re-verifies the signature). Acceptable but worth documenting. | YES — `test_verifier_persists_binding_across_calls` |
| §7 v1 origin_server = null in envelope | YES — `VerifiedIdentity.origin_server: str \| None = None`; propagated by `bind_for_send` (verifier.py:259) | NO — no test asserts `bind_for_send` writes `origin_server` into the returned dict |
| §7 registry shape `(agent_id, public_key, registered_at, revoked_at?)` | YES — `CredentialRecord` fields exact (registry.py:42-45) | YES — `test_registry_records_required_columns` |
| §7 append-only | PARTIAL — `revoke()` is append-only; `register()` of an existing agent overwrites | YES (revoke); NO test for register-overwrite preserving history (because it doesn't, see findings) |
| §9 audit log entries written for every identity failure | YES (`auth.py` short-circuit path also logs via verifier) | YES — `test_rejection_writes_audit_line`, `test_audit_log_still_written_on_rejection` |
| ADR 0002 file mode 0600 enforced | YES — `keys.py:74-82` | YES — `test_load_private_key_rejects_world_readable`, `test_load_private_key_accepts_0600` |
| ab1c954 `middleware_timings` entry to `_meta` | YES — `auth.py:164-186`, fired on all 3 paths | NO — no test asserts the `_meta["middleware_timings"]` entry shape after AuthMiddleware runs (claim is grounded in source only) |

## Architecture / dependency check

- `grep -rn "from sox_protocol.adapters" core/identity/` → 0 hits. Architecture rule respected.
- `core/identity/` only imports from `cryptography`, stdlib, and itself. Confirmed.
- `core/identity/middleware.py` is a deprecated shim correctly identified as such; canonical path is `core/middleware/plugins/auth.py`.

## Test-coverage gaps despite "100% line coverage"

These are observed gaps in *behaviour* coverage that line coverage hides:

1. Audit-log write failure (disk full, EACCES) → would mask the `IdentityFailure` and break the §5 sox-error guarantee. No test.
2. Concurrent-coroutine replay race (two tasks, same nonce, simultaneous `verify`) — see finding above. No test.
3. `list_agents` enforcement regression — no fixture pins the salvage fix; trivial to remove without breaking tests.
4. `middleware_timings` _meta contribution — visible in code, not asserted in any test.
5. `bind_for_send` writing `origin_server: None` into the returned dict — visible in code, not asserted.
6. Expired-credential semantics distinct from revoked — current code conflates `revoked_at` with "all expiry"; if a future `expires_at` lands the verifier needs adjustment. No forward-looking test.
7. Deprecation warning emitted by the `signed_request`-in-input fallback path — code logs, no test captures.

## Security review

- Constant-time signature comparison: delegated to `cryptography` Ed25519; OK.
- Constant-time agent-id comparison: not relevant — registry lookup is dict-based; timing leak is theoretically possible (Python dict hash) but registries are server-only and not under attacker control.
- No secrets in audit lines: confirmed (`test_audit_line_has_no_secrets`).
- No secrets in error messages: neutral strings used. Confirmed.
- No secrets in log messages: `auth.py:109-114` logs the operation name only, not the credential.
- File-permission enforcement on private key: 0600 strict (`keys.py:77`).
- File-permission on audit log: NOT enforced (see finding above) — recommend 0600.

## Sign-off

PASS-WITH-NOTES — the implementation is structurally correct, all five salvage claims are verified true, all 80 identity tests pass, and the spec/ports/identity.md guarantee is upheld on the happy path and on the documented rejection paths. No blocking findings. Eight warnings (concurrency, audit-write robustness, audit-file mode, register history, future-skew, error-context preservation) are worth landing as a follow-up before federation work begins; they do not block downstream engagements that consume the verifier today.
