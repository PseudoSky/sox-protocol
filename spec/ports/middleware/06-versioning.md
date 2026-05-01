<!-- SPDX-License-Identifier: Apache-2.0 -->
# SOX Protocol Plugin-Protocol-Version Negotiation

**Version:** 1.0
**Status:** candidate (2026-05-01)
**Scope:** Language-neutral. Normative for all SOX Protocol v1 host implementations and plugin authors.

**Related:**
- `docs/adr/0004-plugin-architecture.md` — companion ADR; decisions 3 (versioning), 4 (discovery), and 7 (configuration) are the direct inputs to this document
- `spec/schemas/sox-plugin.schema.json` — machine-readable schema; the `protocol_version` field's `oneOf` patterns and the `signatures` field definition are normative references throughout this document
- `spec/ports/middleware/03-plugin-contract.md` — sister document; §6 of that document defines the closed error taxonomy from which `plugin_protocol_version_mismatch` is drawn
- `.workflow/plans/plugin-architecture/analysis.md` §7.3 (versioning decision) and §7.4 (signing reservation)

---

## 1. Purpose & Scope

This document defines the version-negotiation contract between SOX hosts and plugins. It specifies:

- How plugins declare the set of host protocol versions they are compatible with.
- How hosts validate that declaration at boot time.
- The refusal semantics and structured error envelope when the host and plugin are incompatible.
- Pre-release marker normalization rules across PEP 440 and npm semver syntax.
- The v1 signing reservation and its planned evolution path.

**In scope:** the `spec.protocol_version` field in `sox-plugin.yaml`; host `host_protocol_version` declaration; boot-time compatibility check algorithm; the `plugin_protocol_version_mismatch` error envelope; pre-release handling; the `signatures` reserved field.

**Out of scope:** the plugin *content* version — `metadata.version` in the manifest — which is the plugin author's release tag and carries no host-compatibility semantics. That field is documented in `spec/schemas/sox-plugin.schema.json` and is not evaluated by the version-negotiation algorithm described here.

The decisions ratified here correspond to ADR 0004 decisions 3 and 4. Where this document and ADR 0004 conflict, ADR 0004 is authoritative.

---

## 2. The `protocol_version` Field (normative)

### 2.1 Field definition

