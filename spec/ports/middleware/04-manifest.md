<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Plugin Manifest Format

**Version:** 1.0
**Status:** Normative
**Scope:** Language-neutral. This document specifies the `sox-plugin.yaml` manifest envelope: its required and optional fields, the machine-readable schema, and the three committed example manifests.

**Related:**
- `spec/ports/middleware/03-plugin-contract.md` — plugin kinds, capability flags, failure semantics, and the full contract that the manifest's `spec.*` fields declare conformance to
- `spec/ports/middleware/05-discovery.md` — how the host locates and loads manifests at startup
- `spec/ports/middleware/06-versioning.md` — `spec.protocol_version` field; dual wire forms, compatibility algorithm
- `spec/schemas/sox-plugin.schema.json` — machine-readable JSON Schema 2020-12 companion; authoritative for field types and constraints
- `spec/schemas/examples/sox-plugin.example.interceptor.yaml` — concrete interceptor manifest (JWT auth)
- `spec/schemas/examples/sox-plugin.example.transformer.yaml` — concrete transformer manifest (schema-strict body validator)
- `spec/schemas/examples/sox-plugin.example.provider.yaml` — concrete provider manifest (Redis pool)
- `docs/adr/0004-plugin-architecture.md` — decisions 1 (kind taxonomy), 2 (manifest format), 7 (configuration)

---

## 1. Purpose

A plugin manifest is a **language-neutral YAML file** named `sox-plugin.yaml` that every SOX plugin MUST ship alongside its language-specific package. The manifest declares:

- What the plugin is (its stable identifier, human-readable name, and version).
- What kind of plugin it is (interceptor, transformer, provider, or hook) and what capability flags it asserts.
- Which protocol versions of the SOX host it is compatible with.
- What operations or lifecycle phases it applies to.
- What ordering constraints it requires relative to other plugins.
- What capabilities it provides to, and requires from, the plugin registry.

The manifest is deliberately **language-neutral**. It does not contain any entry-point hints (module paths, function names). Those belong in language-specific package metadata (`pyproject.toml` for Python, `package.json` for Node). See `05-discovery.md` §2 for the rationale and the two-layer authoring model.

The host MUST validate every discovered manifest against `spec/schemas/sox-plugin.schema.json` before attempting to load the plugin. A manifest that fails schema validation MUST produce `plugin_manifest_invalid` and MUST NOT proceed to factory instantiation. See `03-plugin-contract.md` §6.2 for the full error taxonomy.

---

## 2. Envelope Shape

Every `sox-plugin.yaml` MUST be a YAML mapping with the following top-level structure, drawn from the Backstage RFC 18372 `catalog-info.yaml` envelope pattern:

```yaml
apiVersion: sox.dev/v1
kind: SoxPlugin
metadata:
  id: <reverse-DNS string>        # required — stable unique identifier
  name: <human-readable string>   # required — display name
  version: <semver string>        # required — plugin's own release version
  description: <string>           # optional — one-sentence description
  tags: [<string>, ...]           # optional — discovery tags

spec:
  plugin_kind: <kind>             # required — interceptor | transformer | provider | hook
  protocol_version: <range>       # required — PEP 440 or npm semver range
  plugin_capabilities: [...]      # required (may be empty list)
  applies_to: [...]               # optional — operation scope filter
  must_run_before: [...]          # optional — ordering constraint
  must_run_after: [...]           # optional — ordering constraint
  observe_only: <bool>            # optional — interceptor capability flag
  may_short_circuit: <bool>       # optional — interceptor capability flag
  signatures: []                  # required — v1: always empty list; reserved for v1.x signing
```

All fields listed as "required" MUST be present. A manifest omitting any required field MUST be rejected with `plugin_manifest_invalid` during schema validation.

---

## 3. `metadata` Fields

### 3.1 `metadata.id` — Plugin Identifier

The `id` field is a **reverse-DNS string** that uniquely identifies the plugin across the ecosystem. It MUST be ASCII-only or NFC-normalised Unicode. The schema regex constrains `id` to the pattern `^[a-zA-Z][a-zA-Z0-9._-]*$`.

Examples: `org.example.sox-jwt-auth`, `io.sox.schema-strict`, `com.myco.sox-provider-redis-pool`.

