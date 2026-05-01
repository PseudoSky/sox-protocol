# Workflow optimization suggestions — plugin-architecture umbrella (v2, second pass)

Based on: `.workflow/plans/plugin-architecture/analysis.md` §7 (revisions, 2026-05-01)
Supersedes: nothing in `suggestions.md` v1; first-pass suggestions 1–4 are ratified
and embodied in §7. This pass pressure-tests §7's *application* of the research and
the decisions made under risk #1–#7.
Research as of: 2026-05-01

## TL;DR for the project owner

§7 is a substantial improvement over v1 and most of its decisions hold up. I am
**not rubber-stamping**. There are five places where I think §7 chose
sub-optimally or under-specified, ranked below by ROI of the corrective change.
There are also two places where §7 is *more right than my v1 suggestions* and
should be ratified as written.

**Recommended changes ordered by ROI:**

1. **HIGH** — Flip risk #2 hook semantics from "swallow + log" to "fail-closed
   in dev / swallow + log + alarm in prod" (operator-controlled, default
   prod-swallow). Pure swallow is a production-ops anti-pattern; pure
   fail-closed is a dev-velocity anti-pattern.
2. **HIGH** — Tighten risk #5: make `conformance-substitution-removed` the
   *only* CI gate immediately at A-merge; do not run a `conformance-legacy`
   parallel mode "briefly." That dual mode is exactly the rollback hatch that
   keeps the substitution alive.
3. **MED** — Add a manifest field for *plugin-side* protocol_version
   declarations to be re-checked at runtime, not only at boot. §7.3's
   boot-time-only refusal misses lazy-load and reload cases.
4. **MED** — Resolve open decision §7.8.3 (PEP 440 vs npm caret) toward
   **dual-form on the wire** with PEP 440 canonical and npm-form documented as
   informative. §7.3's "PEP 440 only" creates UX friction for TS plugin authors
   that compounds across the ecosystem.
5. **LOW–MED** — Restore one half-day of "TS Pipeline runtime smoke test" to
   the E-spike: not a full port, but enough TS code to actually *consume* the
   protocol.ts types end-to-end. Pure types-only TS code never catches
   contract-shape bugs because nothing exercises the types.

**Ratify as written:** §7.1 (kind collapse), §7.2 (entry-point out of body),
§7.5 risk #1 (allowlist + reserved signatures), §7.5 risk #3 (Kahn + lex),
§7.5 risk #6 (env-vars only), §7.6 decomposition.

---

## Question-by-question review

### Q1 — Sanity-check the 7-engagement decomposition

**Holds up. Do not compress further.**

The structure is now:
- 5 v1 sub-engagements
- 1 post-v1 sibling (`reference-plugins-extended`)
- 1 umbrella

The v1 case for further compression would be: "merge `plugin-spec-polish` (B2)
into `plugin-discovery-py` (C) since polish is just docs and C is the user of
the spec." **Reject this.** Reasons:

1. B2's directory restructure of `spec/ports/middleware/` touches normative spec
   text. Lumping it with C makes the C engagement's review require *spec
   reviewer + python-pro* simultaneously — a bottleneck. Keeping them separate
   lets architect-reviewer sign B2 while python-pro signs C, in parallel.
2. B2 is the only post-contract-freeze polish work that is genuinely
   parallelizable with everything else. Merging it would force serial.
3. The 6 conformance fixtures in B2 are *cross-language* artifacts — they get
   exercised by both `plugin-discovery-py` and `plugin-architecture-ts`. If B2
   is folded into C, the fixtures become Python-coupled by accident.

