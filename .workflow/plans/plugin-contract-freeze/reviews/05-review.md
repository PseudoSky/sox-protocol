# plugin-contract-freeze 05-review — architectural review

Reviewer: architect-reviewer
Date: 2026-05-01

## Verdict

**PASS-WITH-NOTES**

The four artifacts cohere into a defensible v1 plugin contract. Cross-language portability is genuinely achieved at the manifest level. One real schema bug (the `oneOf` rejects plain version pins despite the spec/description claiming they are accepted), several lesser inconsistencies, and a handful of forward-compat traps are surfaced below. None of them block the downstream engagements (`plugin-discovery-py`, `reference-plugins`, `plugin-architecture-ts`) from starting; all are appropriate for a B2 amendment under the explicit "candidate contract" framing of §11 of the plugin-contract spec.

## Summary

The B1 freeze hits its central goal: a TS implementation can consume these four artifacts and produce isomorphic plugin behaviour to the Python reference, with no Python-only constructs leaking into the language-neutral document. The schema validates against draft-07 and all three example fixtures round-trip cleanly. The capability orthogonality if/then constraint correctly catches the documented conflict case (`observe_only:true + may_short_circuit:true`). The most important finding is a `oneOf` failure that contradicts both the schema's own description and §2.3 of the versioning spec — easily fixable by switching to `anyOf` or by removing the dual-overlap zone.

## Findings

