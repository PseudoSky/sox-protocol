# SPDX-License-Identifier: Apache-2.0
"""Typed exception and response classes for the middleware pipeline.

Short-circuit responses and error envelopes defined here are used throughout
the pipeline to halt execution and return a sox-error-shaped dict to the
caller without leaking implementation details.

Spec reference: ``spec/ports/middleware.md §7``; ``spec/envelopes/sox-error.schema.json``
Plugin startup errors: ``spec/ports/middleware/03-plugin-contract.md §6.2``
"""

from __future__ import annotations

from typing import ClassVar


def make_internal_error(reason: str) -> dict[str, object]:
    """Build a sox-error envelope for an internal (non-caller) error.

    The message deliberately omits stack traces and internal details
    per ``spec/ports/middleware.md §7``.

    Args:
        reason: Short human-readable explanation (safe for external exposure).

    Returns:
        Dict conforming to ``spec/envelopes/sox-error.schema.json`` with
        ``error_code="internal_error"``.
    """
    return {
        "error_code": "internal_error",
        "message": reason,
        "detail": None,
        "retry_after": None,
    }


class MiddlewareError(Exception):
    """Base class for all middleware pipeline errors.

    Subclasses are caught by :class:`~sox_protocol.core.middleware.pipeline.Pipeline`
    and converted to appropriate sox-error response dicts.
    """


class ChainConfigurationError(MiddlewareError):
    """Raised when the middleware chain cannot be assembled due to constraint violations.

    Examples: must_run_before/must_run_after conflicts, missing required links,
    duplicate middleware names.
    """


class ShortCircuitResponse(MiddlewareError):
    """Raised by a middleware to immediately return a response without forwarding.

    The wrapped *response* MUST conform to the relevant operation output schema
    (success) or ``spec/envelopes/sox-error.schema.json`` (rejection).

    Spec reference: ``spec/ports/middleware.md §5``

    Args:
        response: The complete response dict to return to the caller.
    """

    def __init__(self, response: dict[str, object]) -> None:
        super().__init__("short-circuit")
        self.response: dict[str, object] = response


# ---------------------------------------------------------------------------
# Plugin startup error taxonomy
# Spec: spec/ports/middleware/03-plugin-contract.md §6.2
# ---------------------------------------------------------------------------


class PluginStartupError(MiddlewareError):
    """Base class for all plugin startup failures.

    Subclasses carry a stable ``error_code`` class-level constant and a
    ``to_envelope()`` method that serialises the error into a structured dict
    suitable for structured logging or a sox-error response body.

    These errors are fail-fast at startup; they are raised before any plugin
    factory is invoked and MUST NOT be caught and swallowed by the bootstrap.

    Spec reference: ``spec/ports/middleware/03-plugin-contract.md §6.2``
    """

    error_code: ClassVar[str] = "plugin_startup_error"

    def to_envelope(self) -> dict[str, str]:
        """Return a structured error dict for logging / startup exit.

        Returns:
            Dict with at minimum ``error_code`` and ``message`` keys.
        """
        return {
            "error_code": self.error_code,
            "message": str(self),
        }


class PluginNotAllowed(PluginStartupError):
    """Plugin discovered via entry-points but not in the allowlist.

    Raised in production mode when a plugin's id is absent from
    ``--allow-plugins`` / ``SOX_ALLOWED_PLUGINS``.

    Spec reference: ``spec/ports/middleware/03-plugin-contract.md §6.2``
    """

    error_code: ClassVar[str] = "plugin_not_allowed"

    def __init__(self, plugin_id: str, message: str | None = None) -> None:
        self.plugin_id = plugin_id
        msg = message or f"Plugin {plugin_id!r} is not in the allowlist"
        super().__init__(msg)

    def to_envelope(self) -> dict[str, str]:
        base = super().to_envelope()
        base["plugin_id"] = self.plugin_id
        return base


class PluginNotFound(PluginStartupError):
    """Plugin id in allowlist but no matching entry-point found.

    Raised when an id listed in ``--allow-plugins`` has no corresponding
    installed entry-point in the ``sox_protocol.plugins`` group.

    Spec reference: ``spec/ports/middleware/03-plugin-contract.md §6.2``
    """

    error_code: ClassVar[str] = "plugin_not_found"

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        super().__init__(
            f"Plugin {plugin_id!r} is in the allowlist but no matching entry-point was found"
        )

    def to_envelope(self) -> dict[str, str]:
        base = super().to_envelope()
        base["plugin_id"] = self.plugin_id
        return base