**One mild concern:** `pipeline-integration` now carries 7 phases (was 5) after
absorbing F as 06/07 and adding 04 observability + 05 concurrency-fix. That is
on the edge of "too big for one engagement." But the phases are independent
enough (06/07 can land before 04 if needed, per v1 suggestion #1's risk note),
and splitting again just re-creates the orchestration overhead the merge was
designed to remove. **Hold the line at 7 phases.**

If `pipeline-integration` is still in flight at day 6 with phases 06/07
unstarted, *that* is the trigger to spin them out — not preemptively.

### Q2 — Re-evaluate the dependency graph

**§7.6's graph is correct and near-optimal. One refinement worth making:**

§7.6 says `reference-plugins` depends only on `plugin-discovery-py`. Strictly,
`reference-plugins` *also* depends on `pipeline-integration` — because
schema-strict (the chosen plugin) replaces `routes._validate_body`, and
`routes.py` only calls into the Pipeline once `pipeline-integration` is done.
If `reference-plugins` starts before `pipeline-integration` finishes, the
plugin will be authored against a code path that doesn't yet receive requests.

**Concrete recommendation:** annotate `reference-plugins/STATE.md` prereqs as
`[plugin-discovery-py, pipeline-integration]`. Both are required transitively
but the second one is currently implicit through the long A→C→D path; making
it explicit prevents accidental scheduling where D starts before A merges.

This does not change the critical path because A is the longest first-stage
task anyway. It just hardens the dependency declaration.

**Compression beyond §7.6:** none I can find that wouldn't sacrifice review
parallelism.

### Q3 — Pressure-test the §7.5 risk addenda

#### Risk #1 (supply-chain): allowlist + reserved signatures — **DEFEND**

This is right for v1. The OPA precedent is genuinely strong: OPA shipped
unsigned bundles in early versions and added Sigstore later without breaking
the bundle format. The reserved `signatures: []` field is a 4-byte cost
(literally) and removes the v2 migration burden entirely.

The only thing I'd add: spec the **failure mode when an allowlisted plugin
fails to load** vs **a non-allowlisted plugin found on entry-points**. They
should be different errors:
- Non-allowlisted, found: `plugin_not_allowed` (config error, fail-fast)
- Allowlisted, missing: `plugin_not_found` (deployment error, fail-fast)
- Allowlisted, found, manifest-invalid: `plugin_manifest_invalid` (build
  error, fail-fast)

Without this, a typo in `--allow-plugins` (e.g. missing version pin or
hyphen-vs-underscore) silently degrades to "plugin not loaded, no error."

**Action:** add to `plugin-contract-freeze:03-plugin-contract.md` error
taxonomy section.

#### Risk #2 (failure semantics per kind): **CRITIQUE — change hook default**

Three of four defaults are right. One is wrong:

- `interceptor` → `internal_error` envelope: ✓ (mirrors Express/Fastify; aligns
  with existing AuthMiddleware behavior)
- `transformer` → `validation_failed` envelope: ✓ (transformers operate
  pre-dispatch; validation framing is correct)
- `provider` startup → fail-fast: ✓ (Spring's "context refresh failed" pattern,
  battle-tested)
- `hook` → swallowed + logged: **wrong as a flat default**

The owner already flagged this concern (§7.8.6). I agree with the concern.
"Swallow + log" is exactly how observability plugins silently mask production
incidents — Datadog's own tracer has had multi-year-old issues where a buggy
hook ate exceptions from upstream code. Once you swallow, the only signal
operators get is "metrics look weird."

**Recommended decision:** environment-controlled, with explicit name:

```yaml
# Host config (sox env-var convention per risk #6)
SOX_HOOK_FAILURE_MODE=swallow   # production default
SOX_HOOK_FAILURE_MODE=raise     # CI/dev default
SOX_HOOK_FAILURE_MODE=alarm     # production option: swallow + structured-log + metrics counter
```

Spec the env-var; default to `alarm` (not `swallow`) in production. The cost
of `alarm` over `swallow` is one counter increment; the value is that
operators discover broken hooks via a metric instead of via "why are my
dashboards stale." `swallow` (silent) becomes an explicit opt-in.

CI must run with `SOX_HOOK_FAILURE_MODE=raise` so test suites surface bugs in
hooks immediately.

This is a **flat improvement** over the §7.5 proposal — same v1 schema,
smarter default, and the env-var hook fits cleanly under risk #6's
descope-to-env-vars decision. Cost: ~20 LOC in the HookDispatcher and one new
spec subsection. ROI: prevents a class of production-silence bugs.

#### Risk #3 (ordering cycles): Kahn + lex tie-break — **DEFEND**

Standard, deterministic, debuggable. Kahn's algorithm specifically (rather
than DFS-based topo sort) gives the operator a useful error message: it can
report *which* nodes are still incoming-edged when the queue empties, naming
the cycle members directly. Lex tie-break by plugin id is correct because it
is stable across Python and Node implementations (both languages sort UTF-8
strings the same way for ASCII identifiers; the spec should require plugin
ids to be ASCII or normalize via NFC for safety).

