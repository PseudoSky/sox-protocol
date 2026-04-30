<!-- SPDX-License-Identifier: Apache-2.0 -->
# SOX Protocol Spec

**Protocol version:** 1.0 (see `VERSION`)

This directory contains the canonical, language-neutral artefacts for SOX Protocol. Every language implementation (`packages/<lang>/`) consumes from here. Nothing in `spec/` depends on any package.

---

## Directory structure

```text
spec/
├── VERSION                          # single line: "1.0"
├── README.md                        # this file
├── schemas/                         # JSON Schema 2020-12 files (wire definitions)
│   ├── event.schema.json            # enforcer input — CONTRACTS.md §3.1
│   ├── decision.schema.json         # enforcer output — CONTRACTS.md §3.3
│   ├── policy.schema.json           # operator-tunable parameters — CONTRACTS.md §4
│   ├── state.schema.json            # per-agent enforcer state — CONTRACTS.md §3.2
│   ├── message.schema.json          # a single received message element — CONTRACTS.md §5.2
│   └── tools/
│       ├── send.input.schema.json   # channels__send input — CONTRACTS.md §5.1
│       ├── send.output.schema.json  # channels__send output — CONTRACTS.md §5.1
│       ├── recv.input.schema.json   # channels__recv input — CONTRACTS.md §5.2
│       ├── recv.output.schema.json  # channels__recv output — CONTRACTS.md §5.2
│       ├── subscribe.input.schema.json   # channels__subscribe input — CONTRACTS.md §5.3
│       ├── subscribe.output.schema.json  # channels__subscribe output — CONTRACTS.md §5.3
│       └── list-channels.output.schema.json  # channels__list_channels output — CONTRACTS.md §5.4
├── discipline/                      # canonical discipline markdown
│   ├── discipline.md                # full discipline with {{placeholder}} tokens
│   └── examples/                   # (populated at Milestone 4)
│       ├── send-and-continue.md
│       ├── reconciliation.md
│       └── group-broadcast.md
├── ports/                           # port behaviour contracts (prose, language-neutral)
│   ├── backing-store.md             # BackingStore port (south / driven)
│   ├── runtime-discipline-renderer.md  # DisciplineRenderer port (north / driving)
│   └── runtime-enforcer-binding.md    # EnforcerBinding port (north / driving)
└── conformance/                     # (populated at Milestone 6)
    ├── README.md
    ├── docker-compose.yml
    ├── scenarios/
    └── runner/run.sh
```

---

## How implementations consume this spec

Each language package (`packages/<lang>/`) consumes the spec in three ways, as described in `docs/IMPLEMENTATION-PLAN.md §1.2`:

### 1. Build-time codegen from schemas

JSON Schema files under `spec/schemas/` are the authoritative wire definitions. Language packages generate native types from them at build time:

- **Python:** `datamodel-code-generator` generates dataclasses from `spec/schemas/*.schema.json`. The generated files are committed and regenerated on every release.
- **TypeScript:** `json-schema-to-typescript` generates TypeScript interfaces.
- **Rust:** `schemars` or hand-written types tested for equivalence.

The MCP server validates incoming and outgoing tool arguments against `spec/schemas/tools/*.schema.json` at startup and fails fast if the implementation has drifted from the spec.

To regenerate types in the Python package (example for the reference Python implementation: `packages/python/src/sox_protocol/core/enforcer/generated_types.py`):

```sh
# from repo root
datamodel-codegen \
  --input spec/schemas/ \
  --output <output-path> \
  --input-file-type jsonschema
```

### 2. Install-time templating from the discipline document

`spec/discipline/discipline.md` uses `{{placeholder}}` tokens for all tool name references. Runtime adapter installers read this file and substitute the tokens with concrete tool names before writing the result to the runtime's prompt surface.

The four tokens and their substitutions:

| Token | Substituted with (example — Claude Code) |
|---|---|
| `{{send_tool}}` | `mcp__sox__channels__send` |
| `{{recv_tool}}` | `mcp__sox__channels__recv` |
| `{{subscribe_tool}}` | `mcp__sox__channels__subscribe` |
| `{{list_tool}}` | `mcp__sox__channels__list_channels` |

Never substitute tokens in-place in `spec/discipline/discipline.md`. Substitution happens at install time in the target project; the spec source must remain token-bearing.

Port behaviour contracts in `spec/ports/*.md` are prose-only. Implementations bind them in language-specific idioms (Python: ABC; TypeScript: interface; Rust: trait). The prose contract is normative; if a language binding introduces additional semantics, the prose wins.

### 3. Runtime conformance against the conformance suite

At CI time, each package's conformance runner spins up its MCP server and runs `spec/conformance/scenarios/*.json` against it via `spec/conformance/runner/run.sh`. Passing all scenarios is what makes an implementation "SOX v1.0-compliant."

The conformance suite runs against the MCP wire interface only — it does not link against any package source. This makes it reusable across all language ports without modification.

---

## Adding a new language port

1. Read `spec/ports/backing-store.md`, `spec/ports/runtime-discipline-renderer.md`, and `spec/ports/runtime-enforcer-binding.md` to understand the three ports you must implement.
2. Generate or hand-write native types from `spec/schemas/`.
3. Implement all five `BackingStore` methods per the prose contract.
4. Implement `DisciplineRenderer` and `EnforcerBinding` per their prose contracts.
5. Wire the MCP server using the four tool schemas in `spec/schemas/tools/`.
6. Run `spec/conformance/runner/run.sh` against your implementation and pass all scenarios.
7. See `packages/typescript/README.md` or `packages/rust/README.md` for the contribution process.

---

## Versioning

The protocol version is in `spec/VERSION`. Schema files include a `schema_version` property with a `"1.0"` const. Bump policy follows CONTRACTS.md §8:

- **Patch** (e.g. 1.0 → 1.0.1): clarifications only, no wire change.
- **Minor** (e.g. 1.0 → 1.1): backward-compatible additions (new optional fields, new tools).
- **Major** (e.g. 1.0 → 2.0): breaking change to wire format or behaviour semantics.

Spec changes require a PR against `spec/` with `spec-lint.yml` passing and at least one implementation updated to match. See `CONTRIBUTING.md`.
