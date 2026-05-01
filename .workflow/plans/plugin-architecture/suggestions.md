# Workflow optimization suggestions — plugin-architecture umbrella

Based on: `.workflow/plans/plugin-architecture/analysis.md` (generated 2026-05-01)
Research as of: 2026-05-01

## Research gaps (memory was insufficient)

The shared `~/.claude/plugins/workflow/memory/research/` index has no
topic covering plugin-architecture / middleware-contract / cross-language
plugin manifests / Fastify-vs-NestJS-vs-gRPC synthesis. The analysis cites
those frameworks directly and the project owner already approved the
synthesis, so suggestions below lean on the analysis's own framework
citations rather than fabricating "best practice" without sources. A
domain-neutral `workflow-researcher` run would be valuable for *future*
plugin-spec work but is **not blocking** this optimize pass — the analysis
is internally well-sourced.

Recommended follow-up research questions (not dispatched here):

1. "Cross-language plugin manifest formats — survey of Fastify
   `fastify-plugin`, Envoy/xDS, OPA bundle, gRPC interceptor metadata,
   Backstage plugin-metadata.yaml, VS Code `package.json#contributes`,
   Babel preset/plugin protocol, ESLint shareable configs. What's the
   convergent shape and what divergences are load-bearing?"
2. "Plugin kind taxonomies — NestJS Interceptor/Guard/Pipe, Spring
   AOP advice types, Envoy filter types, Istio EnvoyFilter, Kong plugin
   phases. Which taxonomies survived contact with users and which got
   collapsed back?"
3. "Protocol-version negotiation in plugin systems — Fastify
   `fastify` field, Backstage `backstage.role`, VS Code
   `engines.vscode`, Terraform provider protocol versions. Refusal
   semantics, range syntax, and migration strategy."

---

## Ranked suggestions

### 1. Restructure to a "thin spine" merge: hoist the harness-cleanup deletion *into* pipeline-integration as its acceptance test — ROI: high · Difficulty: XS

**Observation** (from analysis §1.4 + §6): Analysis identifies
`tools/conformance_runner.py:805-813` deletion as "the single
highest-value commit in the whole program." Yet the engagement
decomposition makes it a separate 1-day engagement (F) blocked on A,
gated by its own plan/build/review cycle.

**Pattern** (from the analysis itself, §4.1 step 4): "The conformance
harness's client-side rejection block ... gets *deleted*. The production
server now enforces. If conformance regresses, the framework caught a
real bug." The analysis already proposes the deletion as part of A's
done-criteria.

**Proposal:** Collapse harness-cleanup (F) into pipeline-integration (A)
as its terminal acceptance test:

- Phase `06-delete-harness-substitution` inside A — deletes lines
  805-813 and the `_registered_agents` field, runs conformance, must
  show 32/0/27 against both transports.
- Phase `07-add-server-side-rejection-fixture` — adds the new fixture
  asserting server-side rejection.

A is no longer "done" until the substitution is gone. F goes away as
a separate engagement.

**Rationale:** The substitution is *the test* of whether A worked.
Splitting it into a separately-tracked engagement adds orchestrator
overhead (planner spawn, review spawn, status churn) for ~20 LOC of
deletion. It also lets the team declare A "done" while the smoking gun
is still in the tree — a misleading state.

**Difficulty:** XS — moves two small phases from one STATE.md to
another. workflow-planner edits, no code change.

**Expected ROI:** high. Eliminates one full engagement
(plan→build→review×3) of orchestrator overhead. Compresses
calendar by ~1 day. Forces the symbolic milestone to land *with* the
work that earned it, not as a separate ceremony. Measurable: one fewer
STATE.md to maintain (-1 of 6 = 17% reduction in umbrella surface area).

**Risk:** A grows from 5 phases to 7 phases. If A has to be paused
mid-flight, the "harness still has substitution" state persists longer.
Mitigation: the 06/07 phases are independent of 04-concurrency-fix and
05-review, so they can land first if stdio integration is done.