**One addition:** spec must say "ordering is computed once at startup and
cached." Otherwise an implementation might recompute per-request, which is
both wasteful and a chance for nondeterminism if plugin lists could mutate
mid-process (they can't in v1 — but the cached-once rule documents that).

#### Risk #4 (hot-reload deferral): **DEFEND with one tweak**

"v1 static; v2 may relax" is correct. The defensive note is also correct.

**Tweak:** the spec note as written says "Implementations MUST NOT depend on
stable Pipeline identity across reloads." Strengthen to: *"Plugin authors
MUST NOT cache references to host-provided objects (registries, contexts,
config) across plugin lifetime; the host MAY rebuild any of them. v1 hosts
will not actually rebuild them, but v2-compatible plugin code must not
assume otherwise."* This is the Backstage lesson — they couldn't introduce
hot-reload until plugin authors stopped caching.

This costs zero in v1 (because nothing reloads) and buys forward-compat for
free.

#### Risk #5 (CI substitution-removed mode): **CRITIQUE — drop the dual-mode**

§7.5's plan is to run *both* `conformance-substitution-removed` (must pass
after A) and `conformance-legacy` (with substitution, slated for removal in
v1.1). The stated rationale is "rollback if A regresses."

**This is the rollback hatch that defeats the purpose.** The whole point of
the harness substitution deletion is that the production server now must
enforce. Keeping the legacy path one CI flag away means:

1. If A merges with a bug that breaks `substitution-removed`, the team's
   path of least resistance is to revert to legacy mode for "one more
   release" while they fix it. That release ships.
2. New code lands during the fix window with the legacy assumption baked in.
3. v1.1 arrives, legacy is removed, new code breaks, and we're back where
   we started.

**Recommended:** delete the legacy mode at the same commit as the
substitution. Make `substitution-removed` the only mode. If A regresses, the
remediation is to revert A — not to flip a CI mode. The whole engagement A is
designed to make this possible (it's a 7-phase incremental landing, not a
big-bang).

**Concrete spec:** `pipeline-integration:06-delete-harness-substitution`
should *also* delete the legacy CI matrix entry in the same commit as the
substitution lines. One commit, one revert button. No middle state.

Cost of this change: zero (it's a smaller delta than §7.5 currently
proposes). ROI: high — preserves the symbolic milestone integrity that v1
suggestion #1 was protecting.

#### Risk #6 (sox.yaml descope to env-vars): **DEFEND**

Env-vars only is correct for v1. The convention `SOX_PLUGIN_<id>_<key>`
mirrors Twelve-Factor and is the path of least resistance for k8s deploys
(ConfigMap → env). Plugin authors who want a config file can wrap env-vars
locally; the host doesn't need to know.

**One concern:** plugin ids per §7.2 are reverse-DNS strings
(`org.example.sox-jwt-auth`). Mapping these to env-var names requires
canonicalization (`SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_<KEY>`). The
canonicalization rule needs to be normative and documented:

- Replace `.` and `-` with `_`
- Uppercase
- Concatenate with `_<KEY>`

If left ambiguous, two SDKs will canonicalize differently and a plugin's
config will work in Python but not in TS. **Spec it in B1.**

#### Risk #7 (pipeline_trace observability): **DEFEND**

Structured array is right for v1. OTel from day 1 would be over-engineering:
OTel adds a runtime dep, a trace context propagation contract, and a
sampling story. None of those are needed to debug "which plugin
short-circuited." Ship the structured array; emit OTel spans in v1.x once
real production-debug pressure shows what shape the spans need.

The structured-array shape in §7.5 is good. **Add one field:**
`correlation_id` (echoed from the request envelope, not invented). Without
it, `pipeline_trace` arrays from concurrent requests can't be correlated
across logs. Cheap to add now; impossible to retrofit usefully.

### Q4 — Pressure-test the kind-taxonomy collapse

**§7.1 is correct. Capability flags are the right approach. But the flag
*names* need work.**

The collapse from 5 → 4 kinds is research-grounded (Spring AOP
least-powerful-advice; NestJS production collapse evidence). Capability
flags (`observe_only`, `may_short_circuit`) are also the right move because
they make the *contract* declarative and statically inspectable, which is
exactly what `kind: guard` was trying to be.

