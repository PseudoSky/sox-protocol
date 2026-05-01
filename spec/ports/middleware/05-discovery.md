<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Plugin Discovery and Registration

**Version:** 1.0
**Status:** Normative
**Scope:** Language-neutral. This document specifies how SOX hosts discover, load, and register plugins at startup — covering Python entry-points, Node `package.json#sox`, programmatic in-tree registration, the production allowlist mechanism, and the `--no-discovery` flag.

**Related:**
- `spec/ports/middleware/03-plugin-contract.md` — allowlist enforcement (§6), manifest validation (§5), error taxonomy (§6.2); this document is referenced as "described fully in 05-discovery.md" by §5 of that document
- `spec/ports/middleware/04-manifest.md` — the `sox-plugin.yaml` manifest that discovery locates and loads
- `spec/ports/middleware/06-versioning.md` — version negotiation that runs immediately after manifest validation
- `docs/adr/0004-plugin-architecture.md` — decisions 4 (discovery mechanism) and 6 (configuration); this document is the normative body of decision 4

---

## 1. Purpose and Design Rationale

Plugin discovery is the process by which a SOX host locates installed plugins at startup, validates their manifests, and registers their factories into the pipeline before the first request is served. Discovery is a **startup-time** operation: no discovery occurs during request handling. The plugin registry is frozen after startup (see `03-plugin-contract.md` §9.1).

Three discovery paths are defined, each targeting a different deployment and authoring context:

1. **Python entry-points** — the standard mechanism for installed Python packages (`importlib.metadata`).
2. **Node `package.json#sox`** — the standard mechanism for installed Node packages.
3. **Programmatic (`register_plugin`)** — for in-tree composition, built-in plugins, and test doubles.

All three paths converge on the same post-discovery pipeline: manifest validation → version negotiation → allowlist check → capability resolution → ordering computation → registry freeze. No path bypasses any step.

The entry-point hint (the module path and factory function name) is intentionally **absent from `sox-plugin.yaml`**. It lives in language-specific package metadata. This separation keeps the manifest language-neutral and avoids the cross-language manifest mutation that would be required if entry points were in the manifest body. ADR 0004 §2 and `04-manifest.md` §7 document the full rationale and the Backstage/Envoy/OPA precedents.

---

## 2. Python Discovery via `importlib.metadata`

### 2.1 Entry-Point Group

The host MUST scan the entry-point group `"sox_protocol.plugins"` using:

```python
from importlib.metadata import entry_points

discovered = entry_points(group="sox_protocol.plugins")
```

Each discovered entry point represents one plugin candidate. The entry point's `name` attribute MUST match the `metadata.id` field in the corresponding `sox-plugin.yaml` manifest. If the names do not match, the host MUST emit `plugin_manifest_invalid` and skip the plugin.

### 2.2 `pyproject.toml` Declaration

A Python plugin author declares the entry point in `pyproject.toml`:

```toml
[project.entry-points."sox_protocol.plugins"]
"org.example.sox-jwt-auth" = "my_jwt_auth_plugin:make_plugin"
```

- The key (`"org.example.sox-jwt-auth"`) MUST exactly match `metadata.id` in `sox-plugin.yaml`.
- The value (`"my_jwt_auth_plugin:make_plugin"`) is the module-and-callable reference. The callable is the **plugin factory**: a function that returns a plugin instance conforming to the kind contract in `03-plugin-contract.md` §2.
- The `sox-plugin.yaml` manifest MUST be locatable from the installed distribution. The host MUST look for it at the path declared by the distribution's `sox_manifest` metadata field, or fall back to scanning the distribution's package directory for a file named `sox-plugin.yaml`.

### 2.3 Manifest Location for Python Packages

After loading the entry point, the host MUST locate and load the manifest. The resolution order is:

1. If the distribution's metadata includes a `SOX-Manifest` field (a custom metadata key), use that path as the manifest location.
2. Otherwise, search the distribution's top-level package directory for a file named `sox-plugin.yaml`.
3. If no manifest is found, the host MUST emit `plugin_manifest_invalid` (manifest absent is a build error) and skip the plugin.

Once located, the manifest file is parsed as YAML and validated against `spec/schemas/sox-plugin.schema.json`. Validation MUST succeed before the factory callable is imported. See `04-manifest.md` §6.

### 2.4 Error Handling for Python Discovery

| Condition | Error code | Behaviour |
|---|---|---|
| Entry point found, manifest absent | `plugin_manifest_invalid` | Skip plugin; log error |
| Entry point found, manifest fails schema validation | `plugin_manifest_invalid` | Skip plugin; log error |
| Entry point found, factory import fails (ImportError) | `plugin_not_found` | Skip plugin; log error |
| Entry point id does not match manifest `metadata.id` | `plugin_manifest_invalid` | Skip plugin; log error |
| Entry point found, not in allowlist | `plugin_not_allowed` | Skip plugin; log at WARNING level |

---

## 3. Node Discovery via `package.json#sox`

### 3.1 Scan Mechanism