| Severity | File:section | Issue | Suggested fix |
|---|---|---|---|
| blocking | `spec/schemas/sox-plugin.schema.json` lines 65-74 (`spec.protocol_version.oneOf`) | The two patterns both match plain version forms (`1.0.0`, `1.0`, `1`, `1.x`). JSON Schema `oneOf` requires **exactly one** branch to match; therefore these plain forms are REJECTED. This contradicts the field's own description ("A plain version pin ('1.0.0') is accepted as an exact match"), the schema's own `examples` array (which lists both `"1.0.0"` and `"1.x"`), and `06-versioning.md` §2.3 ("Plain version with no operator ... MUST treat it as an exact-match requirement"). Verified empirically: `jsonschema.Draft7Validator(schema).iter_errors({...protocol_version: "1.0.0"})` → fails. | Replace `oneOf` with `anyOf`. The two forms are documented as overlapping aliases, not mutually exclusive parses; `anyOf` matches the spec's intent. Alternatively, collapse to a single relaxed pattern that covers both and let the host's parser do the disambiguation. |
| warning | `spec/schemas/sox-plugin.schema.json` line 38 (`metadata.version` regex) | Pattern requires three segments (`^[0-9]+\.[0-9]+\.[0-9]+`), but PEP 440 allows shorter forms (`1.0`, `1`) for content versions. SemVer 2.0.0 also requires three segments, so this is technically correct, but a contrast with `protocol_version` which accepts `1`/`1.0` adds avoidable surprise. | Either accept that `metadata.version` is strict-SemVer (current behaviour, correct per the field description "Full SemVer 2.0.0 format") and document the asymmetry, or relax to match. Status quo is acceptable; nit-grade. |
| warning | `spec/ports/middleware/03-plugin-contract.md` §2.4 vs `spec/schemas/sox-plugin.schema.json` `requires` definition | §2.4 introduces a "version-range matching in `requires`" v1.x extension and shows examples like `rate_limit.backend: ">=1.0"`, but the schema's `requires` is `array<string>` (e.g. `"identity.registry"`), with no syntax for embedded version ranges. The provider example uses `{"rate_limit.backend": ">=1.0"}` in `plugin_capabilities` (correctly an object) but a consumer's `requires` would have to be `"rate_limit.backend"` (string only) — there is no way to express the requirement-side version constraint in v1. | Either explicitly state in §2.4 that v1 `requires` is exact-match-only on the capability key, with version constraints deferred entirely to v1.x and a v1.x manifest schema bump; or reserve a delimiter syntax now (e.g. `"rate_limit.backend@>=1.0"`) so v1.x can land without a schema change. The current language hints at a feature that the schema cannot represent. |
| warning | `spec/ports/middleware/03-plugin-contract.md` §6.2 error taxonomy ("seven error codes are the complete set") vs ADR 0004 §4 | ADR 0004 lists six codes (`plugin_not_allowed`, `plugin_not_found`, `plugin_manifest_invalid`, `plugin_protocol_version_mismatch`, `plugin_capability_conflict`, `plugin_ordering_cycle`); the spec lists seven (adds `plugin_requirement_unmet`). §3.3 of the spec also introduces an additional code `plugin_startup_failed` not present in the §6.2 table. Internal inconsistency. | Reconcile to a single closed set across ADR §4 and spec §6.2. Add `plugin_requirement_unmet` to ADR §4 and add `plugin_startup_failed` to the §6.2 table (or drop it from §3.3). |
| warning | `spec/ports/middleware/06-versioning.md` §2.4 normalization table | Lists three pre-release equivalence pairs but stops short of `1.0.0.dev1` (PEP 440) ↔ no clean npm form. Plugin authors using PEP 440 dev releases will hit a parsing-vs-normalization gap. | Either add a row "PEP 440 `.devN` is not normalizable to npm form; hosts MUST reject `.devN` in `protocol_version` for v1" or extend the normalization rule with a documented npm spelling. |
| warning | `spec/ports/middleware/03-plugin-contract.md` §2.2.2 hook `applies_to.phase` | Section 2.2.2 says "The classification is declared in the plugin manifest's `applies_to` phase field (v1.x; in v1.0, all hooks are registered as pre-hooks unless the host's API provides explicit ordering)." But the schema's `applies_to` has no `phase` property, and `additionalProperties: false` on `applies_to` would reject one if added by an author following the prose. | Either add `phase` to the schema as an optional enum reserved for v1.x (with `additionalProperties: false`-compatible declaration), or remove the v1.x forward reference from §2.2.2. The current language tells authors they can write a field that the schema will reject. |
| warning | `spec/ports/middleware/03-plugin-contract.md` §10.1 reference impl path | Cites `packages/python/src/sox_protocol/core/middleware/` as the reference. A normative document referencing a still-evolving implementation path commits the spec to that directory layout. | Either soft-link via a documented stable URL, or qualify with "see the SOX reference impl tree (path subject to repo restructure)." |
| warning | `spec/schemas/sox-plugin.schema.json` `metadata.id` regex `^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$` | First segment forbids hyphens (`[a-z][a-z0-9]*`) but subsequent segments allow them (`[a-z][a-z0-9-]*`). The provider example uses `com.myco.sox-provider-redis-pool` — second/third segments contain hyphens, which is fine. But a perfectly reasonable id like `my-org.example.plugin` would be rejected because of the first-segment restriction. The reverse-DNS convention does not normally forbid hyphens in TLD-shaped first segments. | Allow hyphens in the first segment too (`^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$`), or document this restriction explicitly in the description. |
| nit | `docs/adr/0004-plugin-architecture.md` line 8 | Status appears twice ("Status: Accepted — 2026-05-01" at line 3 and "Status: Accepted (2026-05-01)" at line 8). | Remove one. |
| nit | `spec/ports/middleware/03-plugin-contract.md` §8.1 | `started_at` / `finished_at` typed as `float` (Unix epoch seconds). TypeScript `Date.now()` returns integer milliseconds; Python `time.time()` returns float seconds. The unit (seconds vs ms) is normative; the type (float vs int) is implementation. Calling out only the Python-shaped form invites TS implementations to silently emit ms. | Specify "Unix epoch seconds as a JSON number (integer or fractional, MUST be seconds, not milliseconds)." |
| nit | `spec/ports/middleware/03-plugin-contract.md` §3.4 default-mode rule | "When `SOX_HOOK_FAILURE_MODE` is absent, the host MUST default to `alarm`." But the table immediately above lists `alarm` as default for production and `raise` for CI/dev. The MUST default to `alarm` regardless of `SOX_ENV` contradicts the table (which would default to `raise` if `SOX_ENV=development`). | Clarify the precedence: either `SOX_HOOK_FAILURE_MODE` overrides `SOX_ENV`-derived default, or the table's `SOX_ENV`-derived defaults apply only when `SOX_HOOK_FAILURE_MODE` is absent. The latter is implied; just spell it out. |
| nit | `spec/schemas/sox-plugin.schema.json` `applies_to.phase` absence | See §2.2.2 finding above — same issue from the schema side. | Same fix. |