The `id` value is used as the basis for:

- The allowlist check (`--allow-plugins ID,...`; see `03-plugin-contract.md` §6.1).
- Environment variable canonicalization for plugin configuration (`03-plugin-contract.md` §7.2).
- The entry point name in `pyproject.toml` (MUST match `metadata.id`; see `05-discovery.md` §2).
- `pipeline_trace` records (each record's `plugin_id` field echoes `metadata.id`).

Plugin id changes are **breaking changes**. Once a plugin is published, its `id` MUST be considered stable. Operators who pin plugin ids in `--allow-plugins` will have their configs broken by an id change.

### 3.2 `metadata.version`

The plugin's own release version, as a SemVer 2.0.0 string. This is the plugin author's release tag and carries no host-compatibility semantics. The host does not evaluate this field during version negotiation; that is the role of `spec.protocol_version`. See `06-versioning.md` §1 (Out of scope) for the explicit distinction.

### 3.3 `metadata.name` and `metadata.description`

Human-readable fields. `name` MUST be a non-empty string. `description` is optional but RECOMMENDED. These fields are used in host startup logs, admin API responses, and error messages.

---

## 4. `spec` Fields

### 4.1 `spec.plugin_kind`

One of the four kind values: `interceptor`, `transformer`, `provider`, `hook`. Any other value MUST cause `plugin_manifest_invalid`. See `03-plugin-contract.md` §2 for the full contract of each kind.

### 4.2 `spec.protocol_version`

A SemVer range string in either PEP 440 form (`>=1.0,<2.0`) or npm caret form (`^1.0.0`). Required. See `06-versioning.md` for the full specification of this field, including the dual wire forms, compatibility algorithm, and pre-release handling.

The recommended form for v1 plugins is `>=1.0,<2.0`, matching all three committed example manifests.

### 4.3 `spec.plugin_capabilities`

An array of capability strings and/or capability flag objects. REQUIRED; the empty list `[]` is a valid value for plugins that provide nothing and require nothing.

The array MAY contain:

- **Free-form capability strings** (`"auth.method"`, `"rate_limit.backend"`) — what the plugin provides to the registry. Other plugins that declare matching strings in their `requires` field will receive this plugin's resource handle.
- **Capability flag objects** — `{"observe_only": true}` or `{"may_short_circuit": true}` for interceptor-kind plugins.

Orthogonality constraint: `observe_only: true` and `may_short_circuit: true` MUST NOT both appear in the same manifest. This combination is a `plugin_capability_conflict` startup error. See `03-plugin-contract.md` §2.3.

### 4.4 `spec.applies_to`

Optional array of operation names (`send`, `recv`, `subscribe`, `list_channels`) or lifecycle phase names (`startup`, `shutdown`). When present, the plugin is invoked only for the listed operations or phases. When absent, the plugin applies to all operations and phases.

This field enables scoped plugins: a plugin that only needs to run for `send` operations should declare `applies_to: ["send"]` so the host can skip invoking it for `recv` and `subscribe` calls. This is a performance optimisation, not a security boundary.

For provider-kind plugins, `applies_to` is irrelevant; the host MUST ignore it. See `03-plugin-contract.md` §2.2.1.

### 4.5 `spec.must_run_before` and `spec.must_run_after`

Optional arrays of plugin ids or capability strings. These declare ordering constraints that the host resolves via the Kahn's topological sort algorithm described in `03-plugin-contract.md` §4.

A plugin MAY reference capability strings rather than specific plugin ids in these fields; the host resolves the capability string to whichever loaded plugin provides it. This decoupling is intentional: a plugin that must run before persistence should declare `must_run_before: ["store_dispatch"]`, not hard-code the persistence plugin's id.

A cycle in the ordering graph is a `plugin_ordering_cycle` startup error. See `03-plugin-contract.md` §4.2.

### 4.6 `spec.signatures`

REQUIRED field. In v1, the value MUST be `[]` (empty array). The host MUST validate that `signatures` is present and is a list, but MUST NOT enforce or evaluate its contents in v1.

This field is reserved for v1.x manifest-hash pinning and v2.0 in-band signature verification (Sigstore/Cosign). See `06-versioning.md` §6 for the full reservation and evolution plan.

---

## 5. Complete Manifest Examples

The three committed example manifests in `spec/schemas/examples/` illustrate the envelope in use.

### 5.1 Interceptor — JWT Auth (`sox-plugin.example.interceptor.yaml`)

Key fields:
- `plugin_kind: interceptor`
- `may_short_circuit: true` — this plugin halts the chain when credentials are invalid
- `observe_only: false`
- `protocol_version: ">=1.0,<2.0"`
- `must_run_after: ["namespace_resolver"]` — runs after namespace is resolved; before all other units per the `DEFAULT_ORDER` contract
- `applies_to: ["send", "recv", "subscribe"]`

This manifest is the canonical example of the `kind: guard` migration: a guard is an interceptor with `may_short_circuit: true`. See `03-plugin-contract.md` §2.3 migration table.

### 5.2 Transformer — Schema-Strict Body Validator (`sox-plugin.example.transformer.yaml`)

Key fields:
- `plugin_kind: transformer`
- `protocol_version: ">=1.0,<2.0"`
- `must_run_after: ["auth"]` — runs after identity is confirmed; only validates authenticated sends
- `applies_to: ["send"]`

This is the reference plugin targeted by engagement P5 (`reference-plugins`). Its purpose is to replace the built-in `_validate_body` call in `routes.py` with a proper pipeline unit.

### 5.3 Provider — Redis Pool (`sox-plugin.example.provider.yaml`)

Key fields:
- `plugin_kind: provider`
- `plugin_capabilities: ["backing_store.redis"]` — registers the Redis pool resource under this capability string
- `protocol_version: ">=1.0,<2.0"`
- Configuration exposed under `SOX_PLUGIN_COM_MYCO_SOX_PROVIDER_REDIS_POOL_*` per the canonicalization rule in `03-plugin-contract.md` §7.2

This manifest illustrates the provider lifecycle: the host calls the factory once at startup, invokes `on_startup`, and makes the resource available to any plugin declaring `requires: ["backing_store.redis"]`.

---

## 6. Schema Validation

The host MUST validate every manifest against `spec/schemas/sox-plugin.schema.json` using JSON Schema 2020-12 semantics. Validation MUST occur before any factory instantiation, `on_startup` call, capability registration, or ordering-graph insertion.

The schema enforces:

- Required field presence (`apiVersion`, `kind`, `metadata.id`, `metadata.name`, `metadata.version`, `spec.plugin_kind`, `spec.protocol_version`, `spec.plugin_capabilities`, `spec.signatures`).
- `plugin_kind` enum constraint.
- `protocol_version` pattern constraints (PEP 440 or npm semver form via `anyOf`).
- `metadata.id` format constraint (ASCII reverse-DNS pattern).
- `observe_only` + `may_short_circuit` orthogonality via `if/then` constraint.

A manifest that passes schema validation is not necessarily semantically correct; the host MUST additionally perform the runtime checks described in `03-plugin-contract.md` §2.3 (capability orthogonality), §4 (ordering cycle detection), and §6 (allowlist check).

---

## 7. Two-File Authoring Model

Plugin authors maintain two files:

1. **`sox-plugin.yaml`** — the language-neutral manifest described in this document.
2. **Language-specific package metadata** — `pyproject.toml` (Python) or `package.json` (Node) — containing the entry-point hint that maps the plugin id to the factory callable.

The entry-point hint is deliberately absent from the manifest. See `05-discovery.md` §2.1 for the full rationale. In summary: embedding entry-point hints in the manifest would bake language-specific semantics (module paths, export names) into a language-neutral document, creating the multi-language rot that Backstage, Envoy, and OPA all avoided by separating these layers.

The authoring story for a Python plugin:

```
my-plugin/
├── pyproject.toml          # 3-line addition under [project.entry-points]
├── sox-plugin.yaml         # this document; language-neutral
└── src/
    └── my_plugin/
        └── __init__.py     # make_plugin factory function
```

The `pyproject.toml` entry:

```toml
[project.entry-points."sox_protocol.plugins"]
"org.example.my-plugin" = "my_plugin:make_plugin"
```

The entry point name (`org.example.my-plugin`) MUST exactly match `metadata.id` in `sox-plugin.yaml`. The host uses this match to associate the factory callable with the manifest.
