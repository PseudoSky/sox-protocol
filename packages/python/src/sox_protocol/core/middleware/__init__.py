# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol middleware pipeline — public API.

This package implements the Middleware port (``spec/ports/middleware.md``),
providing a composable pipeline through which every tool call passes before
reaching the backing store.

Public API
----------

Protocol / context::

    Middleware        — structural protocol for a middleware unit
    MiddlewareContext — per-call context dataclass
    CallNext          — type alias for the async next-stage callable

Pipeline::

    Pipeline          — ordered chain with a terminal handler
    PipelineBuilder   — fluent builder for Pipeline

Registry::

    MiddlewareRegistry  — collects factories and assembles chains
    register_middleware — module-level default registry (importable from
                          outside core/ to register plugins)

Hooks::

    HookDispatcher — pre/post observation-only hook fan-out middleware
    Hook           — hook Protocol
    HookDecision   — allow/deny decision returned by a hook

Default chain::

    DEFAULT_ORDER    — normative middleware name tuple (spec §4)
    default_chain    — alias for build_default_pipeline (convenience import)

Errors::

    MiddlewareError        — base exception
    ChainConfigurationError — invalid chain assembly
    ShortCircuitResponse   — short-circuit a pipeline call with a response

Plugin registration from outside core/
---------------------------------------
No core code modification is required to add a plugin::

    from sox_protocol.core.middleware import register_middleware

    register_middleware.register("my_plugin", MyPluginFactory)

The plugin will be picked up the next time
:func:`~sox_protocol.core.middleware.registry.MiddlewareRegistry.assemble` is
called with ``"my_plugin"`` in the order list.

Spec reference: ``spec/ports/middleware.md §2``
"""

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.default_chain import DEFAULT_ORDER, build_default_pipeline
from sox_protocol.core.middleware.errors import (
    ChainConfigurationError,
    MiddlewareError,
    ShortCircuitResponse,
)
from sox_protocol.core.middleware.hooks import Hook, HookDecision, HookDispatcher
from sox_protocol.core.middleware.pipeline import Pipeline, PipelineBuilder
from sox_protocol.core.middleware.protocol import CallNext, Middleware
from sox_protocol.core.middleware.registry import MiddlewareRegistry, register_middleware

# Convenience alias.
default_chain = build_default_pipeline

__all__ = [
    # Protocol / context
    "Middleware",
    "MiddlewareContext",
    "CallNext",
    # Pipeline
    "Pipeline",
    "PipelineBuilder",
    # Registry
    "MiddlewareRegistry",
    "register_middleware",
    # Hooks
    "HookDispatcher",
    "Hook",
    "HookDecision",
    # Default chain
    "DEFAULT_ORDER",
    "default_chain",
    "build_default_pipeline",
    # Errors
    "MiddlewareError",
    "ChainConfigurationError",
    "ShortCircuitResponse",
]