The host MUST scan the top-level `node_modules/` directory at startup. For each immediate subdirectory (or scoped subdirectory under `@org/`), the host reads `package.json`. If a `package.json` contains a top-level `"sox"` key, the package is a plugin candidate.

```json
{
  "name": "@myorg/sox-jwt-auth",
  "version": "1.0.0",
  "sox": "./dist/sox-plugin.yaml"
}
```

The value of the `"sox"` key is a **relative path** from the package root to the `sox-plugin.yaml` manifest file.

### 3.2 Manifest Loading for Node Packages

The host resolves the manifest path relative to the `package.json` file's directory, reads the YAML file, and validates it against `spec/schemas/sox-plugin.schema.json`. The `package.json#name` field is informative only; the authoritative plugin id is `metadata.id` in `sox-plugin.yaml`.

The factory callable is loaded via the `package.json#exports` map. The host MUST look for a `"./plugin"` or `"."` export that resolves to the factory function. The factory function MUST be the default export of the resolved module.

### 3.3 Scoped Packages

Scoped packages (`@org/package-name`) are supported. The host MUST scan `node_modules/@<scope>/*/package.json` in addition to `node_modules/*/package.json`.

### 3.4 Error Handling for Node Discovery

| Condition | Error code | Behaviour |
|---|---|---|
| `"sox"` key present, manifest path does not resolve | `plugin_manifest_invalid` | Skip plugin; log error |
| Manifest fails schema validation | `plugin_manifest_invalid` | Skip plugin; log error |
| Factory module import fails | `plugin_not_found` | Skip plugin; log error |
| Package not in allowlist | `plugin_not_allowed` | Skip plugin; log at WARNING level |

---

## 4. Programmatic Registration via `register_plugin`

### 4.1 API

The host MUST expose a programmatic registration API for in-tree composition, built-in plugins, and test doubles:

```python
# Python signature
def register_plugin(
    name: str,
    factory: Callable,
    manifest: dict | None = None,
) -> None: ...
```

```typescript
// TypeScript signature
function registerPlugin(
  name: string,
  factory: PluginFactory,
  manifest?: SoxPluginManifest,
): void;
```

- `name` MUST match `metadata.id` in the manifest (or in an inline manifest dict/object if `manifest` is provided).
- `factory` is the plugin factory callable, equivalent to the entry-point callable in §2 and §3.
- `manifest` is optional. When provided, it is validated against `spec/schemas/sox-plugin.schema.json`. When absent, the host MUST locate the manifest via the same resolution logic as §2.3.

`register_plugin` MUST be called before the registry is frozen. Calling it after startup is complete MUST raise a `RegistryFrozenError` (or equivalent) — the static-composition constraint in `03-plugin-contract.md` §9.1.

### 4.2 Allowlist Behaviour for Programmatic Registration

Programmatic registration bypasses entry-point scanning but is **still subject to allowlist enforcement**. A plugin registered via `register_plugin` whose `name` is not in the allowlist MUST be treated the same as a discovered-but-not-allowlisted entry-point plugin: `plugin_not_allowed` in production mode; a WARNING in development mode.

This ensures that test doubles accidentally included in a production build cannot bypass the supply-chain gate.

### 4.3 Built-in Plugins

The built-in default-chain units (`namespace_resolver`, `auth`, `rate_limit`, `schema_validator`, `idempotency`, `store_dispatch`, `audit_log`) are registered via `register_plugin` during host startup before external discovery runs. Their manifests are inline dicts embedded in the host source. They are always present in the allowlist implicitly — built-in plugins MUST NOT be subject to the external allowlist check.

---

## 5. Allowlist Mechanism

### 5.1 CLI Flag and Environment Variable

The host MUST support two equivalent mechanisms for declaring the production allowlist:

- **`--allow-plugins ID,ID,...`** — CLI flag; comma-separated list of `metadata.id` values.
- **`SOX_ALLOWED_PLUGINS=ID,ID,...`** — environment variable; same format.

When both are provided, the CLI flag takes precedence over the environment variable. Both accept zero-or-more comma-separated ids. Whitespace around commas is permitted and MUST be trimmed.

### 5.2 Production Mode Behaviour (`SOX_ENV=production`)

In production mode, the allowlist is a strict filter:

- An empty allowlist (`--allow-plugins ""` or `SOX_ALLOWED_PLUGINS=""`) MUST cause the host to load **no external plugins**. Built-in plugins are unaffected.
- A non-empty allowlist MUST be treated as an exact filter. Any discovered plugin whose `metadata.id` is not in the allowlist MUST be silently skipped with a `plugin_not_allowed` log entry at WARNING level.
- Any plugin id in the allowlist that is not discovered MUST produce `plugin_not_found` at ERROR level. This is a deployment error: the operator declared a plugin they expected to be installed, and it is absent.

The distinction between these two cases is operationally significant: a `plugin_not_allowed` entry indicates a config error (the operator should add the id to the allowlist); a `plugin_not_found` entry indicates a deployment error (the plugin package is not installed).

### 5.3 Development Mode Behaviour (`SOX_ENV=development` or unset)

In development mode, all discovered plugins are loaded regardless of the allowlist:

- If an allowlist is provided, the host MUST emit a `stderr` WARNING for each discovered plugin not in the allowlist (informational; not a load failure).
- If no allowlist is provided, all discovered plugins are loaded without warning. This is the expected behaviour for local development.
- Production-mode strictness (`plugin_not_found` for allowlisted-but-missing plugins) does not apply in development mode.

### 5.4 Rationale

The allowlist exists because `load_entry_points` is a **code-execution boundary**. Any Python package installed in the same environment that declares an `"sox_protocol.plugins"` entry point will be loaded by an unconstrained host. In a production container, this includes any package that was transitively installed as a dependency of an unrelated library.

The allowlist converts discovery from "load everything we find" to "load only what the operator explicitly consented to." This is the same gate that Envoy uses for its xDS configuration sources and that OPA uses for its bundle loaders. ADR 0004 decision 4 and `03-plugin-contract.md` §6.1 provide additional context.

---

## 6. `--no-discovery` Flag

### 6.1 Behaviour

The host MUST support a `--no-discovery` flag (and equivalent `SOX_NO_DISCOVERY=1` environment variable). When set:

- Entry-point scanning (§2) and `node_modules` scanning (§3) MUST NOT occur.
- Only programmatically registered plugins (§4) are loaded.
- Built-in plugins are unaffected.

### 6.2 Use Cases

`--no-discovery` is intended for two contexts:

**Security audits:** An operator who wants to verify that a deployment loads exactly the plugins they expect — no more, no fewer — can start the host with `--no-discovery` and verify that all desired plugins are registered programmatically (via test wiring or a startup script). This eliminates the variable introduced by the installed package set.

**Test isolation:** The conformance suite and unit tests SHOULD use `--no-discovery` to prevent test environments from accidentally loading production plugins that happen to be installed in the CI Python environment. Combined with explicit `register_plugin` calls for the test doubles needed by each fixture, this produces hermetic test runs.

### 6.3 Interaction with Allowlist

`--no-discovery` and `--allow-plugins` are orthogonal:

- `--no-discovery` disables scanning; `--allow-plugins` filters what scanning finds.
- When both are set, `--no-discovery` takes full effect: no scanning occurs; the allowlist has no external plugins to filter.
- Programmatically registered plugins are still subject to allowlist enforcement (§4.2) regardless of `--no-discovery`.

---

## 7. Post-Discovery Pipeline

After all three discovery paths have completed (or been skipped via `--no-discovery`), the host MUST execute the following steps in order before the registry is frozen:

1. **Manifest validation** — validate each candidate manifest against `spec/schemas/sox-plugin.schema.json`. Reject failures with `plugin_manifest_invalid`.
2. **Version negotiation** — for each valid manifest, execute the compatibility algorithm in `06-versioning.md` §4. Reject mismatches with `plugin_protocol_version_mismatch`.
3. **Allowlist check** — in production mode, filter candidates against the allowlist. Reject with `plugin_not_allowed` or `plugin_not_found` as appropriate.
4. **Capability conflict check** — for each passing candidate, validate capability flag orthogonality (`observe_only` + `may_short_circuit`). Reject conflicts with `plugin_capability_conflict`.
5. **Requirements resolution** — resolve each plugin's `requires` entries against the `plugin_capabilities` of all passing candidates. Reject unresolved requirements with `plugin_requirement_unmet`.
6. **Ordering computation** — build the DAG from `must_run_before` and `must_run_after` constraints across all passing candidates. Compute the stable Kahn's sort. Reject cycles with `plugin_ordering_cycle`. Cache the result.
7. **Factory instantiation** — call each factory in the computed order. Call `on_startup` for provider-kind plugins. Reject startup failures with the applicable error code.
8. **Registry freeze** — mark the registry as frozen. All subsequent `register_plugin` calls MUST raise `RegistryFrozenError`.

This pipeline is described in summary in `03-plugin-contract.md` §5. The authoritative ordering is here.

All failures in steps 1–7 MUST cause the host to abort startup with a non-zero exit code. A host that proceeds with a partially-initialised plugin set is not conformant.

---

## 8. Startup Log Requirements

The host MUST emit a structured startup log entry for each loaded plugin, and a summary entry when the registry is frozen:

```
[sox] loaded plugin: org.example.sox-jwt-auth (kind=interceptor, protocol_version=>=1.0,<2.0)
[sox] loaded plugin: io.sox.schema-strict (kind=transformer, protocol_version=>=1.0,<2.0)
[sox] plugin registry frozen: 2 external plugins + 7 built-in slots loaded
[sox] pipeline order: namespace_resolver → auth [org.example.sox-jwt-auth] → rate_limit → schema_validator [io.sox.schema-strict] → idempotency → store_dispatch → audit_log
```

The pipeline order log line MUST name each slot and, in brackets, the plugin id if a third-party plugin fills that slot. This provides operators with a single line that describes the exact pipeline the running host will execute.

Failures MUST be logged at ERROR level with the applicable error code and the plugin id. All seven error codes defined in `03-plugin-contract.md` §6.2 MUST appear in log output verbatim so that operators can grep for them in structured logging systems.
