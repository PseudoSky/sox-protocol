# SPDX-License-Identifier: Apache-2.0
"""MiddlewareRegistry: collects middleware factories and assembles ordered chains.

Responsibilities
----------------
1. Accept factory registrations by name (in-process or via entry points).
2. Assemble an ordered list of middleware instances, validating
   ``must_run_before`` / ``must_run_after`` constraints.
3. Raise :class:`~sox_protocol.core.middleware.errors.ChainConfigurationError`
   on unresolvable ordering conflicts.

Out-of-core registration
------------------------
Code outside ``core/`` (adapters, plugins, tests) can register middleware via
the module-level ``register_middleware`` singleton::

    from sox_protocol.core.middleware import register_middleware

    register_middleware.register("my_plugin", lambda: MyPlugin())

This proves no core code change is needed to add a plugin.

Spec reference: ``spec/ports/middleware.md §4``; ``docs/adr/0003 §Decision (4)``
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable

from sox_protocol.core.middleware.errors import ChainConfigurationError
from sox_protocol.core.middleware.protocol import Middleware

_log = logging.getLogger(__name__)


def _topological_sort(
    names: list[str],
    instances: dict[str, Middleware],
) -> list[str]:
    """Return *names* sorted to satisfy all must_run_before/must_run_after constraints.

    Uses Kahn's algorithm.  Raises :class:`ChainConfigurationError` on cycles
    or unsatisfiable constraints.

    Args:
        names: The middleware names to order (subset of registered names).
        instances: Map of name -> instantiated Middleware for constraint lookup.

    Returns:
        Ordered list of names.

    Raises:
        ChainConfigurationError: On cycle or unsatisfiable ordering constraint.
    """
    name_set = set(names)

    # Build adjacency: edge (a, b) means "a must run before b".
    in_degree: dict[str, int] = {n: 0 for n in names}
    successors: dict[str, list[str]] = {n: [] for n in names}

    for name in names:
        mw = instances[name]
        for before in mw.must_run_before:
            if before in name_set:
                successors[name].append(before)
                in_degree[before] += 1
        for after in mw.must_run_after:
            if after in name_set:
                successors[after].append(name)
                in_degree[name] += 1

    # Kahn's BFS.
    queue = [n for n in names if in_degree[n] == 0]
    queue.sort()  # deterministic tie-breaking
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for succ in sorted(successors[node]):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    if len(result) != len(names):
        remaining = [n for n in names if n not in result]
        raise ChainConfigurationError(
            f"Middleware ordering cycle or unsatisfiable constraint among: {remaining}"
        )

    return result


class MiddlewareRegistry:
    """Registry that maps middleware names to factory callables.

    Usage::

        registry = MiddlewareRegistry()
        registry.register("auth", lambda: AuthMiddleware(verifier))
        chain = registry.assemble(["auth", "store_dispatch"])

    Plugin registration from outside ``core/``::

        from sox_protocol.core.middleware import register_middleware
        register_middleware.register("my_plugin", lambda: MyPlugin())
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Middleware]] = {}

    def register(self, name: str, factory: Callable[[], Middleware]) -> None:
        """Register a named middleware factory.

        Args:
            name: Unique middleware name.
            factory: Zero-argument callable returning a fresh Middleware instance.

        Raises:
            ValueError: If *name* is already registered.
        """
        if name in self._factories:
            raise ValueError(f"Middleware {name!r} is already registered")
        self._factories[name] = factory

    def get(self, name: str) -> Callable[[], Middleware]:
        """Return the factory for *name*.

        Args:
            name: The middleware name.

        Returns:
            The registered factory callable.

        Raises:
            KeyError: If *name* is not registered.
        """
        return self._factories[name]

    def assemble(self, order: list[str]) -> list[Middleware]:
        """Instantiate middlewares in *order* and validate constraints.

        Middlewares named in *order* that are not registered are skipped with
        a startup warning (tolerating absent optional links).

        Args:
            order: Requested middleware names in desired order.

        Returns:
            Ordered list of Middleware instances.

        Raises:
            ChainConfigurationError: On must_run_before / must_run_after
                conflict among the registered subset.
        """
        # Resolve which names are actually registered.
        present: list[str] = []
        for name in order:
            if name in self._factories:
                present.append(name)
            else:
                warnings.warn(
                    f"Middleware {name!r} not registered; skipping in chain assembly.",
                    stacklevel=2,
                )

        # Instantiate.
        instances: dict[str, Middleware] = {n: self._factories[n]() for n in present}

        # Validate ordering constraints via topological sort.
        sorted_names = _topological_sort(present, instances)

        return [instances[n] for n in sorted_names]

    def load_entry_points(self, group: str = "sox_protocol.middleware") -> None:
        """Discover and register middleware factories from Python entry points.

        Each entry point in *group* must be a zero-argument callable (a factory
        function or class) whose return value conforms to the
        :class:`~sox_protocol.core.middleware.protocol.Middleware` Protocol.  The
        entry point name is used as the middleware name.

        Args:
            group: Entry point group to scan.  Defaults to
                ``"sox_protocol.middleware"``.
        """
        from importlib.metadata import entry_points

        eps = entry_points(group=group)
        for ep in eps:
            try:
                factory: Callable[[], Middleware] = ep.load()
                self.register(ep.name, factory)
                _log.debug("Loaded middleware entry point %r from %r", ep.name, ep.value)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "Failed to load middleware entry point %r: %s", ep.name, exc
                )


# ---------------------------------------------------------------------------
# Module-level default registry (importable by out-of-core code)
# ---------------------------------------------------------------------------

#: The default :class:`MiddlewareRegistry` singleton.  Import this from
#: outside ``core/`` to register plugins without modifying core code::
#:
#:     from sox_protocol.core.middleware import register_middleware
#:     register_middleware.register("my_plugin", MyPluginFactory)
register_middleware: MiddlewareRegistry = MiddlewareRegistry()