The `spec.protocol_version` field in `sox-plugin.yaml` is a **required** SemVer 2.0.0 range expression ([SemVer 2.0.0](https://semver.org/)). There is no default value; a manifest that omits this field MUST be rejected with `plugin_manifest_invalid` during schema validation, before the version-negotiation algorithm is reached.

The field is defined in `spec/schemas/sox-plugin.schema.json` under `properties.spec.properties.protocol_version`. The schema enforces `minLength: 1` (empty string is invalid) and a `oneOf` constraint accepting either of the two wire forms described below.

### 2.2 Dual wire forms

Two wire forms are accepted. Both MUST be supported by every conforming host implementation. Hosts MAY canonicalize internally (for example, converting npm caret to PEP 440 before evaluation) but MUST accept either form on the wire without requiring the plugin author to use a specific form.

**Form 1 — PEP 440 specifier (canonical):** comma-separated version clauses, each consisting of a comparison operator (`==`, `!=`, `<=`, `>=`, `<`, `>`, `~=`) followed by a version string ([PEP 440](https://peps.python.org/pep-0440/)).

Examples (drawn from `spec/schemas/sox-plugin.schema.json` `examples` array):

```
>=1.0,<2.0
~=1.0
==1.0.0
>=1.0.0,!=1.2.0,<2.0
```

PEP 440 is the canonical wire form because Python's `packaging.specifiers.SpecifierSet` parses it natively and it is the form used in all three committed example manifests — `sox-plugin.example.interceptor.yaml` (`">=1.0,<2.0"`), `sox-plugin.example.transformer.yaml` (`">=1.0,<2.0"`), and the inline example in `sox-plugin.schema.json`.

**Form 2 — npm semver range (informative-but-supported):** caret, tilde, comparison, or wildcard notation as defined by the `node-semver` range syntax.

Examples (drawn from `spec/schemas/sox-plugin.schema.json` `examples` array):

```
^1.0.0
~1.0.0
>=1.0.0
1.x
1.0.x
1.0.0
```

The npm caret form is documented as informative because `node-semver` is the natural parser for TypeScript host implementations. The dual-form decision was ratified in analysis §7.3 and endorsed by the optimizer second pass (`suggestions-v2.md` item 4): "Resolve open decision §7.8.3 (PEP 440 vs npm caret) toward dual-form on the wire with PEP 440 canonical and npm-form documented as informative." This directly addresses the UX friction for TypeScript plugin authors that a PEP 440-only requirement would create.

The research finding `plugin-protocol-versioning/version-declaration-and-negotiation.md` confirmed that both `packaging.specifiers.SpecifierSet` (Python) and `node-semver` (Node) can parse the PEP 440 comma-separated form (`>=1.0 <2.0` with a space instead of comma is accepted by `node-semver`'s `Range` constructor), making the dual-form feasible without bespoke translators on either runtime.

### 2.3 Special cases

- **Empty string:** invalid; rejected by the schema `minLength: 1` constraint. MUST produce `plugin_manifest_invalid`.
- **Plain version with no operator** (e.g. `"1.0.0"`): treated as an exact pin — equivalent to `==1.0.0` in PEP 440 form or `=1.0.0` in npm form. Hosts MUST treat it as an exact-match requirement.
- **Bare wildcard** (`"*"`, `"1.x"`, `"1.0.x"`): npm wildcard forms. A host MUST parse these as "any version in that major/minor series". `"*"` matches any host version and SHOULD trigger a host warning recommending a bounded range.

### 2.4 Pre-release marker normalization

PEP 440 and npm use different syntax for pre-release identifiers. Hosts MUST treat the following as equivalent when evaluating compatibility:

| PEP 440 form | npm equivalent |
|---|---|
| `1.0.0a1` | `1.0.0-alpha.1` |
| `1.0.0b2` | `1.0.0-beta.2` |
| `1.0.0rc1` | `1.0.0-rc.1` |

This normalization applies to version strings appearing in both the plugin's declared range and the host's declared version. A host MUST NOT reject a pre-release declaration solely because it uses a different syntactic convention from the host's own version string.

---

## 3. Host Version Declaration

### 3.1 `host_protocol_version`

Every conforming host implementation MUST declare its own `host_protocol_version` as a single SemVer string — not a range. This value represents the one protocol version the host implements. The v1 reference Python implementation declares `"1.0.0"`.

### 3.2 `host_protocol_version_range`

Hosts MUST also declare a `host_protocol_version_range` — a SemVer range string representing the union of all plugin protocol versions this host can load. A host that maintains backward compatibility MAY declare a range wider than its own version (e.g. a host at `"1.5.0"` that still loads v1.0 plugins may declare `">=1.0,<2.0"`).

In v1, hosts MAY stub `host_protocol_version_range` as a single-version range that matches `host_protocol_version` exactly (e.g. `"==1.0.0"`). This stub is sufficient for the v1 compatibility check but SHOULD be updated when the host adds backward-compat support for an older plugin range.

### 3.3 Publication requirement

Implementations MUST publish both `host_protocol_version` and `host_protocol_version_range` through at least one of the following channels:

- A `sox version` CLI subcommand that prints both values in structured output.
- A programmatic API (Python module attribute or TypeScript export) at a documented path.
- A documented constant in the implementation's source distribution.

This publication requirement exists so that plugin authors can determine at development time whether their declared `protocol_version` range will satisfy the target host.

---

## 4. Compatibility Check Algorithm (normative)

### 4.1 Timing

The compatibility check MUST occur at plugin load time, during host startup. It MUST NOT be deferred to the first request that routes through the plugin (lazy refusal). ADR 0004 decision 3 states: "Boot-time refusal with structured error envelope. Lazy refusal is forbidden — research shows it's only acceptable when the API surface is too large to enumerate (gRPC), which is not SOX's case." The research basis is the `version-declaration-and-negotiation.md` finding on refusal granularity: "Boot-time refusal (Fastify, Terraform handshake) is preferable when the host can know the answer before user code runs. It produces clear, early, actionable errors."

This is consistent with Fastify's `fastify-plugin` behavior, which throws synchronously before `listen()` on a version mismatch ([fastify-plugin](https://github.com/fastify/fastify-plugin)).

### 4.2 Algorithm

At plugin load time the host MUST execute the following steps, in order:

1. **Parse.** Parse `manifest.spec.protocol_version` into a version range R_plugin. If parsing fails (the string is not a valid PEP 440 specifier or npm semver range), the host MUST emit `plugin_manifest_invalid` and stop. This is a distinct failure from a version mismatch.

2. **Test.** Evaluate whether `host_protocol_version` ∈ R_plugin. That is: does the host's single protocol version satisfy the plugin's declared range?

3. **Accept.** If the test passes, proceed with the remaining load-time validations — schema validation, allowlist check (see `spec/ports/middleware/03-plugin-contract.md` §6), capability orthogonality check, and ordering resolution.

4. **Reject.** If the test fails, the host MUST emit the `plugin_protocol_version_mismatch` envelope (§5) and MUST NOT proceed to load the plugin. The allowlist check, capability checks, and ordering algorithm are not reached for a version-mismatched plugin.

### 4.3 Strictness

The check is strict: a plugin declaring `^1.0.0` (equivalent to `>=1.0.0,<2.0.0`) loads on host versions `1.0.0` through `1.x.x` but MUST NOT load on host version `2.0.0`. This is the universal behavior from Fastify (`fastify: '5.x'`), VS Code (`"engines": {"vscode": "^1.74.0"}` — [VS Code Extension Manifest](https://code.visualstudio.com/api/references/extension-manifest)), and npm. SOX adopts the same semantics because the research finding confirms it is the convergent practice for cross-language plugin ecosystems: "Five of seven systems surveyed use a single version axis per artifact."

### 4.4 Pre-release version semantics

Pre-release versions follow SemVer 2.0.0 §11 precedence rules: `1.0.0-alpha < 1.0.0`. A range `>=1.0.0` does NOT satisfy a host running `1.0.0-alpha` unless the range explicitly includes pre-releases. In PEP 440 terms, `SpecifierSet(">=1.0.0")` does not match pre-releases by default; to include them, the range must be written as `>=1.0.0a0` or the evaluator must be invoked with `prereleases=True`.

Hosts running a pre-release version (e.g. `1.5.0-rc.1`) MUST evaluate plugin ranges with pre-release semantics enabled. The v1 reference implementation accomplishes this via Python's `packaging.specifiers.SpecifierSet(prereleases=True)` when `host_protocol_version` contains a pre-release identifier.

A plugin MAY explicitly opt into pre-release host versions by including a pre-release lower bound in its declared range (e.g. `>=1.0.0-alpha` or `>=1.0.0a0`). A plugin that does not opt in MUST NOT be loaded on a pre-release host if its range does not cover the host's version under SemVer §11 ordering.

---

## 5. Refusal Envelope (normative)

### 5.1 Shape

When the compatibility check (§4.2 step 4) determines a mismatch, the host MUST emit the following structured envelope. The envelope MUST be written to the host's structured log at `ERROR` level and MUST cause startup to abort with a non-zero exit code.

```json
{
  "error_code": "plugin_protocol_version_mismatch",
  "plugin_id": "<manifest.metadata.id>",
  "plugin_declares": "<manifest.spec.protocol_version verbatim>",
  "host_supports": "<host_protocol_version>",
  "remediation": "<human-readable upgrade path>"
}
```

All five fields are REQUIRED. Hosts MUST NOT omit any field. The `plugin_declares` field MUST reproduce the `spec.protocol_version` string exactly as it appears in the manifest — no normalization or canonicalization.

### 5.2 `error_code` taxonomy placement

The value `"plugin_protocol_version_mismatch"` is part of the closed seven-code error taxonomy defined in `spec/ports/middleware/03-plugin-contract.md` §6.2. That table records: "Compatibility error — upgrade plugin or pin protocol version." Hosts MUST NOT introduce synonymous error codes for this condition; the error taxonomy is closed for v1.

### 5.3 `remediation` field

The `remediation` field SHOULD name a specific action. When both the plugin's declared range and the host's version are known, the host SHOULD generate a message of the form:

- When host is newer than plugin's upper bound: `"upgrade plugin to a version supporting protocol >=<host_version>"`
- When host is older than plugin's lower bound: `"upgrade host to protocol version >=<plugin_lower_bound> or use a plugin version supporting <host_protocol_version>"`

A generic message (`"check protocol_version compatibility between plugin and host"`) is acceptable when the host cannot determine the direction of the mismatch, but SHOULD be avoided.

### 5.4 No partial load

Hosts MUST NOT proceed to instantiate the plugin factory, call `on_startup`, register capabilities, or include the plugin in the ordering graph after emitting this envelope. The plugin is treated as absent from the pipeline for all subsequent startup steps.

---

## 6. Signing and Supply-Chain Reservation (per §7.4)

### 6.1 Reserved field

The `spec/schemas/sox-plugin.schema.json` schema defines `signatures` as a **required** field under `spec`, with `type: array`. A manifest that omits `signatures` MUST be rejected with `plugin_manifest_invalid`. A manifest that includes `signatures: []` (empty array) is valid.

This reservation was established in ADR 0004 decision 2 and analysis §7.4 based on the OPA bundle precedent: "OPA shipped unsigned bundles in early versions and added Sigstore later without breaking the bundle format. The reserved `signatures: []` field is a 4-byte cost" (`suggestions-v2.md` §Q3 risk #1). The retrofit cost of adding a required field after ecosystem adoption is high; the reservation is cheap.

### 6.2 v1 enforcement

In v1, host implementations MUST validate that `signatures` is present and is a list (array). They MUST NOT enforce or evaluate the contents of the list. An empty array is the expected v1 value. A non-empty array with any item shape MUST NOT cause a load failure in v1; the host MAY log a warning that signature verification is not yet enforced.

The v1 supply-chain gate is the `--allow-plugins ID,...` CLI allowlist (or `SOX_ALLOWED_PLUGINS` environment variable), not cryptographic signature verification. See `spec/ports/middleware/03-plugin-contract.md` §6.1.

### 6.3 v1.x — hash pinning

In v1.x, hosts MAY add manifest-hash pinning: the host computes a SHA-256 of the manifest file and the plugin package content and verifies it against a host-side allowlist entry. The allowlist mechanism for hash pinning is implementation-specific in v1.x and is not normatively specified here. Plugin authors SHOULD NOT depend on a specific hash-pinning format in v1.x.

### 6.4 v2.0 — in-band signature verification

In v2.0, the `signatures` array is planned to gain a normative item shape for Sigstore/Cosign verification:

```json
{
  "algorithm": "sigstore-cosign-v1",
  "value": "<base64-encoded signature>"
}
```

Adoption of this form is gated on real-world plugin ecosystem adoption and on the stability of the Sigstore/Cosign API for non-OCI artifacts. This document reserves the field shape; it does not commit v2.0 to a specific signing scheme. Any v2.0 signing specification will be issued as a separate ADR.

---

## 7. Pre-release Markers and Migration

### 7.1 Pre-release semantics

Pre-release identifiers (`-alpha`, `-beta`, `-rc.1`, etc.) signal incompatible or experimental behavior. SemVer 2.0.0 §11 governs precedence: `1.0.0-alpha < 1.0.0-alpha.1 < 1.0.0-beta < 1.0.0`. A host MUST apply these ordering rules when evaluating whether a host version satisfies a plugin's declared range.

Default host behavior is to NOT match pre-release ranges unless the plugin explicitly opts in. A plugin that declares `protocol_version: ">=1.0.0"` does not opt in to pre-release host versions. A plugin that declares `protocol_version: ">=1.0.0-alpha"` (or `>=1.0.0a0` in PEP 440 form) explicitly opts in.

### 7.2 Migration path: host major-version bump (1.x → 2.x)

When the host releases a breaking protocol change:

1. **Pre-release window.** The host SHOULD publish pre-release versions (`2.0.0-rc.1`) before the final `2.0.0` release. Plugin authors SHOULD test against pre-releases and update their `protocol_version` declaration. A plugin compatible with both 1.x and 2.x SHOULD declare `>=1.0,<3.0`; a plugin that requires 2.x features SHOULD declare `>=2.0,<3.0`.

2. **Deprecation period.** Hosts MAY implement a deprecation warning period: a 1.x host MAY log a structured warning for plugins declaring ranges that will not satisfy a future 2.0 host (e.g. `<2.0` upper bounds). The 2.0 host MUST refuse such plugins outright via the standard mismatch envelope (§5).

3. **No automatic translation in v1.x.** SOX v1.x does not ship protocol-translation shims. This is consistent with Fastify and VS Code, which require explicit plugin re-publishing for major host bumps. Terraform's `tf5to6server` / `tf6to5server` translation approach ([Terraform protocol 5↔6 translation](https://developer.hashicorp.com/terraform/plugin/mux/translating-protocol-version-5-to-6)) is noted as precedent for v2.0+ if additive translation becomes feasible; it is explicitly deferred from v1.x scope.

4. **Plugin author guidance.** Plugin authors SHOULD bound their `protocol_version` range with a major-version ceiling. A range of `>=1.0` with no upper bound is discouraged because it silently opts the plugin into future major protocol versions that may carry breaking changes. The recommended form is `>=1.0,<2.0` as used in all three committed example manifests.

---

## 8. Worked Examples

### 8.1 Compatible plugin on current host

Plugin manifest (`sox-plugin.yaml`, drawn from `spec/schemas/examples/sox-plugin.example.interceptor.yaml`):

```yaml
spec:
  protocol_version: ">=1.0,<2.0"
```

Host:

```python
host_protocol_version = "1.0.0"
```

Evaluation: `"1.0.0"` satisfies `>=1.0,<2.0` — true. Plugin proceeds to load.

**Result:** plugin loads. No error envelope emitted.

### 8.2 Incompatible plugin (host newer than plugin's declared upper bound)

Plugin manifest:

```yaml
spec:
  protocol_version: ">=0.5,<1.0"
```

Host:

```python
host_protocol_version = "1.0.0"
```

Evaluation: `"1.0.0"` satisfies `>=0.5,<1.0` — false (`1.0.0` is not less than `1.0.0`).

**Result:** refused. Host emits:

```json
{
  "error_code": "plugin_protocol_version_mismatch",
  "plugin_id": "org.example.legacy-plugin",
  "plugin_declares": ">=0.5,<1.0",
  "host_supports": "1.0.0",
  "remediation": "upgrade plugin to a version supporting protocol >=1.0"
}
```

Host aborts startup (or, if operating in a multi-plugin load sequence, skips this plugin and continues loading others, then fails startup after completing all per-plugin checks).

### 8.3 Pre-release host with explicit plugin opt-in

Plugin manifest:

```yaml
spec:
  protocol_version: ">=1.0.0-alpha,<2.0"
```

Host:

```python
host_protocol_version = "1.0.0-rc.2"
```

Evaluation: `"1.0.0-rc.2"` satisfies `>=1.0.0-alpha,<2.0` — true, because `1.0.0-alpha < 1.0.0-rc.2 < 2.0.0` under SemVer §11 ordering. The plugin declared a pre-release lower bound, which constitutes explicit opt-in.

**Result:** plugin loads.

If the same plugin instead declared `protocol_version: ">=1.0.0,<2.0"` (no pre-release suffix on the lower bound), the host running `1.0.0-rc.2` would evaluate `"1.0.0-rc.2"` against `>=1.0.0` with pre-release semantics disabled on that clause. Under SemVer §11, `1.0.0-rc.2 < 1.0.0`, so `>=1.0.0` would NOT match `1.0.0-rc.2`. The plugin would be refused with `plugin_protocol_version_mismatch`.

---

## 9. Conformance

### 9.1 Conformance fixture targets

Conformance test cases for this document are to be authored under `spec/conformance/plugin-contract/` in the `plugin-spec-polish` engagement (B2). This section names the required fixtures so that engagement has explicit targets:

| Fixture file | Type | Assertion |
|---|---|---|
| `versioning-01-compatible-loads.yaml` | positive | Plugin with `>=1.0,<2.0` loads on host `1.0.0`; no mismatch envelope emitted |
| `versioning-02-incompatible-refused.yaml` | negative | Plugin with `>=0.5,<1.0` refused on host `1.0.0`; mismatch envelope shape asserted (all 5 fields present) |
| `versioning-03-prerelease-opt-in.yaml` | positive | Plugin with `>=1.0.0-alpha,<2.0` loads on host `1.0.0-rc.2` |
| `versioning-04-prerelease-no-opt-in.yaml` | negative | Plugin with `>=1.0.0,<2.0` refused on host `1.0.0-rc.2`; mismatch envelope emitted |

### 9.2 Conformance requirements

A host implementation is conformant with this document if and only if:

1. It accepts both PEP 440 and npm semver range forms for `spec.protocol_version` without rejecting a syntactically valid form solely because of its syntax convention. (§2.2)
2. It performs the compatibility check at plugin load time during startup, never lazily. (§4.1)
3. It applies the strict semver range check — host version must satisfy plugin's declared range. (§4.3)
4. It applies SemVer 2.0.0 §11 pre-release ordering rules. (§4.4, §7.1)
5. It emits the five-field `plugin_protocol_version_mismatch` envelope on mismatch and does not proceed to load the refused plugin. (§5)
6. It validates that `signatures` is present and is a list, but does not enforce signature contents. (§6.2)
7. It publishes `host_protocol_version` and `host_protocol_version_range` through a documented channel. (§3.3)

Cross-language conformance (Python reference implementation and any future TypeScript implementation) is required. Both MUST pass fixtures `versioning-01` through `versioning-04`.
