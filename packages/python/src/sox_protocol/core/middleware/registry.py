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
from collections.abc import Callable, Mapping

from sox_protocol.core.middleware.errors import (
    ChainConfigurationError,
    PluginCapabilityConflict,
    PluginManifestInvalid,
    PluginNotAllowed,
    PluginNotFound,
    PluginOrderingCycle,
    PluginProtocolVersionMismatch,
    PluginRequirementUnmet,
)
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


def _toposort_plugins(
    manifests: Mapping[str, object],
) -> list[str]:
    """Stable Kahn topological sort over plugin manifests with lex tie-break.

    Builds a DAG from ``must_run_before`` / ``must_run_after`` constraints and
    returns a deterministic ordering.  Cycles produce
    :class:`PluginOrderingCycle` naming all cycle members.

    Args:
        manifests: Dict mapping plugin id → :class:`~sox_protocol.core.middleware.plugin_loader.Manifest`.

    Returns:
        Ordered list of plugin ids.

    Raises:
        PluginOrderingCycle: When a cycle is detected.
    """
    # Import here to avoid a circular-import at module level.
    from sox_protocol.core.middleware.plugin_loader import Manifest as _Manifest

    ids = list(manifests.keys())
    id_set = set(ids)

    in_degree: dict[str, int] = {pid: 0 for pid in ids}
    successors: dict[str, list[str]] = {pid: [] for pid in ids}

    for pid in ids:
        m = manifests[pid]
        assert isinstance(m, _Manifest)
        # must_run_before: self → target  (self must precede target)
        for target in m.must_run_before:
            if target in id_set:
                successors[pid].append(target)
                in_degree[target] += 1
        # must_run_after: source → self  (self must follow source)
        for source in m.must_run_after:
            if source in id_set:
                successors[source].append(pid)
                in_degree[pid] += 1

    # Kahn's BFS with lex tie-break (§4 normative sort).
    queue = sorted(pid for pid in ids if in_degree[pid] == 0)
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        newly_zero: list[str] = []
        for succ in successors[node]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                newly_zero.append(succ)
        # Insert newly-zero nodes in lex order (merge into sorted queue).
        for nz in sorted(newly_zero):
            # Insert in sorted position to maintain lex ordering.
            import bisect

            bisect.insort(queue, nz)

    if len(result) != len(ids):
        cycle_members = sorted(pid for pid in ids if pid not in set(result))
        raise PluginOrderingCycle(cycle_members)

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
        # Plugin discovery state (populated by load_plugins).
        from sox_protocol.core.middleware.plugin_loader import Manifest

        self._loaded_manifests: dict[str, Manifest] = {}
        self._resolved_order: tuple[str, ...] | None = None

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

    @property
    def resolved_order(self) -> tuple[str, ...]:
        """Return the plugin load order determined by ``load_plugins()``.

        Returns an empty tuple if ``load_plugins()`` has not been called yet.

        Returns:
            Tuple of plugin ids in pipeline execution order.
        """
        return self._resolved_order if self._resolved_order is not None else ()

    def load_plugins(
        self,
        *,
        allowlist: list[str] | None = None,
        env: str = "dev",
        host_protocol_version: str = "1.0.0",
        no_discovery: bool = False,
        group: str = "sox_protocol.plugins",
    ) -> None:
        """Discover, validate, order, and register out-of-tree plugins.

        Orchestrates the seven-step plugin boot sequence:

        0. ``no_discovery`` short-circuit: if *True*, log and return immediately
           with ``resolved_order = ()``. Takes precedence over allowlist
           evaluation (R4 precedence rule).
        1. Scan ``importlib.metadata.entry_points(group=group)``.
        2. In production mode with empty allowlist: refuse startup.
        3. For each entry-point: read manifest → validate schema →
           check protocol_version → assert capability orthogonality.
        4. Allowlist filter.
        5. Stable Kahn topological sort with lex tie-break; cycle → error.
        6. ``requires`` resolution against loaded capability strings.
        7. Factory invocation + ``register()``.

        The computed order is cached in ``self._resolved_order``.

        Args:
            allowlist: Plugin ids that are permitted to load.  ``None`` means
                "no explicit allowlist provided" (dev: load all; production:
                refuse all).
            env: Runtime environment string.  ``"production"`` activates strict
                allowlist enforcement.  Any other value is treated as
                development mode.
            host_protocol_version: The host's single protocol version string
                used for compatibility checks.
            no_discovery: When ``True``, skip all discovery and return with an
                empty resolved order.  Allowlist contents are NOT validated.
            group: Entry-point group to scan.  Defaults to
                ``"sox_protocol.plugins"``.

        Raises:
            PluginNotAllowed: In production mode with an empty allowlist (no
                plugins permitted).
            PluginNotFound: An allowlisted id has no corresponding entry-point.
            PluginManifestInvalid: A manifest fails schema validation.
            PluginProtocolVersionMismatch: Host version outside plugin's range.
            PluginCapabilityConflict: ``observe_only`` + ``may_short_circuit``.
            PluginOrderingCycle: Ordering constraints form a cycle.
            PluginRequirementUnmet: A ``requires`` capability is unresolvable.
        """
        # Step 0: no_discovery short-circuit (R4 — wins over allowlist).
        if no_discovery:
            _log.info("plugin discovery disabled (--no-discovery)")
            self._resolved_order = ()
            return

        from importlib.metadata import entry_points

        from sox_protocol.core.middleware.plugin_loader import (
            Manifest,
            assert_capability_orthogonality,
            check_protocol_version,
            read_manifest_for_entry_point,
            validate_manifest,
        )

        # Step 1: scan entry-points.
        eps = {ep.name: ep for ep in entry_points(group=group)}

        # Step 2: production + empty allowlist → refuse startup.
        is_production = env == "production"
        if is_production and not allowlist:
            raise PluginNotAllowed(
                plugin_id="*",
                message=(
                    "SOX_ENV=production requires an explicit --allow-plugins allowlist. "
                    "Set SOX_ALLOWED_PLUGINS or pass --allow-plugins to enable plugins, "
                    "or set --no-discovery to disable plugin loading entirely."
                ),
            )

        # Step 3: validate each discovered entry-point.
        # When an explicit allowlist is provided, plugins that are NOT on the
        # allowlist are skipped before validation — there is no point validating
        # manifests we will never load, and doing so can cause spurious failures
        # (e.g. a globally-installed plugin with an incompatible protocol version
        # would abort startup even though it is explicitly excluded by the
        # allowlist).  In dev mode with no allowlist, all discovered plugins are
        # validated (and any validation failure is a hard error).
        from importlib.metadata import EntryPoint

        _allowlist_set: frozenset[str] | None = (
            frozenset(allowlist) if allowlist is not None else None
        )

        manifests: dict[str, Manifest] = {}
        ep_map: dict[str, EntryPoint] = {}
        for ep_name, ep in eps.items():
            # Pre-filter: when an explicit allowlist is given AND we are in
            # production mode, skip validation of plugins that are NOT on the
            # allowlist.  Production silently drops unallowlisted plugins (step
            # 4), so validating them is unnecessary and can cause spurious
            # PluginProtocolVersionMismatch errors when a globally-installed
            # plugin has an incompatible host version but is explicitly excluded.
            #
            # Dev mode intentionally validates all discovered plugins so the
            # "dev loads all plugins with a warning" contract is preserved.
            if is_production and _allowlist_set is not None and ep_name not in _allowlist_set:
                _log.debug(
                    "Plugin %r not in allowlist; skipping validation (production).",
                    ep_name,
                )
                continue
            try:
                raw = read_manifest_for_entry_point(ep)
                manifest = validate_manifest(raw)
                check_protocol_version(manifest, host_protocol_version)
                assert_capability_orthogonality(manifest)
                manifests[manifest.id] = manifest
                ep_map[manifest.id] = ep
            except (
                PluginManifestInvalid,
                PluginProtocolVersionMismatch,
                PluginCapabilityConflict,
            ):
                raise

        # Step 4: allowlist filter.
        if allowlist is not None:
            allowlist_set = set(allowlist)
            # Check for allowlisted ids with no matching manifest.
            for wanted_id in allowlist_set:
                if wanted_id and wanted_id not in manifests:
                    raise PluginNotFound(wanted_id)

        to_load: dict[str, Manifest] = {}
        for plugin_id, manifest in manifests.items():
            if allowlist is None or plugin_id in allowlist:
                to_load[plugin_id] = manifest
            elif is_production:
                # Production: silently skip unallowlisted plugins.
                _log.debug(
                    "Plugin %r not in allowlist; skipping (production mode).", plugin_id
                )
            else:
                # Dev: load with a warning.
                import sys

                print(
                    f"[sox] WARNING: plugin {plugin_id!r} is not in --allow-plugins "
                    "allowlist but will be loaded in dev mode.",
                    file=sys.stderr,
                )
                to_load[plugin_id] = manifest

        # Step 5: stable Kahn topological sort over to_load.
        sorted_ids = _toposort_plugins(to_load)

        # Step 6: requires resolution.
        # Build a set of all provided capability keys across loaded plugins.
        provided_caps: set[str] = set()
        for manifest in to_load.values():
            for cap in manifest.plugin_capabilities:
                for k in cap:
                    if k not in ("observe_only", "may_short_circuit"):
                        provided_caps.add(k)
            # Also treat plugin id itself as a "provided" token.
            provided_caps.add(manifest.id)

        for plugin_id in sorted_ids:
            manifest = to_load[plugin_id]
            for req in manifest.requires:
                if req not in provided_caps:
                    raise PluginRequirementUnmet(
                        plugin_id=plugin_id,
                        capability=req,
                    )

        # Step 7: factory invocation + register.
        for plugin_id in sorted_ids:
            ep = ep_map[plugin_id]
            factory: Callable[[], Middleware] = ep.load()
            if plugin_id in self._factories:
                # Already registered from a prior load_plugins call (e.g. multiple
                # create_app calls in the same process during tests).  The factory
                # is functionally identical — re-registering would produce the same
                # middleware, so skip silently to preserve idempotency.
                _log.debug(
                    "Plugin %r already registered; skipping re-registration "
                    "(idempotent load_plugins).",
                    plugin_id,
                )
                continue
            try:
                self.register(plugin_id, factory)
            except ValueError as exc:
                # Name collision: convert to PluginManifestInvalid per R6.
                raise PluginManifestInvalid(
                    plugin_id=plugin_id,
                    reason=str(exc),
                ) from exc

        self._loaded_manifests = dict(to_load)
        self._resolved_order = tuple(sorted_ids)

        _log.info(
            "[sox] plugin registry frozen: %d plugin%s loaded",
            len(sorted_ids),
            "" if len(sorted_ids) == 1 else "s",
        )

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