**Sources:** analysis.md §4.1 step 4 (already specifies the deletion as
part of A's deliverables); analysis.md §6 (single-highest-value commit
framing); harness-cleanup/STATE.md `prereqs: [pipeline-integration]`
(confirms F adds nothing A doesn't already need to do).

---

### 2. Defer reference-plugins (D) from v1 critical path; ship 1 plugin not 3 — ROI: high · Difficulty: S

**Observation** (from analysis §4.4): Three reference plugins proposed
(audit-jsonl, rate-limit-redis, schema-strict). One of these
(rate-limit-redis) requires a `Provider` plugin contract — itself a
§5.6 open design question still resolving. The other two
(audit-jsonl, schema-strict) are independently valuable.

**Pattern** (from analysis §2.1 + §5.6): The Provider kind is the most
controversial part of the kind taxonomy — analysis itself says
"separate registration mechanism" is "recommended" but flags it as a
new API not yet specified. Shipping a plugin that exercises the most
unstable part of the contract first is risky.

**Proposal:** Reduce D's v1 scope to **one** plugin: `schema-strict`
(transformer). Reasons:

- It migrates *real existing code* (`routes.py:_validate_body`) out of
  core — measurable LOC reduction, not new feature surface.
- It exercises only the Transformer kind, which is the
  least-controversial of the five.
- It eliminates the `_validate_body` duplication across 22 HTTP
  handlers.
- It does *not* depend on the Provider contract.

Move `audit-jsonl` and `rate-limit-redis` to a follow-on engagement
`reference-plugins-extended` (post-v1). This unblocks
plugin-architecture-ts (E) earlier because the contract gets exercised
faster.

**Rationale:** The contract is *proven* by one well-chosen plugin that
migrates real code. Three plugins built in parallel risk three
divergent interpretations of an unfrozen spec, then a costly
re-alignment. Better to freeze the contract on one canonical migration,
then expand.

**Difficulty:** S — workflow-planner edits D's STATE.md to drop two
phases; creates a placeholder `reference-plugins-extended` engagement
for post-v1.

**Expected ROI:** high. Compresses D from 1-2d × 3 = 3-6d to ~2d.
Removes the riskiest plugin (rate-limit-redis with provider dep) from
critical path. Measurable: critical path shortened by 2-4 days; one
fewer place where Provider semantics need to be frozen for v1.

**Risk:** Three-plugin contract proof is weaker than one. Mitigation:
the spec engagement (B) is the contract; D is the *demonstration*.
Demonstration with one plugin is sufficient for "the contract works";
breadth comes post-v1.

**Sources:** analysis.md §2.1 (kind taxonomy); §5.6 (Provider open
question); §4.4 (the three plugins); reference-plugins/STATE.md phases
02/03/04.

---

### 3. Split plugin-manifest-spec (B) into B1 (frozen contract for unblocking) + B2 (full spec polish) — ROI: high · Difficulty: S

**Observation** (from analysis §3 + dependency graph §4.7): B is on the
critical path of C (discovery-py), D (reference-plugins), and E (TS
SDK). All three are blocked until B is fully done — 4-5 days. But
those dependents only need a *subset* of B: the manifest schema, kind
taxonomy, and protocol_version rules. They do **not** need the full
spec/ports/middleware/ directory restructure or the 6 conformance
fixtures (which are themselves marked `pending: true`).

**Pattern** (Fastify, Envoy, gRPC all freeze the wire/manifest contract
*before* the prose spec is finalized — implementations precede full
docs): the analysis's own framework citations all shipped runnable
contracts before normative spec text was complete.

**Proposal:** Split B into:

- **B1 — `plugin-contract-freeze`** (~2 days): ADR 0004 draft + JSON
  Schema for `sox-plugin.yaml` + 03-plugin-contract.md +
  06-versioning.md. Sufficient to unblock C/D/E.
- **B2 — `plugin-spec-polish`** (~2-3 days): the directory restructure
  (01/02/05/07/08), the conformance fixtures, the cross-references. Can
  run in parallel with C/D/E.

C/D/E unblock on B1 (~day 2), not B (~day 5). Calendar compresses by
~3 days.

**Rationale:** A frozen JSON Schema + ADR is enough for downstream
implementation. The prose spec's directory hygiene, fixtures, and
README polish do not gate code-writing. Treating them as one
engagement holds dependents hostage to documentation work.

**Difficulty:** S — workflow-planner edits B's STATE.md to split
phases; updates prereqs on C/D/E from `plugin-manifest-spec` to
`plugin-contract-freeze`.

**Expected ROI:** high. Critical-path compression of ~3 days on a
~21-day program (~14% calendar reduction). Reduces "spec polish"
opportunity-cost: while polish happens, code happens too.

**Risk:** B2 might discover a contract issue that requires changes,
forcing C/D/E rework. Mitigation: that's exactly what spec review is
for — and it's better to discover it via real implementation pressure
than via prose review alone (Postel/rough-consensus-and-running-code
reasoning).

**Sources:** analysis.md §3 (8-file restructure scope); §4.2 (B
deliverables); plugin-manifest-spec/STATE.md (5 phases, only 01+03 are
contract-freezing).

---

### 4. Re-order: ship A *concurrently* with B1 from day 0, not "A first then B" — ROI: med · Difficulty: XS

**Observation** (from analysis §4.7 + §6): Analysis dependency graph
correctly says A and B are independent. But analysis §6
"Recommendations" then says "Engagement A first ... Engagement B
second" — a *sequential* ordering not justified by the DAG.

**Pattern**: Critical-path scheduling — when two tasks are independent,
parallelism is the default unless a resource constraint forbids it.

**Proposal:** Run A and B1 (per suggestion #3) literally in parallel
from day 0. Different specialists (python-pro vs architect-reviewer +
api-designer), no shared files, no shared review queue.

**Rationale:** The "A first" framing in §6 conflates *priority order
for review* with *temporal scheduling*. They are independent. Two-engineer
or two-agent capacity makes this strictly dominant.

**Difficulty:** XS — scheduling decision only. No STATE.md edits
required; this is a workflow-planner instruction.

**Expected ROI:** med. Parallelism saves ~2-3 days if capacity exists;
zero saving if single-engineer (then just do A first as analysis says).
Measurable: under two-engineer capacity, total calendar drops from
~3 weeks to ~2 weeks.

**Risk:** If B1 reveals a contract issue that forces A to refactor
mid-flight (e.g. `kind` field needs a slot in `MiddlewareContext`),
rework cost. Mitigation: A is *not* exposing manifests yet; it's
internal pipeline wiring. B1's manifest is for *external* plugins.
The interfaces don't collide.

**Sources:** analysis.md §4.7 (correct DAG), §6 (incorrect sequential
recommendation), pipeline-integration/STATE.md (no manifest deps),
plugin-manifest-spec/STATE.md (no pipeline deps).

---

### 5. Eliminate plugin-architecture-ts (E) from v1; replace with a 1-day "TS contract spike" — ROI: med · Difficulty: M

**Observation** (from analysis §1.7 and §4.5): E is a 1-week port of
the entire Python middleware framework to TS, "before TS code lands."
But analysis §1.7 also notes that the TS SDK is *planned*, not
shipped — `packages/typescript/README.md` describes future work. There
is **no** TS production code that needs the framework yet.

**Pattern** (Postel + YAGNI): Building both implementations
simultaneously to "prevent drift" is a classic over-investment when
only one implementation has users. The drift risk is real but cheaper
to address by *publishing the manifest schema and kind taxonomy as
language-agnostic spec* (which B1 does) than by porting the full
runtime.

**Proposal:** Replace E with a 1-day "TS contract spike":

- Author `packages/typescript/src/core/middleware/protocol.ts` —
  interfaces only, no runtime, no Pipeline, no Registry.
- Validate that `sox-plugin.yaml` round-trips through a TS YAML loader
  + AJV against the same JSON Schema.
- Document this in the spec as "TS reference shape; full runtime ships
  with first TS production code."

Defer the full E to whenever TS production code lands (current
roadmap: post-v1).

**Rationale:** "Mirror Python design before TS code lands" is correct
about the *contract*, not about the *runtime*. The contract is the
manifest + JSON Schema + interface signatures. Shipping a TS Pipeline
runtime with no TS users is dead weight that has to be maintained in
sync with Python changes through v1.x.

**Difficulty:** M — workflow-planner replaces E (6 phases over 1 week)
with a 1-day spike engagement; risks pushback because owner explicitly
listed "Mirror Python design in TS SDK before TS code lands" as a
goal. Worth raising as a deliberate scope-cut decision.

**Expected ROI:** med. Saves ~5 engineering days. Measurable: one fewer
runtime to keep in sync during v1.x evolution (~50% reduction in
plugin-runtime drift surface). Risk-weighted, this is the *most
contentious* suggestion — flag for owner decision.

**Risk:** If TS production code lands sooner than expected (~3-6
months), the deferred work becomes urgent and now must be done under
schedule pressure rather than as part of the architectural program.
Mitigation: the spec engagement (B) freezes the contract; whenever the
runtime port happens, the design decisions are already made.

**Sources:** analysis.md §1.7, §4.5; plugin-architecture-ts/STATE.md
(6 phases); `packages/typescript/README.md` (planned, not shipped).

---

## Risks the analysis missed (responding to question 4)

Analysis §5 covers concurrency, performance, kind-vs-provider,
HookDispatcher, version negotiation. **Missing or under-covered:**

1. **Plugin trust / supply-chain risk.** `load_entry_points` discovers
   *anything* installed in the venv that declares
   `sox_protocol.plugins`. A malicious or buggy plugin gets full pipeline
   access — including the ability to read all `MiddlewareContext.input`
   bodies (which contain channel messages, agent IDs, signed
   credentials). Spec needs an explicit security boundary: at minimum a
   `--allow-plugins <name,name,...>` allowlist for production deploys,
   ideally a manifest-pinning mechanism (hash or version pin).
   **Action:** add to B1 spec; add allowlist flag to C.

2. **Plugin failure semantics.** What happens when an interceptor
   raises a non-`ShortCircuitResponse` exception in production? The
   pipeline's "internal-error envelope on uncaught exceptions" is
   noted, but the *taxonomy of failure* is not specified: does
   `kind: guard` failure deny-by-default or allow-by-default? Does
   `kind: hook` failure crash the request or get swallowed? Spec must
   define normative failure modes per kind.

3. **Plugin ordering ambiguity / cycles.** `must_run_before` /
   `must_run_after` form a DAG. The analysis doesn't specify what
   happens with: (a) cycles in the `must_run_*` graph (refuse-to-load
   error?); (b) underspecified ordering (two plugins with no relative
   constraint — deterministic by name? insertion order?); (c) conflicts
   with `DEFAULT_ORDER`. Spec needs a normative topological-sort
   algorithm and tie-break rule.

4. **Hot-reload / dynamic registration.** Current Pipeline assumes
   static composition at startup. Realistic deploys want to add a
   plugin without restart (rate-limit tuning, audit-log redirection).
   Not a v1 requirement, but a *spec hazard*: locking in
   "static-composition-only" semantics now makes hot-reload
   forever-painful later. Either spec it as "v1 is static; v2 may
   support reload" or design `MiddlewareRegistry` mutation rules
   defensively.

5. **Conformance-suite coupling to harness-cleanup.** If A ships and
   conformance regresses (because the production server still has a
   gap), the harness substitution gets re-enabled to keep CI green —
   defeating the purpose. Need an explicit "no-substitution mode" CI
   matrix entry that *must* pass, separate from the legacy mode.
   `harness-cleanup`'s STATE.md mentions uncommenting
   `python-reference-http`; this is the right instinct, but the
   discipline needs to be: substitution-removed mode is the *only*
   mode after A. Recommend adding a CI-gate for "substitution removed"
   in suggestion #1's merged engagement.

6. **`sox.yaml` config-file coupling.** §5.5 recommends `sox.yaml` as
   primary config delivery. But that introduces a new top-level
   project artifact with its own schema, validation, and migration
   story. Analysis doesn't budget time for `sox.yaml` schema spec,
   which is non-trivial (per-plugin sections, env-var override
   semantics, precedence rules). Either descope to env-vars-only for
   v1 or add a phase to B for `sox.yaml` schema.

7. **Telemetry / observability of the pipeline itself.** Once the
   pipeline runs every request, *its* behavior becomes a debugging
   surface: which middleware ran, in what order, with what timings,
   why was the request short-circuited? The existing
   `metadata["middleware_timings"]` is a start. Spec should require
   structured execution traces (OpenTelemetry-compatible spans?) so
   operators can debug "why did my request fail in
   plugin-foo-bar?" without grepping logs.

---

## Manifest format & taxonomy soundness check (responding to question 5)

The synthesis (Fastify manifest + Next.js declarative matchers + gRPC
cross-language + NestJS taxonomy minus decorators) is **defensible
but not optimal**. Specific notes:

- **Better-known prior art the analysis missed:**
  - **Backstage `catalog-info.yaml` + plugin-metadata.yaml** —
    closest match to what SOX wants (cross-language plugin manifest
    in YAML, declarative scope, version negotiation, used in
    production at scale). Worth a research run.
  - **Envoy filter chain + xDS protocol** — gold standard for
    declarative ordered middleware with version negotiation and
    cross-language portability. The `must_run_before/after`
    formulation in SOX is weaker than Envoy's explicit phase enum
    (`AUTHN`, `AUTHZ`, `RATE_LIMIT`, etc.). Consider replacing
    `DEFAULT_ORDER` string-based ordering with a closed phase enum.
  - **OPA bundles** — for `Guard` kind specifically, OPA's
    decision-point + policy-bundle model is more battle-tested than
    a hand-rolled `Decision{allow|deny}` shape. Not necessarily
    adopt it, but cite it in the ADR for "considered alternatives."

- **Kind taxonomy soundness:** Five kinds is right, but
  `Provider` doesn't fit the same machinery (analysis §5.6
  acknowledges this) and `Hook` overlaps with `Interceptor` in
  observable behavior. A cleaner taxonomy:
  - **Wire kinds** (in pipeline): Interceptor, Guard, Transformer
  - **Lifecycle kinds** (out of pipeline): Provider, Hook
  - Two registries, two contracts, no awkward "kind: provider with
    no `__call__`."

  This is closer to NestJS's actual split (Interceptor/Guard/Pipe in
  request flow; Module/Provider in DI graph). Worth raising in B1.

