// SPDX-License-Identifier: Apache-2.0
/**
 * MiddlewareRegistry — stub forcing function (TS spike; runtime deferred).
 *
 * Public API shape mirrors Python MiddlewareRegistry.register().
 * register() THROWS. See pipeline.ts module docstring for rationale.
 *
 * Spec references:
 *   .workflow/plans/plugin-architecture-ts/STATE.md
 *   packages/python/src/sox_protocol/core/middleware/registry.py
 *   docs/adr/0004-plugin-architecture.md §7.6 / NR-3
 */

import type { Middleware } from './protocol.js';

/** Factory callable — mirrors Python `Callable[[], Middleware]`. */
export type MiddlewareFactory = () => Middleware;

/**
 * Registry that maps middleware names to factory callables.
 *
 * register() THROWS. This is intentional — see pipeline.ts for rationale.
 */
export class MiddlewareRegistry {
  /**
   * Register a named middleware factory.
   *
   * @throws Error — always. Runtime not implemented in TS spike.
   */
  register(_name: string, _factory: MiddlewareFactory): void {
    throw new Error(
      'MiddlewareRegistry.register not implemented in TS spike — runtime ships with first TS production code. ' +
        'See plugin-architecture-ts STATE.md and analysis.md §7.6 / NR-3.',
    );
  }
}
