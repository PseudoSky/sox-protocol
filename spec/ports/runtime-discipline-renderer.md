<!-- SPDX-License-Identifier: Apache-2.0 -->
# DisciplineRenderer Port — Behaviour Contract

**Version:** 1.0  
**Status:** Normative  
**Scope:** Language-neutral. Defines required behaviour for any runtime adapter that renders the SOX discipline document into a target runtime's prompt-construction surface. Defined in CONTRACTS.md §7.1.

---

## 1. Purpose

The `DisciplineRenderer` port is the north / driving adapter port responsible for taking the canonical SOX discipline document (`spec/discipline/discipline.md`) and making its content available to participating agents within a specific LLM runtime.

The discipline document uses `{{placeholder}}` tokens for all tool name references. The renderer's primary job is substituting those tokens with concrete tool names valid in the target runtime, then injecting the result into the runtime's prompt surface.

The renderer does NOT execute the discipline — it renders it. Behavioural enforcement is the concern of the `EnforcerBinding` port (see `spec/ports/runtime-enforcer-binding.md`).

---

## 2. Required Behaviours

### 2.1 Discipline source acceptance

The renderer MUST be able to accept the discipline content in at least one of these forms:
- A filesystem path pointing to `spec/discipline/discipline.md` (or a copy of it bundled in the implementation's package).
- The raw markdown string content of the discipline document.

The renderer MUST NOT hard-code discipline content inline. Discipline content is versioned in `spec/` and evolves independently of renderer implementations.

### 2.2 Placeholder substitution

The renderer MUST substitute all four placeholder tokens before rendering:

| Placeholder | Substituted with |
|---|---|
| `{{send_tool}}` | The runtime-specific tool name for `channels__send` |
| `{{recv_tool}}` | The runtime-specific tool name for `channels__recv` |
| `{{subscribe_tool}}` | The runtime-specific tool name for `channels__subscribe` |
| `{{list_tool}}` | The runtime-specific tool name for `channels__list_channels` |

The renderer MUST substitute all occurrences of each placeholder throughout the document, including in code blocks and inline examples.

The renderer MUST NOT leave any `{{...}}` placeholder token unsubstituted in the rendered output. If the runtime does not support one of the four tools, the renderer MUST substitute the placeholder with a clearly marked "unavailable" note rather than leaving the raw token.

### 2.3 Prompt surface injection

The renderer MUST deliver the substituted discipline content to the runtime's prompt-construction surface. The exact injection mechanism is runtime-specific:

- For skill-based runtimes: write the rendered content to the runtime's skill file location.
- For instruction-based runtimes: load the rendered content into the agent's `instructions` or `system` slot.
- For node-based runtimes: inject the rendered content as a system-slot addition to the relevant graph state.

The renderer MUST inject the content in a location that is visible to the agent before the agent takes its first action on a session where SOX channels are available.

### 2.4 Bootstrap snippet injection

In addition to the full discipline content, the renderer MUST add a one-line bootstrap snippet to each participating agent's system prompt. The bootstrap snippet MUST be runtime-appropriate and MUST include a pointer to the channel capability so the agent can discover it at the start of any session, even if the full discipline content is loaded lazily.

The bootstrap snippet is separate from the full discipline and MUST NOT duplicate the full discipline content.

### 2.5 Idempotent installation

Running the renderer's install operation twice on the same target project MUST be idempotent:
- It MUST NOT produce duplicate discipline content in any prompt surface.
- It MUST NOT corrupt or break any existing project configuration.
- Re-running the install SHOULD update the rendered content if the discipline source has changed (version upgrade path).

---

## 3. Forbidden Behaviours

- The renderer MUST NOT inject concrete tool names into the discipline source file (`spec/discipline/discipline.md`). Substitution happens at render time, not at authoring time.
- The renderer MUST NOT modify `spec/discipline/discipline.md` or any file under `spec/`.
- The renderer MUST NOT include content from `packages/` in the rendered output.
- The renderer MUST NOT emit rendered content that still contains raw `{{...}}` placeholder tokens (with the exception of tokens the runtime has declared unavailable and replaced with a marked note).

---

## 4. Versioning

The renderer MUST declare which protocol version's discipline it renders. If the discipline source is a newer major version than the renderer supports, the renderer MUST fail fast with a clear error message identifying the version mismatch.

---

## 5. Conformance Checklist

A `DisciplineRenderer` implementation is SOX v1.0 conformant when it satisfies all of the following:

- [ ] Accepts discipline source as a path or string content.
- [ ] Substitutes all four `{{placeholder}}` tokens with valid runtime-specific tool names.
- [ ] Leaves no unsubstituted `{{...}}` tokens in rendered output.
- [ ] Injects rendered content into the runtime's prompt-construction surface before agent first-action.
- [ ] Injects bootstrap snippet separately into system prompt.
- [ ] Installation is idempotent; running twice does not duplicate or break content.
- [ ] Does not modify any file under `spec/`.
- [ ] Declares the protocol version it targets.
- [ ] Fails fast on major-version mismatch between the discipline source and the renderer.
