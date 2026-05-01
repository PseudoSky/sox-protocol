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
├── schemas/                         # JSON Schema 2020-12 files
│   ├── event.schema.json            # enforcer input — CONTRACTS.md §3.1
│   ├── decision.schema.json         # enforcer output — CONTRACTS.md §3.3
│   ├── policy.schema.json           # operator-tunable parameters — CONTRACTS.md §4
│   ├── state.schema.json            # per-agent enforcer state — CONTRACTS.md §3.2
│   ├── message.schema.json          # canonical wire envelope — spec/protocol.md §Message envelope shape
│   └── tools/
│       ├── send.input.schema.json   # channels__send input (MCP stdio binding)
│       ├── send.output.schema.json  # channels__send output (MCP stdio binding)
│       ├── recv.input.schema.json   # channels__recv input (MCP stdio binding)
│       ├── recv.output.schema.json  # channels__recv output (MCP stdio binding)
│       ├── subscribe.input.schema.json   # channels__subscribe input (MCP stdio binding)
│       ├── subscribe.output.schema.json  # channels__subscribe output (MCP stdio binding)
│       └── list-channels.output.schema.json  # channels__list_channels output (MCP stdio binding)
├── operations/                      # JSON Schema 2020-12 files for all 15 v1 operations
│   ├── send.input.schema.json       # adapter-neutral send input
│   ├── send.output.schema.json      # adapter-neutral send output
│   ├── recv.input.schema.json       # adapter-neutral recv input
│   ├── recv.output.schema.json      # adapter-neutral recv output
│   └── list_channels.output.schema.json  # adapter-neutral list_channels output
├── primitives/                      # normative prose for each protocol primitive
│   ├── channels.md
│   ├── groups.md
│   ├── dms.md
│   ├── threads.md
│   ├── presence.md
│   ├── ack-nack.md
│   ├── pending-state.md
│   ├── sequence-numbers.md
│   └── trace-ids.md
├── discipline/                      # canonical discipline markdown
│   ├── discipline.md                # full discipline with {{placeholder}} tokens
│   └── examples/                   # worked examples
│       ├── send-and-continue.md
│       ├── reconciliation.md
│       └── group-broadcast.md
├── ports/                           # port behaviour contracts (prose, language-neutral)
│   ├── backing-store.md             # BackingStore port (south / driven)
│   ├── transport.md                 # Transport port (wire / HTTP)
│   ├── identity.md                  # Identity port (auth)
│   ├── middleware.md                # Redirect stub → see middleware/ directory below
│   ├── middleware/                  # Middleware port (pipeline + plugin architecture) — 8 files
│   │   ├── README.md                # Directory index and reading guide
│   │   ├── 01-context.md            # MiddlewareContext shape and structural invariants
│   │   ├── 02-pipeline.md           # Pipeline flow, short-circuit, mutability, error handling
│   │   ├── 03-plugin-contract.md    # Plugin kinds, failure semantics, ordering, allowlist, observability
│   │   ├── 04-manifest.md           # sox-plugin.yaml envelope; schema and example references
│   │   ├── 05-discovery.md          # Python entry-points, Node package.json#sox, register_plugin
│   │   ├── 06-versioning.md         # protocol_version dual wire forms; refusal envelope; signing
│   │   ├── 07-default-chain.md      # DEFAULT_ORDER constant; slot specs; schema_validator contract
│   │   └── 08-conformance.md        # Conformance checklists; plugin-contract/ fixture pointers
│   ├── runtime-discipline-renderer.md  # DisciplineRenderer port (north / driving)
│   └── runtime-enforcer-binding.md    # EnforcerBinding port (north / driving)
└── conformance/                     # language-neutral conformance test harness
    ├── README.md
    ├── docker-compose.yml
    ├── scenarios/
    └── runner/run.sh
```

---

## Two-tier schema layout

`spec/schemas/` and `spec/operations/` describe the same operations from two perspectives. **Both are authoritative for their respective binding.**

### `spec/schemas/`

Contains two categories of JSON Schema files:

1. **Core type schemas** (`event.schema.json`, `decision.schema.json`, `policy.schema.json`, `state.schema.json`, `message.schema.json`) — define the enforcer internals and the canonical wire envelope for stored messages. All language implementations generate native types from these at build time.

2. **MCP tool I/O schemas** (`spec/schemas/tools/*.schema.json`) — define the exact input and output shapes for the four stdio MCP tool calls (`channels__send`, `channels__recv`, `channels__subscribe`, `channels__list_channels`). The MCP server validates incoming and outgoing tool arguments against these schemas at startup and fails fast if the implementation has drifted from the spec. Tool names use MCP naming conventions (`channels__send`, etc.).

### `spec/operations/`

Contains schemas for all 15 v1 operations using adapter-neutral naming conventions (`send`, `recv`, `list_channels`, etc.). These are the source for:

- The HTTP transport binding
- The language-neutral conformance suite (`spec/conformance/`)
- Future language ports that expose additional transports

### Relationship between the two directories

`spec/schemas/tools/` and `spec/operations/` are kept in sync. When a field is added or changed, both must be updated together. `spec/schemas/tools/` is the validation source for the MCP stdio server. `spec/operations/` is the validation source for the HTTP transport and conformance suite.

---

## How implementations consume this spec

Each language package (`packages/<lang>/`) consumes the spec in three ways, as described in `docs/IMPLEMENTATION-PLAN.md §1.2`:

### 1. Build-time codegen from schemas

JSON Schema files under `spec/schemas/` are the source for native type generation:

- **Python:** `datamodel-code-generator` generates dataclasses from `spec/schemas/*.schema.json`. The generated files are committed and regenerated on every release.
- **TypeScript:** `json-schema-to-typescript` generates TypeScript interfaces.
- **Rust:** `schemars` or hand-written types tested for equivalence.

The MCP server validates incoming and outgoing tool arguments against `spec/schemas/tools/*.schema.json` at startup and fails fast if the implementation has drifted from the spec.

To regenerate types in the Python package:

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
3. Implement all required `BackingStore` methods per the prose contract.
4. Implement `DisciplineRenderer` and `EnforcerBinding` per their prose contracts.
5. Wire the MCP server using the tool schemas in `spec/schemas/tools/`.
6. Run `spec/conformance/runner/run.sh` against your implementation and pass all scenarios.
7. See `packages/typescript/README.md` or `packages/rust/README.md` for the contribution process.

---

## Versioning

The protocol version is in `spec/VERSION`. MAJOR.MINOR policy:

- **Patch** (e.g. 1.0 → 1.0.1): clarifications only, no wire change.
- **Minor** (e.g. 1.0 → 1.1): backward-compatible additions (new optional fields, new tools). Implementations of vN.M MUST accept inputs from vN.(≤M).
- **Major** (e.g. 1.0 → 2.0): breaking change to wire format or behaviour semantics. Implementations MUST refuse cross-major interaction.

Spec changes require a PR against `spec/` with `spec-lint.yml` passing and at least one implementation updated to match. See `CONTRIBUTING.md`.
