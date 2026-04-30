# SPDX-License-Identifier: Apache-2.0
"""HookDispatcher middleware — observation-only pre/post hooks.

Hooks are a thin sugar layer over the middleware chain (ADR 0003 §Decision 3).
They allow external code to observe tool calls without participating in the
chain as a full middleware unit.

Hook contract
-------------
- A hook receives an **immutable view** of the context — it MUST NOT mutate it.
- A hook may return :class:`HookDecision` with ``action='deny'`` to short-circuit.
- A hook returning ``None`` or ``HookDecision(action='allow')`` is a no-op.
- Hooks are observation-only: they cannot modify ``ctx.input``.

Spec reference: ``docs/adr/0003 §Decision (3) hooks-as-sugar``
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ShortCircuitResponse
from sox_protocol.core.middleware.protocol import CallNext


class Hook(Protocol):
    """Observation-only hook that fires before or after a verb.

    Implementations MUST be async callables accepting an immutable context
    view and returning either ``None`` (pass-through) or a
    :class:`HookDecision`.
    """

    async def __call__(
        self, ctx_view: Mapping[str, object]
    ) -> HookDecision | None:
        """Observe the call and optionally deny it.

        Args:
            ctx_view: A read-only mapping view of the context fields.

        Returns:
            ``None`` to pass through, or a :class:`HookDecision` to
            allow/deny the call.
        """
        ...


@dataclass
class HookDecision:
    """Decision returned by a hook.

    Args:
        action: ``'allow'`` passes through; ``'deny'`` short-circuits with
            *error* (or a generic identity_failure envelope).
        error: Optional sox-error-shaped dict to return on deny.  If ``None``
            a generic error is generated.
    """

    action: Literal["allow", "deny"]
    error: dict[str, object] | None = None


def _make_deny_error(hook_name: str) -> dict[str, object]:
    """Build a sox-error envelope for a hook denial."""
    return {
        "error_code": "hook_denied",
        "message": f"Request denied by hook: {hook_name}",
        "detail": None,
        "retry_after": None,
    }


class _ImmutableContextView(Mapping[str, object]):
    """Read-only Mapping wrapper around a MiddlewareContext.

    Raises ``TypeError`` on any attempt to mutate (via standard Mapping
    interface this is already enforced; this class also overrides
    ``__setitem__`` / ``__delitem__`` for extra safety).
    """

    def __init__(self, ctx: MiddlewareContext) -> None:
        self._data: dict[str, object] = {
            "operation": ctx.operation,
            "input": dict(ctx.input),  # shallow copy so hooks can't mutate
            "connection_id": ctx.connection_id,
            "agent_id": ctx.agent_id,
            "metadata": dict(ctx.metadata),
            "correlation_id": ctx.correlation_id,
        }

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setitem__(self, key: str, value: object) -> None:
        raise TypeError("ctx_view is read-only; hooks must not mutate context")

    def __delitem__(self, key: str) -> None:
        raise TypeError("ctx_view is read-only; hooks must not mutate context")


@dataclass
class HookDispatcher:
    """Middleware that fans out pre/post hooks around the rest of the chain.

    Pre-hooks fire before ``call_next``; post-hooks fire after.  If any
    pre-hook returns ``HookDecision(action='deny')``, the chain is short-
    circuited and the error response is returned immediately.

    Post-hooks are observation-only and cannot alter the response.

    Attributes:
        name: Always ``'hook_dispatcher'``.
        must_run_before: Empty — hooks should run early.
        must_run_after: Empty — hooks are outermost by default.
        pre: Mapping of operation name -> list of pre-hooks.
        post: Mapping of operation name -> list of post-hooks.
    """

    pre: dict[str, list[Hook]] = field(default_factory=dict)
    post: dict[str, list[Hook]] = field(default_factory=dict)

    name: str = field(default="hook_dispatcher", init=False)
    must_run_before: tuple[str, ...] = field(default_factory=tuple, init=False)
    must_run_after: tuple[str, ...] = field(default_factory=tuple, init=False)

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: CallNext,
    ) -> dict[str, object]:
        """Fan out hooks and delegate to the rest of the chain.

        Args:
            ctx: The per-call context.
            call_next: Next stage in the pipeline.

        Returns:
            Response from the chain, or a sox-error envelope on hook denial.
        """
        ctx_view = _ImmutableContextView(ctx)
        operation = ctx.operation

        # Pre-hooks.
        for hook in self.pre.get(operation, []):
            decision = await hook(ctx_view)
            if decision is not None and decision.action == "deny":
                err = decision.error or _make_deny_error(getattr(hook, "__name__", "unknown"))
                raise ShortCircuitResponse(err)

        response = await call_next(ctx)

        # Post-hooks (observation only — ignore return value).
        for hook in self.post.get(operation, []):
            await hook(ctx_view)

        return response