The risk that capability flags re-create "which kind?" confusion as "which
flags?" is real but mitigable:

1. Keep the flag set **small** — 2–4 flags max for v1. The §7.1 example has
   2 (`observe_only`, `may_short_circuit`); resist adding more until a
   concrete need appears. NestJS's flag-creep happened because every release
   added a new bucket.
2. **Make flags orthogonal.** `observe_only: true` should imply
   `may_short_circuit: false` automatically. The host should reject manifests
   where the two contradict (`observe_only: true` + `may_short_circuit:
   true` → `plugin_capability_conflict` error). This is exactly the "static
   inferable contract violation" §7.1 alludes to.
3. **Document the mapping.** The spec should explicitly say "if you would
   have written `kind: guard` in the v1 design, write `kind: interceptor`
   with `may_short_circuit: true, observe_only: false`." This migration
   table prevents the "what kind do I want?" confusion by giving authors a
   recipe instead of a taxonomy lecture.

These three additions cost maybe half a page of spec text and make the
collapse genuinely better than the v1 5-kind design rather than just
equivalent.

**Net verdict on §7.1:** ratify, with the above three spec amendments to
the B1 plugin-contract.md.

### Q5 — Pressure-test the manifest decisions (entry-point out of body)

**§7.2 is the most opinionated single choice and it is correct.**

The two-file authoring concern is real but mis-scoped. Plugin authors in
both Python and Node *already* maintain language-specific package metadata
(`pyproject.toml`, `package.json`). They are not adding a new file; they
are adding 3 lines to a file they already maintain.

The alternative — entry-point in the manifest body — has worse failure
modes:

1. **Cross-language manifest mutation.** A manifest with `entry:
   "myorg_sox_jwt_auth:make_plugin"` is *not* loadable in Node, because
   that's a Python module path. A Node-side host loading the manifest to
   *validate* it (e.g. for a registry, or for spec-compliance checks) would
   either ignore the entry or fail. Neither is correct.
2. **Build-system coupling.** The manifest body would need to encode a
   field like `entry_python: ...` and `entry_node: ...`, growing
   monotonically per language. That's the language-specific rot the
   research finding warned about.
3. **Re-publication burden.** If a plugin author rewrites their loader
   (e.g. moves `make_plugin` from `__init__.py` to `plugin.py`), they have
   to re-publish the manifest *and* the package, instead of just the
   package.

The Backstage / Envoy / OPA precedent is unambiguous on this. Concrete
plugin-author UX:

```
my-plugin/
├── pyproject.toml          # 3-line addition under [project.entry-points]
├── sox-plugin.yaml         # the manifest, language-neutral
└── src/
    └── my_plugin/
        └── __init__.py     # make_plugin function
```

vs. the rejected alternative:

```
my-plugin/
├── pyproject.toml          # unchanged
├── sox-plugin.yaml         # has entry_python, will need entry_node, entry_rust...
└── src/
```

The first is genuinely simpler for the author (the manifest stays small;
package metadata stays in the package); only the cross-language host
pays a small dispatcher cost, which it pays once.

**Ratify §7.2 as written.** No changes needed.

One nice-to-have for plugin-author UX: a `sox-cli scaffold-plugin` command
in v1.x that generates both files together. Keeps the "two files" objection
from manifesting as friction. Out of scope for v1; flag as a future
deliverable.

### Q6 — NEW risks introduced by the revisions

#### NR-1: `pipeline-integration` over-scoping risk

Merging F into A and adding observability + concurrency-fix gives A 7
phases over 4–5 days. **At the upper bound that's ~1.4 phases/day** —
aggressive but achievable for python-pro on a well-defined refactor.

Risk: if any single phase blows budget (most likely 04-concurrency-fix —
asyncio.Lock interactions with the verifier replay path are subtle), the
6/7 substitution-deletion phase slips. The symbolic milestone is then
delayed, which is the exact thing v1 suggestion #1 was protecting against.

**Mitigation (cheap):** add an explicit phase-ordering rule to A's
STATE.md:

> Phases 06 and 07 (substitution deletion + server-side rejection
> fixture) MAY land independently of phase 04 (concurrency-fix) once
> phases 01/02/03 are complete. The concurrency-fix is independently
> reviewable and need not gate the symbolic milestone.