## Cross-language portability check

**Q1 — Python-only constructs in the manifest?** None found. `metadata.id` is reverse-DNS, not a Python module path. Entry-point hints are explicitly out of the manifest body (ADR §2, schema description, spec §5). The `pyproject.toml` reference is correctly scoped to the Python discovery side. PASS.

**Q2 — Dual-form `protocol_version` parses unambiguously on both runtimes?** Mixed. PEP 440 `~=1.0` parses correctly on Python via `packaging.specifiers.SpecifierSet`; on Node, `node-semver` does not natively understand `~=` and would need a translation layer or a documented "PEP 440 input → npm equivalent" mapping. The versioning spec §2.2 acknowledges this ("Hosts MAY canonicalize internally") but does not specify the translation. The PEP 440 `~=1.0` operator means `>=1.0,<2` (compatible release); npm's `~1.0` means `>=1.0.0,<1.1.0` (different semantics). A TS implementation that treats `~=` as an unknown operator vs. one that maps it correctly will produce divergent compatibility decisions. RECOMMENDATION: add an explicit normative translation table for `~=` → npm equivalent in §2.4 of the versioning spec. The existing pre-release normalization table is the right shape; extend it.

**Q3 — `kind: provider` lifecycle in TS?** Both Python and TS have async functions (`async def`, `async function`); both have a clean factory pattern. The contract `() -> Resource` plus optional `on_startup`/`on_shutdown` is language-neutral. PASS.

**Q4 — Failure-semantics-per-kind language-neutral?** Mostly. §3.1 references `ShortCircuitResponse` (a class), §3.2 references `ValidationError` (a class). Class names are appropriate for a normative contract — implementations need a stable name to match against — but the spec does not specify whether these are exception classes (Python idiom) or sentinel return values (which would also be Node-idiomatic). The reference implementation makes them exceptions; the spec should be explicit so a TS impl knows whether to `throw` or `return`. RECOMMENDATION: §3.1/§3.2 should state "implementations MUST raise these as language-native exceptions." This is a warning-grade portability concern.

**Q5 — Failure mode env-var canonicalization across languages?** §7.2 of the spec gives a fully deterministic algorithm (replace `.` and `-` with `_`, uppercase, prefix `SOX_PLUGIN_`). Both Python `os.environ` and Node `process.env` consume this identically. PASS.

**Q6 — Protocol-version pre-release parse-equivalence?** `1.0.0a1` (PEP 440) ↔ `1.0.0-alpha.1` (npm) is normalized in §2.4. The schema's `oneOf` correctly directs `1.0.0a1` to the PEP 440 branch (npm pattern rejects it because of the missing `-`) and `1.0.0-alpha.1` to the npm branch (PEP 440 pattern rejects the embedded `-`). PASS at the schema level. PASS-with-caveat at the runtime level: hosts must implement the §2.4 normalization equivalence themselves; neither `packaging.specifiers` nor `node-semver` will recognize the other's spelling natively.

## Internal consistency matrix

