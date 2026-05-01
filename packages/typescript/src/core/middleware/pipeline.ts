// SPDX-License-Identifier: Apache-2.0
/**
 * Pipeline — stub forcing function (TS spike; runtime deferred).
 *
 * This class exists as a sociological forcing function per ADR 0004 analysis
 * §7.6 / NR-3: when TS production code arrives, the obvious import
 * (`Pipeline` from `@sox/middleware`) exists and throws, directing
 * implementers to fill it in rather than reinventing in handlers.
 *
 * DO NOT implement Pipeline.dispatch logic here.
 * Full Pipeline + Registry runtime ships with the first TS production code
 * engagement (plugin-architecture-ts-runtime).
 *
 * Spec references:
 *   .workflow/plans/plugin-architecture-ts/STATE.md
 *   packages/python/src/sox_protocol/core/middleware/pipeline.py
 *   docs/adr/0004-plugin-architecture.md §7.6 / NR-3
 */

import type { Middleware, MiddlewareContext, Response, CallNext } from './protocol.js';

// Terminal handler type — matches Python's terminal callable signature.
export type TerminalHandler = (ctx: MiddlewareContext) => Promise<Response>;

/**
 * Ordered middleware chain with a terminal dispatch handler.
 *
 * Constructor signature mirrors Python Pipeline.__init__:
 *   Pipeline(middlewares: list[Middleware], terminal: Callable[[MiddlewareContext], Awaitable[dict]])
 *
 * dispatch() THROWS. This is intentional. See module docstring.
 */
export class Pipeline {
  /** Middleware names in execution order (matches Python's `order` attribute). */
  public readonly order: readonly string[];

  constructor(
    // Accepted for API shape parity with Python Pipeline.__init__.
    // Not stored — this is a stub; dispatch() always throws.
    middlewares: readonly Middleware[],
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    _terminal: TerminalHandler,
  ) {
    this.order = middlewares.map((m) => m.name);
  }

  /**
   * Dispatch an operation through the pipeline.
   *
   * @throws Error — always. Runtime not implemented in TS spike.
   *
   * Constructor signature mirrors Python Pipeline.dispatch:
   *   dispatch(operation, input, *, connection_id, metadata)
   */
  async dispatch(
    _operation: string,
    _input: Record<string, unknown>,
    _opts: {
      connectionId: string;
      metadata?: Record<string, unknown>;
    },
  ): Promise<Response> {
    throw new Error(
      'Pipeline.dispatch not implemented in TS spike — runtime ships with first TS production code. ' +
        'See plugin-architecture-ts STATE.md and analysis.md §7.6 / NR-3.',
    );
  }
}

// Re-export types consumers will need alongside Pipeline.
export type { Middleware, MiddlewareContext, Response, CallNext };
