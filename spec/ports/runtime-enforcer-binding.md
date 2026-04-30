<!-- SPDX-License-Identifier: Apache-2.0 -->
# EnforcerBinding Port — Behaviour Contract

**Version:** 1.0  
**Status:** Normative  
**Scope:** Language-neutral. Defines required behaviour for any runtime adapter that wires a host runtime's lifecycle events into the SOX cadence enforcer and translates enforcer Decisions back into the runtime's mechanisms. Defined in CONTRACTS.md §7.2.

---

## 1. Purpose

The `EnforcerBinding` port is the north / driving adapter port responsible for connecting the SOX cadence enforcer to a specific LLM runtime. Its role has two halves:

1. **Inbound:** Translate the runtime's lifecycle events into `Event` objects (per `spec/schemas/event.schema.json`) and deliver them to `enforcer.decide()`.
2. **Outbound:** Translate the `Decision` returned by `enforcer.decide()` (per `spec/schemas/decision.schema.json`) into the runtime's native mechanism for context injection or action blocking.

The `EnforcerBinding` does NOT contain policy logic. All policy is expressed in the `Policy` object (`spec/schemas/policy.schema.json`) and evaluated inside `enforcer.decide()`. The binding is a pure I/O shim.

---

## 2. Required Behaviours

### 2.1 Lifecycle event wiring (minimum required)

The binding MUST wire at minimum the following two lifecycle events:

**Per-tool-call event:**  
After each tool call completes within the runtime, the binding MUST construct and deliver an `Event` with:
- `event_type: "tool_used"`
- `agent_id`: the identifier of the agent that made the call
- `timestamp`: the time the tool call completed, as Unix epoch seconds
- `tool_name`: the name of the tool that was called

**On-stop event:**  
When the runtime signals that the agent is about to exit or complete its turn, the binding MUST construct and deliver an `Event` with:
- `event_type: "stop_requested"`
- `agent_id`: the stopping agent's identifier
- `timestamp`: the current time, as Unix epoch seconds
- `tool_name`: null

**Recommended additional events (not required for v1.0 conformance):**  
Bindings SHOULD also wire `turn_started`, `channel_send`, and `channel_recv` events for richer enforcer signal. These are used by the enforcer's turn-counting and send-and-wait detection branches (see CONTRACTS.md §3.4 flowchart). Bindings that omit these events remain conformant but will produce fewer `inject` decisions from those branches.

### 2.2 Event delivery ordering

Events for a single agent MUST be delivered to `enforcer.decide()` in the order they occur. Cross-agent ordering is not required (each agent has independent state).

### 2.3 State persistence

The binding MUST persist enforcer `State` objects (`spec/schemas/state.schema.json`) to stable storage shared across all agents in the project. The canonical storage location is `${SOX_STATE_DIR}/state.db`. All agents in one project share one state store so the enforcer has a consistent view of per-agent counters across restarts.

The binding MUST load the current agent's `State` before each `decide()` call and write the updated `State` after each `decide()` call as a single atomic read-modify-write. Concurrent bindings for different agents in the same state store MUST NOT corrupt each other's state records.

### 2.4 Decision translation — `noop`

When `enforcer.decide()` returns a `Decision` with `action: "noop"`, the binding MUST take no action and MUST NOT modify the agent's turn or context in any way. The triggering action (tool call, stop) proceeds normally.

### 2.5 Decision translation — `inject`

When `enforcer.decide()` returns a `Decision` with `action: "inject"`, the binding MUST inject `Decision.message` into the agent's next-turn context using the runtime's appropriate mechanism. Examples by runtime:

- Skill-based hook runtimes: output a structured JSON object to the hook's stdout with the message as additional context.
- Instruction-based runtimes: append `Decision.message` as a user-role turn before the model's next step.
- Node-based graph runtimes: mutate the graph state to prepend `Decision.message` to the system context for the next node execution.

The injected content MUST be `Decision.message` verbatim. The binding MUST NOT paraphrase, summarise, or omit any part of the message.

### 2.6 Decision translation — `block`

When `enforcer.decide()` returns a `Decision` with `action: "block"`, the binding MUST:
1. Prevent the triggering action from completing. For a `stop_requested` event, this means the agent MUST NOT exit until it has drained its inbox.
2. Present `Decision.message` to the agent so it understands what is required before proceeding.

The block MUST be presented in a way that the agent can act on it — i.e., the message is visible in the agent's input for the next reasoning step, not merely logged.

### 2.7 MCP server surface

The binding MUST ensure that the four SOX MCP tools (`channels__send`, `channels__recv`, `channels__subscribe`, `channels__list_channels`) are registered and available to participating agents, typically by adding the SOX MCP server to the runtime's MCP client configuration.

---

## 3. Forbidden Behaviours

- The binding MUST NOT contain policy logic (threshold comparisons, reminder text composition). These belong in `Policy` and `enforcer.decide()`.
- The binding MUST NOT swallow or silently drop `inject` or `block` decisions. Every non-`noop` Decision MUST be acted on.
- The binding MUST NOT deliver events to `enforcer.decide()` out of order for a single agent.
- The binding MUST NOT store per-agent `State` in a location that is not shared across all agents in the project (i.e., per-process in-memory state is not acceptable for enforcer state).

---

## 4. Versioning

The binding MUST declare which protocol version it targets. If the MCP server's advertised protocol version (from `channels__list_channels` output) has a different MAJOR component from the binding's declared version, the binding MUST refuse to operate and MUST emit a clear error identifying the mismatch.

---

## 5. Conformance Checklist

An `EnforcerBinding` implementation is SOX v1.0 conformant when it satisfies all of the following:

- [ ] Wires the per-tool-call lifecycle event (`event_type: "tool_used"`) to `enforcer.decide()`.
- [ ] Wires the on-stop lifecycle event (`event_type: "stop_requested"`) to `enforcer.decide()`.
- [ ] Delivers events for a single agent in occurrence order.
- [ ] Persists enforcer `State` to `${SOX_STATE_DIR}/state.db` (or equivalent shared location) as an atomic read-modify-write per `decide()` call.
- [ ] Translates `noop` decisions correctly: no action taken, triggering action proceeds.
- [ ] Translates `inject` decisions correctly: `Decision.message` injected verbatim into agent's next-turn context.
- [ ] Translates `block` decisions correctly: triggering action prevented; `Decision.message` presented to the agent.
- [ ] Registers the four SOX MCP tools with the runtime's MCP client.
- [ ] Does not contain policy logic.
- [ ] Declares the protocol version it targets.
- [ ] Fails fast on major-version mismatch with the SOX MCP server.