| Spot-check | Result | Notes |
|---|---|---|
| ADR §1 taxonomy ↔ schema `plugin_kind` enum ↔ spec §2 contract | PASS | All three say `[interceptor, transformer, provider, hook]` and agree on the migration of `guard`. |
| ADR §3 boot-time refusal ↔ versioning §4.1 timing | PASS | "Lazy refusal is forbidden" appears verbatim in both. |
| ADR §4 error taxonomy (six codes) ↔ spec §6.2 (seven codes) ↔ spec §3.3 (`plugin_startup_failed`) | FAIL | See finding warning #4. The table is closed in §6.2 ("seven error codes are the complete set") but the count is inconsistent. |
| Three example YAMLs validate against schema | PASS | All three round-trip via `jsonschema.Draft7Validator`. |
| Capability-conflict if/then catches `observe_only:true + may_short_circuit:true` | PASS | Empirically tested. The variant `observe_only:true + may_short_circuit:false` correctly remains valid. |
| Schema description + spec §2.3 + versioning §2.3 all claim plain `1.0.0` is accepted | FAIL | Schema's `oneOf` rejects it. See blocking finding. |
| ADR §7 env-var canonicalization rule ↔ spec §7.2 | PASS | Algorithm steps match; the worked example `org.example.sox-jwt-auth` → `SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_*` is identical in both. |
| ADR §10 candidate framing ↔ spec §11 candidate note | PASS | Both explicitly state amendments are expected and not a process failure. The spec §11 sentence "A reviewer MUST NOT reject a post-B1 amendment PR on the grounds that 'B1 was already merged.'" is a particularly clean instantiation of NR-4. |

## Completeness vs §7 + v2 deltas

| Item | Where addressed | Notes |
|---|---|---|
| §7.5 risk #1 supply-chain | spec §6 (allowlist) + ADR §4 | `--allow-plugins` + `SOX_ALLOWED_PLUGINS`. Production-mode empty-allowlist behaviour is normative. PASS. |
| §7.5 risk #2 hook-failure default | spec §3.4 + ADR §5 | `alarm` is normative production default; `swallow` is opt-in. PASS — exemplary. |
| §7.5 risk #3 ordering cycles | spec §4.1-§4.2 + ADR §6 | Stable Kahn + lex tie-break + named-cycle error. PASS. |
| §7.5 risk #4 hot-reload deferral | spec §9 + ADR §9 | "MUST NOT cache references to host-provided objects" is the load-bearing rule. PASS. |
| §7.5 risk #5 conformance CI | spec §10.2 + §10.3 + versioning §9 | Five fixture targets in plugin-contract; four in versioning; provider conformance fixture explicitly required per Q6 NR-2. PASS. |
| §7.5 risk #6 sox.yaml descope | spec §7.1 + ADR §7 | env-vars-only for v1; sox.yaml deferred to v1.x. PASS. |
| §7.5 risk #7 pipeline_trace | spec §8 + ADR §8 | Field shape, `correlation_id` frozen-field pattern, OTel deferral. PASS. |
| Q3 critiques | ADR §2 (signing reservation), spec §10.3 (provider conformance) | All three raised in suggestions-v2.md §Q3 are folded in. PASS. |
| Q4 capability flags | spec §2.3, schema if/then | Orthogonality is enforced statically AND at runtime per ADR §1. PASS. |
| Q6 NR-1 env-var canonicalization | spec §7.2 | Normative deterministic algorithm with worked example. PASS. |
| Q6 NR-2 provider conformance | spec §10.3 | Explicitly named for B2. PASS. |
| Q6 NR-3 ordering determinism | spec §4.1 | "Implementations MUST produce identical ordering" is normative. PASS. |
| Q6 NR-4 candidate framing | spec §11 + ADR §10 | Explicitly anti-rejection language. PASS — best-in-class. |

## Forward-compat traps