This costs nothing and gives the team an out if 04 is harder than
expected.

#### NR-2: One-plugin contract proof is genuinely thinner

Narrowing D from 3 plugins to 1 is correct ROI-wise (v1 suggestion #2
stands), but it does weaken the contract validation. With three plugins,
a contract bug that only manifests with `Provider` would be caught; with
one plugin (transformer-only), the Provider contract is unexercised in v1.

**Concrete consequence:** the `provider` kind's contract (factory →
Resource with on_startup/on_shutdown) ships in B1 spec but has zero
runtime validation in v1. The first real `provider` plugin (likely
redis-pool in `reference-plugins-extended`) will probably surface a
contract bug.

**Mitigation:** in `plugin-contract-freeze:03-plugin-contract.md`, ship a
*conformance fixture* that exercises the `provider` kind with a synthetic
in-memory provider (no real resource), even if no real provider plugin
ships in v1. This catches obvious contract bugs (factory signature,
lifecycle ordering) without requiring a real plugin. Cost: ~half a day
inside B1's existing scope. ROI: the post-v1 redis-pool engagement won't
hit a "we have to revise the spec" wall.

#### NR-3: TS spike "cliff" if production code lands sooner than expected

§7.6 reduces E to a 1-day types-only spike. The owner accepted this with
eyes open per status.md. But there's a specific failure mode worth
naming:

If TS production code begins before the full TS Pipeline runtime exists,
the team may be tempted to "just inline" the middleware logic directly in
TS handlers — the exact pattern SOX is escaping in Python. Once that
inline code exists, replacing it with a Pipeline runtime port is a *lift*
not a *port*.

**Mitigation:** in `plugin-architecture-ts/STATE.md`, add a phase that
ships a **stub** Pipeline class (TS) that throws `NotImplementedError`
on dispatch. This is ~30 LOC. Its purpose is sociological, not
functional: when TS production code starts, the obvious thing to import
is `Pipeline` from `@sox/middleware`, even if it currently throws. That
stub becomes the load-bearing place where the runtime gets implemented,
preventing the "inline middleware in handlers" anti-pattern from taking
root.

This converts the "spike" from "types only" to "types + runtime stub" —
still ~1 day, still no real runtime, but with a forcing function for
correct shape when real code arrives.

#### NR-4: B1's "plugin-contract-freeze" name oversells finality

The split name `plugin-contract-freeze` (B1) implies the contract is
*frozen* after B1 ships. But B2's `plugin-spec-polish` includes 6
conformance fixtures that *exercise* the contract — and those fixtures
may surface contract issues that force B1 amendments.

