// SPDX-License-Identifier: Apache-2.0
/**
 * SOX Protocol — TypeScript middleware protocol types.
 *
 * Types-only port of the Python reference implementation.
 * No runtime logic is present in this file.
 *
 * Spec references:
 *   spec/ports/middleware/03-plugin-contract.md
 *   docs/adr/0004-plugin-architecture.md
 *   packages/python/src/sox_protocol/core/middleware/protocol.py
 *   packages/python/src/sox_protocol/core/middleware/context.py
 */

// ---------------------------------------------------------------------------
// Operation literal union — all 15 SOX v1 MUST operations.
// Mirrors context.py `Operation` Literal and the 15 enum values in
// sox-plugin.schema.json spec.applies_to.operations.
// ---------------------------------------------------------------------------

export type Operation =
  | 'send'
  | 'recv'
  | 'subscribe'
  | 'unsubscribe'
  | 'list_channels'
  | 'list_agents'
  | 'channels_ack'
  | 'channels_heartbeat'
  | 'channels_collect'
  | 'replay'
  | 'group_create'
  | 'group_invite'
  | 'group_join'
  | 'group_leave'
  | 'group_list_members';

// ---------------------------------------------------------------------------
// PluginKind discriminated union — 4-kind 2-axis taxonomy (ADR 0004 §1).
// Wire axis: interceptor, transformer.
// Lifecycle axis: provider, hook.
// ---------------------------------------------------------------------------

export type PluginKind = 'interceptor' | 'transformer' | 'provider' | 'hook';

// ---------------------------------------------------------------------------
// Response type alias — mirrors Python dict[str, object] return shape.
// ---------------------------------------------------------------------------

export type Response = Record<string, unknown>;

// ---------------------------------------------------------------------------
// SoxError — minimal error envelope shape for use in HookDecision.
// ---------------------------------------------------------------------------

export interface SoxError {
  readonly error_code: string;
  readonly message?: string;
  readonly [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// HookDecision — discriminated union for hook returns.
// A hook may return void/undefined (no-op) or a HookDecision.
// action: 'allow' — pipeline continues.
// action: 'deny'  — pipeline short-circuits with error (pre-hooks only).
// ---------------------------------------------------------------------------

export type HookDecision =
  | { readonly action: 'allow' }
  | { readonly action: 'deny'; readonly error: SoxError };

// ---------------------------------------------------------------------------
// ShortCircuitResponse — explicit short-circuit (mirrors Python exception class).
// Raised by an interceptor that wishes to bypass the remaining chain.
// Not an error condition; host MUST NOT log it as one.
// ---------------------------------------------------------------------------

export class ShortCircuitResponse {
  /**
   * Construct a short-circuit response that bypasses the remaining chain.
   *
   * @param response - The final response dict to return to the caller.
   */
  constructor(public readonly response: Response) {}
}

// ---------------------------------------------------------------------------
// MiddlewareContext — per-call context passed through the pipeline.
//
// Mutability rules (spec/ports/middleware.md §6, context.py):
//   - operation:       read-only after construction
//   - connectionId:    read-only after construction
//   - correlationId:   frozen after Pipeline sets it at construction time;
//                      no plugin may mutate it
//   - agentId:         write-once (set by auth middleware); null until set
//   - input:           mutable (middleware may normalise fields)
//   - metadata:        freely mutable for inter-middleware communication
//
// The Python implementation enforces write-once agentId and frozen
// correlationId via property setters that raise on illegal writes.
// In TypeScript the interface is read-only on those fields — the concrete
// class (shipped with the TS runtime engagement) enforces the rules.
// ---------------------------------------------------------------------------

export interface MiddlewareContext {
  readonly operation: Operation;
  input: Record<string, unknown>;
  metadata: Record<string, unknown>;
  readonly connectionId: string;
  /** Null until set by the auth middleware; write-once thereafter. */
  agentId: string | null;
  /**
   * Pipeline-internal call tracking token.
   * Frozen after Pipeline constructs the context; no plugin may mutate it.
   * Echoed into every pipeline_trace record for correlation across logs.
   */
  readonly correlationId: string;
}

// ---------------------------------------------------------------------------
// CallNext — the call_next callable passed to each middleware unit.
// Mirrors: CallNext = Callable[[MiddlewareContext], Awaitable[dict[str, object]]]
// ---------------------------------------------------------------------------

export type CallNext = (ctx: MiddlewareContext) => Promise<Response>;

// ---------------------------------------------------------------------------
// PluginCapabilities — capability flags declared in plugin_capabilities.
// Reserved boolean flags (interceptor-only): observe_only, may_short_circuit.
// Orthogonality: observe_only:true + may_short_circuit:true is invalid
// (plugin_capability_conflict startup error).
// Index signature allows free-form capability strings: {"auth.method": "jwt-bearer"}.
// ---------------------------------------------------------------------------

export interface PluginCapabilities {
  /** When true, plugin promises never to mutate context or short-circuit. */
  observe_only?: boolean;
  /** When true, plugin may return ShortCircuitResponse without calling next(). */
  may_short_circuit?: boolean;
  /** Free-form capability strings, e.g. {"auth.method": "jwt-bearer"}. */
  [capabilityKey: string]: string | boolean | undefined;
}

// ---------------------------------------------------------------------------
// Middleware interface — structural equivalent of the Python Protocol.
//
// Python uses a @runtime_checkable Protocol with a __call__ method.
// TypeScript does not have structural Protocol classes; instead we use a
// plain interface. Any object satisfying this interface is a valid middleware.
//
// The `call` method corresponds to Python's `__call__`:
//   async (ctx, call_next) -> dict[str, object]
// ---------------------------------------------------------------------------

export interface Middleware {
  /** Unique name for this middleware within a pipeline. */
  readonly name: string;
  /** Plugin taxonomy kind. */
  readonly kind: PluginKind;
  /** Names of middlewares/capabilities this one must precede. */
  readonly mustRunBefore: readonly string[];
  /** Names of middlewares/capabilities this one must follow. */
  readonly mustRunAfter: readonly string[];
  /**
   * Process ctx and either forward to next or short-circuit.
   *
   * @param ctx  - The per-call context object.
   * @param next - Async callable to forward to the next pipeline stage.
   * @returns Response dict conforming to the relevant operation output schema.
   */
  call(ctx: MiddlewareContext, next: CallNext): Promise<Response>;
}