**Trap 1 — `applies_to.phase` for hooks (warning #6).** Spec §2.2.2 promises a v1.x `phase` field that the v1 schema actively forbids via `additionalProperties: false`. The first plugin author who reads §2.2.2 and tries to declare a `post` hook will hit a schema validation error and assume the spec is wrong. Either reserve the field shape now or remove the v1.x forward reference. This will hit P5 (`reference-plugins`) directly the moment any reference plugin needs a post-hook.

**Trap 2 — `requires` capability-version syntax (warning #3).** A plugin author reading §2.4 will assume they can express `requires: ["rate_limit.backend@>=1.0"]` or similar. The schema accepts it as an opaque string but the spec gives no resolution semantics. The first plugin to ship with a real version-bounded requires will discover the v1 host treats it as a literal string match, silently failing to resolve a provider that declares `rate_limit.backend: ">=1.0"`. This will surface in P5.

**Trap 3 — PEP 440 `~=` semantics on TS hosts (cross-language Q2).** A TS host implementing the dual-form requirement will need to translate PEP 440 specifiers to `node-semver`. The trickiest case is `~=1.0` (compatible-release) which is roughly `>=1.0,<2.0` — different from npm's `~1.0` (`>=1.0,<1.1`). A TS host that maps `~=` to `~` will silently mis-evaluate compatibility. Versioning §2.4 normalizes pre-release markers but stops short of operator translation; that is the gap.

**Trap 4 — Pipeline-trace timestamp unit drift (nit #2).** A TS impl that emits `Date.now()` (ms) instead of seconds will produce trace records that look right but are off by 1000×. Cross-implementation conformance fixtures will catch this in B2; the spec should pre-empt it.

**Trap 5 — `plugin_kind` enum frozen at four values.** The schema enum is closed, which is correct for v1. But spec §2.3 floats the prospect of new kinds via the "flag-set cap is a cultural commitment" wording. If v2 adds a fifth kind, the `apiVersion: sox.dev/v2` boundary will need to ship in lockstep with the schema enum extension. This is fine — it's exactly what the `apiVersion` envelope is for — but it should be documented as the planned evolution path. Currently the ADR/spec are silent on what `apiVersion: sox.dev/v2` means in practice.

## What is missing for P3-P6

- **P3 plugin-spec-polish:** the directory restructure of `spec/ports/middleware.md` → `spec/ports/middleware/` is intentionally out of scope; that engagement also owns the conformance fixtures already named in `03-plugin-contract.md` §10.2 and `06-versioning.md` §9. The `applies_to.phase` reservation (trap 1) and the `requires` version syntax (trap 2) should be picked up here.

- **P4 plugin-discovery-py:** the `register_plugin(name, factory)` programmatic-registration path is mentioned in spec §5 but not detailed. The signature, idempotency rules, and interaction with the allowlist (does in-tree registration also gate on `--allow-plugins`?) need fleshing out. Spec §5 says "still subject to allowlist enforcement" but does not say how an in-tree-registered plugin gets into the allowlist (its id from the manifest? from the registration call?).

- **P5 reference-plugins:** the first reference plugin (`io.sox.schema-strict`) is declared `kind: transformer` in the example. The provider-conformance fixture (§10.3) is required to land alongside or before P5 because no committed reference plugin exercises the provider lifecycle. The blocking `oneOf` schema bug WILL hit P5 if the first reference plugin uses a plain `protocol_version: "1.0.0"`.

- **P6 plugin-architecture-ts:** the cross-language Q2 trap (PEP 440 `~=` translation) is the single most impactful gap. The TS impl should not have to reverse-engineer the PEP 440 → npm mapping; the spec should provide it. Versioning §2.4 is the right home for an operator-translation table.

- **General:** the JSON Schema does not yet have a published `$id` URL that resolves (`https://sox-protocol.dev/spec/schemas/sox-plugin.schema.json`). Plugin authors using AJV with `loadSchema` from the URL will fail. Either ship the schema at that URL or document that the `$id` is a logical identifier and the file path is the source of truth.

## Sign-off

PASS-WITH-NOTES. Twelve findings: one blocking (the `oneOf` schema bug), seven warnings (consistency gaps and forward-compat traps), four nits. None block the engagement transition; the blocking finding is a 5-character schema fix (`oneOf` → `anyOf`) that B2 or a hotfix can land. The candidate-contract framing in spec §11 and ADR §10 was the most pleasant surprise — it explicitly anti-vetoes future amendment PRs in normative language, which is a level of process self-awareness rarely seen in v1 specs.

The B1 freeze is sufficient to unblock `plugin-discovery-py`, `reference-plugins`, and `plugin-architecture-ts` to start in parallel, with the noted findings tracked into B2.