- **Manifest format:** YAML is fine, but consider whether `requires`
  / `provides` should be *capability strings* (string-typed,
  registry-validated) or *plugin-name strings* (more brittle, used
  in the example). Capability strings (what the analysis uses for
  `provides: auth.method: "jwt-bearer"`) are far more flexible than
  name-based deps and should be the *primary* mechanism, with
  name-based as fallback.

---

## Provisional ROI ranking — top-3 recommendations to ship first

Re-ranking the original 6 against question 6, after applying
suggestions 1-5:

1. **A (pipeline-integration, with F merged in per #1)** — highest
   user-visible value: HTTP conformance goes from 22/10/27 to 32/0/27,
   `PassthroughIdentityResolver` deleted, harness substitution gone.
   This is the demonstrable architectural milestone. Ship first.

2. **B1 (plugin-contract-freeze, per #3)** — unblocks C/D/E with ~2
   days of focused contract work. Run *concurrently* with A from day
   0 (per #4) if capacity allows.

3. **D-reduced (schema-strict only, per #2)** — the *one* plugin that
   migrates real code (`_validate_body` → external plugin) and
   demonstrates the contract. Ship third.

Then C (discovery-py) lands the entry-point machinery; B2 polishes
the spec; E becomes the 1-day TS spike (per #5).

**Argument against the original ordering:** original says "C, D, E in
parallel after B." That's correct *if* B is monolithic. Splitting B
into B1/B2 lets C/D/E start ~3 days earlier *and* lets B2 polish
proceed in parallel with C/D/E rather than gating them.

**Argument against shipping B before A symbolically:** B is spec
work; A is the smoking-gun fix. Shipping B first looks like "we
wrote a lot of YAML and the bug is still there." A first (or
parallel) is the right *narrative* even when the DAG permits other
orderings.

---

## Self-critique pass

- Every suggestion cites the analysis or the analysis's own framework
  citations? Yes (no fabricated best practices; memory-gap explicitly
  flagged).
- Difficulty estimates justified with concrete file/phase counts? Yes.
- ROI metrics measurable? #1 (1 fewer engagement, ~17% surface
  reduction), #2 (2-4 days saved), #3 (~14% calendar compression),
  #4 (~2-3 days under 2-engineer capacity), #5 (~5 days saved, 50%
  drift surface reduction). #4's ROI is conditional on capacity —
  flagged honestly.
- Risk section non-empty per suggestion? Yes.
- Research gaps explicit? Yes — top of artifact.
- Honest "no high-ROI changes found" considered? No — the analysis is
  rigorous but the engagement decomposition has clear compression
  opportunities. Five suggestions is appropriate; not padding.
- Dependency-graph and risk questions (Q4, Q5, Q6) answered with
  reasoning, not rubber-stamp? Yes — I disagreed with the original
  sequential ordering (#4), the three-plugin scope (#2), the full
  TS port (#5), and added 7 missed risks plus better prior-art
  citations.