This is fine in practice (Postel's running-code reasoning) but the name
is misleading. If the team takes "freeze" literally, they'll resist
revising B1 even when B2 fixtures find bugs.

**Recommendation:** keep the engagement slug for path-stability, but in
the docs say "B1 produces a *candidate* contract; B2 fixtures
pressure-test it; minor amendments to B1 are expected and not a process
failure." Document this explicitly in `plugin-architecture/status.md` so
reviewers don't reject a B1 amendment PR on the grounds that "B1 was
already merged."

### Q7 — Re-rank ROI of the 5 v1 sub-engagements

Reaffirming the v1 ranking from `suggestions.md`, with §7 revisions
folded in:

1. **`pipeline-integration`** (highest visible value; HTTP conformance
   22/10/27 → 32/0/27; substitution deletion; observability foundation).
   Ship first. Run **concurrently with** `plugin-contract-freeze` from
   day 0 if two-engineer capacity exists.
2. **`plugin-contract-freeze`** (unblocks C/D/E with ~2–3 days of
   focused contract work). Concurrent with #1.
3. **`plugin-discovery-py`** (entry-point machinery + allowlist). The
   allowlist is the v1 supply-chain story per risk #1; this engagement
   is where it actually lives in code.
4. **`reference-plugins`** (one plugin: schema-strict). Validates the
   contract on real code. Migrates `_validate_body` out of core.
5. **`plugin-architecture-ts`** (1-day spike, *with* the stub Pipeline
   addition per NR-3 above). Lowest ROI of the v1 set, accepted as a
   forward-compat investment.
6. **`plugin-spec-polish`** (parallel with 3/4/5; not on critical path).
   Documentation polish + conformance fixtures including the
   provider-kind synthetic fixture per NR-2.
7. **`reference-plugins-extended`** — post-v1, defer.

**No deviation from §7.6's ordering.** §7.6 got this right after
incorporating v1 suggestions 1–4.

---

## Research gaps remaining (not blocking)

The three new findings cited in §7 cover manifest formats, taxonomies, and
versioning — the v1 gaps are filled. New gaps surfaced by this pass:

1. **Hook-failure-mode operator conventions.** "Swallow vs alarm vs raise"
   for observability plugins — what do Datadog APM, OpenTelemetry SDK, and
   Sentry actually default to in production? Worth a narrow research run
   before B1 freezes risk #2 semantics. Owner can dispatch
   `workflow-researcher` if the env-var-controlled proposal here is
   contentious.

2. **Plugin-id canonicalization for env-var mapping** (per risk #6
   defense). PEP 8021 / Twelve-Factor have conventions; worth a 1-hour
   review before B1 finalizes the convention. Not a full research run.

Neither blocks workflow-planner from running.

---

## Self-critique pass

- Every suggestion cites §7 or v1 suggestions or research-finding paths?
  Yes. No fabricated best-practice.
- Disagreements with §7 are *concrete* (which clause, what change)? Yes
  — five labeled "CRITIQUE" points with exact spec deltas.
- Difficulty estimates? Each recommended change is XS-or-S spec text or
  config; none require new engagements. The umbrella decomposition is
  unchanged.
- ROI metrics measurable? Yes for risk #5 (one rollback hatch eliminated
  = binary), risk #2 (env-var control = 3 modes vs 1), NR-1 (phase
  ordering = 0 cost), NR-2 (1 conformance fixture in existing scope),
  NR-3 (~30 LOC stub).
- "No changes recommended" considered? Yes — and rejected, because §7
  has 5 specific places where a small spec amendment is high-ROI.
  Suggestions 1–5 above are honest critiques, not padding.
- Open decisions §7.8 addressed? Yes:
  - §7.8.1 (kind collapse): ratify with 3 spec amendments
  - §7.8.2 (entry out of body): ratify as written
  - §7.8.3 (PEP 440 form): recommend dual-form (med ROI)
  - §7.8.4 (sox.yaml descope): ratify with canonicalization rule
  - §7.8.5 (TS spike): ratify with stub-Pipeline addition (NR-3)
  - §7.8.6 (hook failure mode): change default (HIGH ROI, item #1)

---

## Output for workflow-planner

Net additional spec work for B1 (`plugin-contract-freeze`):

1. Error taxonomy section (risk #1 elaboration: not_allowed / not_found /
   manifest_invalid)
2. Hook failure-mode env-var convention + default = `alarm` (risk #2)
3. Stable Kahn ordering computed-once-at-startup rule (risk #3 polish)
4. Plugin-author "MUST NOT cache references" forward-compat note (risk
   #4 strengthen)
5. Plugin-id env-var canonicalization rule (risk #6 polish)
6. Capability flags: orthogonality enforcement + flag-set cap +
   migration table from v1 5-kind design (Q4)
7. Provider-kind synthetic conformance fixture (NR-2)
8. B1 "candidate contract" framing note (NR-4)

Estimated total: ~half a day of additional spec text inside B1's existing
2–3 day budget. **B1 effort estimate stands.**

Net additional code work for A (`pipeline-integration`):

1. `correlation_id` field in `pipeline_trace` array (~5 LOC)
2. Remove the legacy CI matrix entry in same commit as substitution
   deletion (risk #5 critique; net negative LOC)
3. Phase-ordering note in STATE.md allowing 06/07 to land before 04
   (NR-1; documentation only)

Net additional code work for E (`plugin-architecture-ts`):

1. Stub Pipeline class throwing `NotImplementedError` (~30 LOC) on top of
   the types-only spike (NR-3). E remains 1 day.

Net additional code work for D (`reference-plugins`): none. Stays at 1
plugin, 2 days.

Net additional code work for B2 (`plugin-spec-polish`): one new
conformance fixture for synthetic provider (NR-2). Stays in existing 2–3
day budget.

**No engagement effort estimates change.** All v2 critiques fit inside
existing budgets because they are spec amendments, not new scope.