class PluginManifestInvalid(PluginStartupError):
    """Plugin manifest fails JSON Schema validation or structural checks.

    Carries the jsonschema validation path and message so operators can locate
    the offending field.

    Spec reference: ``spec/ports/middleware/03-plugin-contract.md §6.2``
    """

    error_code: ClassVar[str] = "plugin_manifest_invalid"

    def __init__(
        self,
        plugin_id: str,
        reason: str,
        *,
        path: str = "",
    ) -> None:
        self.plugin_id = plugin_id
        self.reason = reason
        self.path = path
        detail = f" (at {path})" if path else ""
        super().__init__(
            f"Plugin {plugin_id!r} manifest invalid{detail}: {reason}"
        )

    def to_envelope(self) -> dict[str, str]:
        base = super().to_envelope()
        base["plugin_id"] = self.plugin_id
        base["reason"] = self.reason
        if self.path:
            base["path"] = self.path
        return base


class PluginProtocolVersionMismatch(PluginStartupError):
    """Host protocol version falls outside the plugin's declared range.

    Carries the five-field envelope mandated by
    ``spec/ports/middleware/06-versioning.md §5.1``:

    - ``plugin_id``
    - ``plugin_declares`` — the ``spec.protocol_version`` string verbatim
    - ``host_supports`` — the single host protocol version string
    - ``remediation`` — human-readable upgrade path

    Spec reference: ``spec/ports/middleware/06-versioning.md §5.1``;
    ``spec/ports/middleware/03-plugin-contract.md §6.2``
    """

    error_code: ClassVar[str] = "plugin_protocol_version_mismatch"

    def __init__(
        self,
        plugin_id: str,
        plugin_declares: str,
        host_supports: str,
        remediation: str,
    ) -> None:
        self.plugin_id = plugin_id
        self.plugin_declares = plugin_declares
        self.host_supports = host_supports
        self.remediation = remediation
        super().__init__(
            f"Plugin {plugin_id!r} requires protocol {plugin_declares!r} "
            f"but host supports {host_supports!r}. {remediation}"
        )

    def to_envelope(self) -> dict[str, str]:
        return {
            "error_code": self.error_code,
            "plugin_id": self.plugin_id,
            "plugin_declares": self.plugin_declares,
            "host_supports": self.host_supports,
            "remediation": self.remediation,
        }


class PluginCapabilityConflict(PluginStartupError):
    """Manifest declares ``observe_only: true`` and ``may_short_circuit: true`` together.

    These flags are mutually exclusive per the orthogonality constraint in
    ``spec/ports/middleware/03-plugin-contract.md §2.3``.

    Spec reference: ``spec/ports/middleware/03-plugin-contract.md §2.3``, §6.2
    """

    error_code: ClassVar[str] = "plugin_capability_conflict"

    def __init__(self, plugin_id: str, message: str | None = None) -> None:
        self.plugin_id = plugin_id
        msg = message or (
            f"Plugin {plugin_id!r} declares both observe_only=true and "
            "may_short_circuit=true, which are mutually exclusive"
        )
        super().__init__(msg)

    def to_envelope(self) -> dict[str, str]:
        base = super().to_envelope()
        base["plugin_id"] = self.plugin_id
        return base


class PluginOrderingCycle(PluginStartupError):
    """``must_run_before`` / ``must_run_after`` constraints form a cycle.

    The error message MUST name cycle members in arrow notation, e.g.::

        org.example.plugin-a -> org.example.plugin-b -> org.example.plugin-a

    Spec reference: ``spec/ports/middleware/03-plugin-contract.md §4.2``, §6.2
    """

    error_code: ClassVar[str] = "plugin_ordering_cycle"

    def __init__(self, cycle_members: list[str]) -> None:
        self.cycle_members = cycle_members
        # Produce arrow notation: a -> b -> a (repeat first to close)
        if cycle_members:
            arrow = " -> ".join(cycle_members + [cycle_members[0]])
        else:
            arrow = "(empty cycle)"
        super().__init__(f"plugin_ordering_cycle: {arrow}")

    def to_envelope(self) -> dict[str, str]:
        base = super().to_envelope()
        base["cycle"] = " -> ".join(
            self.cycle_members + ([self.cycle_members[0]] if self.cycle_members else [])
        )
        return base


class PluginRequirementUnmet(PluginStartupError):
    """A ``requires`` capability is not provided by any loaded plugin.

    Names both the unsatisfied capability string and the plugin that declared
    the requirement.

    Spec reference: ``spec/ports/middleware/03-plugin-contract.md §2.4``, §6.2
    """

    error_code: ClassVar[str] = "plugin_requirement_unmet"

    def __init__(self, plugin_id: str, capability: str) -> None:
        self.plugin_id = plugin_id
        self.capability = capability
        super().__init__(
            f"Plugin {plugin_id!r} requires capability {capability!r} "
            "which is not provided by any loaded plugin"
        )

    def to_envelope(self) -> dict[str, str]:
        base = super().to_envelope()
        base["plugin_id"] = self.plugin_id
        base["capability"] = self.capability
        return base
