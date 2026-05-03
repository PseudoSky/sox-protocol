# SPDX-License-Identifier: Apache-2.0
"""Plugin manifest loader for the SOX Protocol plugin discovery system.

Reads and validates ``sox-plugin.yaml`` manifests bundled with out-of-tree
plugins discovered through Python entry-points (group ``sox_protocol.plugins``).
Runs boot-time protocol_version compatibility checks, capability orthogonality
assertions, and env-var canonicalization.

Hard import boundary: this module MUST NOT import from ``sox_protocol.adapters``.

Spec references:
    - ``spec/schemas/sox-plugin.schema.json`` — manifest JSON Schema
    - ``spec/ports/middleware/03-plugin-contract.md §2.3`` — capability orthogonality
    - ``spec/ports/middleware/03-plugin-contract.md §7.2`` — env-var canonicalization
    - ``spec/ports/middleware/06-versioning.md §4`` — protocol_version negotiation
    - ``spec/ports/middleware/06-versioning.md §5.1`` — mismatch envelope shape
    - ``spec/ports/middleware/06-versioning.md §6.2`` — signatures v1 enforcement
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from sox_protocol.core.middleware.errors import (
    PluginCapabilityConflict,
    PluginManifestInvalid,
    PluginProtocolVersionMismatch,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema loading (resolved relative to this file at import time)
# ---------------------------------------------------------------------------

_SCHEMA_PATH: Path = (
    Path(__file__).parents[6]  # packages/python/src/sox_protocol/core/middleware/ -> repo root
    / "spec"
    / "schemas"
    / "sox-plugin.schema.json"
)


def _load_schema() -> dict[str, Any]:
    """Load and return the sox-plugin JSON Schema from the spec directory.

    Returns:
        Parsed JSON Schema dict.

    Raises:
        RuntimeError: If the schema file cannot be found (programming error,
            not a plugin author error).
    """
    if not _SCHEMA_PATH.exists():
        raise RuntimeError(
            f"sox-plugin.schema.json not found at {_SCHEMA_PATH}. "
            "This is a packaging error in the sox-protocol distribution."
        )
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


# Cache the schema after first load.
_SCHEMA: dict[str, Any] | None = None


def _get_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = _load_schema()
    return _SCHEMA


# ---------------------------------------------------------------------------
# Manifest dataclass
# ---------------------------------------------------------------------------


@dataclass
class Manifest:
    """Parsed and validated plugin manifest.

    Mirrors the ``spec`` block of ``sox-plugin.schema.json``, augmented with
    the ``id`` and ``version`` fields from ``metadata``.

    Attributes:
        id: Globally unique reverse-DNS plugin identifier (``metadata.id``).
        version: Plugin content version string (``metadata.version``).
        kind: Plugin taxonomy kind (``spec.plugin_kind``).
        protocol_version: Raw ``spec.protocol_version`` string (verbatim from
            manifest; used for negotiation and error envelopes).
        plugin_capabilities: List of single-key capability dicts
            (``spec.plugin_capabilities``).
        requires: Capability strings / plugin ids this plugin depends on.
        must_run_before: Ordering constraint — run before these ids/caps.
        must_run_after: Ordering constraint — run after these ids/caps.
        signatures: Reserved signatures array (v1: present but unenforced).
        applies_to: Optional scope restriction dict.
    """

    id: str
    version: str
    kind: str
    protocol_version: str
    plugin_capabilities: list[dict[str, Any]] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    must_run_before: list[str] = field(default_factory=list)
    must_run_after: list[str] = field(default_factory=list)
    signatures: list[dict[str, Any]] = field(default_factory=list)
    applies_to: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# npm caret / tilde normalizer
# ---------------------------------------------------------------------------

_NPM_CARET_RE = re.compile(
    r"^\^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?P<pre>-[0-9A-Za-z.-]+)?$"
)
_NPM_CARET_MINOR_RE = re.compile(
    r"^\^(?P<major>\d+)\.(?P<minor>\d+)$"
)
_NPM_CARET_MAJOR_RE = re.compile(
    r"^\^(?P<major>\d+)$"
)
_NPM_TILDE_RE = re.compile(
    r"^~(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?P<pre>-[0-9A-Za-z.-]+)?$"
)
_NPM_WILDCARD_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.[xX*]$"
)
_NPM_MAJOR_WILDCARD_RE = re.compile(
    r"^(?P<major>\d+)\.[xX*]$"
)
_NPM_BARE_VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$"
)


def _normalize_npm_caret(s: str) -> str | None:
    """Attempt to convert an npm-form range string to a PEP 440 specifier.

    Handles: ``^M.m.p``, ``^M.m``, ``^M``, ``~M.m.p``, ``M.m.x`` wildcards,
    ``M.x`` wildcards, bare ``*``, and plain version pins.

    Args:
        s: The raw ``protocol_version`` string from the manifest.

    Returns:
        A PEP 440 specifier string if conversion succeeded, else ``None``.
    """
    stripped = s.strip()

    # Bare wildcard: matches any version.
    if stripped in ("*", "x", "X"):
        return ">=0.0.0"

    # ^M.m.p  →  >=M.m.p,<(M+1).0.0
    m = _NPM_CARET_RE.match(stripped)
    if m:
        major, minor, patch = m.group("major"), m.group("minor"), m.group("patch")
        pre = m.group("pre") or ""
        lower = f"{major}.{minor}.{patch}{pre}"
        upper = f"{int(major) + 1}.0.0"
        return f">={lower},<{upper}"

    # ^M.m  →  >=M.m.0,<(M+1).0.0
    m = _NPM_CARET_MINOR_RE.match(stripped)
    if m:
        major, minor = m.group("major"), m.group("minor")
        return f">={major}.{minor}.0,<{int(major) + 1}.0.0"

    # ^M  →  >=M.0.0,<(M+1).0.0
    m = _NPM_CARET_MAJOR_RE.match(stripped)
    if m:
        major = m.group("major")
        return f">={major}.0.0,<{int(major) + 1}.0.0"

    # ~M.m.p  →  >=M.m.p,<M.(m+1).0  (npm patch-range tilde)
    m = _NPM_TILDE_RE.match(stripped)
    if m:
        major, minor, patch = m.group("major"), m.group("minor"), m.group("patch")
        pre = m.group("pre") or ""
        lower = f"{major}.{minor}.{patch}{pre}"
        upper = f"{major}.{int(minor) + 1}.0"
        return f">={lower},<{upper}"

    # M.m.x or M.m.*  →  >=M.m.0,<M.(m+1).0
    m = _NPM_WILDCARD_RE.match(stripped)
    if m:
        major, minor = m.group("major"), m.group("minor")
        return f">={major}.{minor}.0,<{major}.{int(minor) + 1}.0"

    # M.x or M.*  →  >=M.0.0,<(M+1).0.0
    m = _NPM_MAJOR_WILDCARD_RE.match(stripped)
    if m:
        major = m.group("major")
        return f">={major}.0.0,<{int(major) + 1}.0.0"

    # Plain bare version pin: M.m.p  →  ==M.m.p
    m = _NPM_BARE_VERSION_RE.match(stripped)
    if m:
        return f"=={stripped}"

    return None


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def parse_version_range(s: str) -> SpecifierSet:
    """Parse a PEP 440 or npm-form version range into a ``SpecifierSet``.

    Strategy:
    1. Try ``packaging.specifiers.SpecifierSet(s)`` directly (PEP 440 first,
       per ``06-versioning.md §2.2``).
    2. On failure, attempt ``_normalize_npm_caret(s)`` and re-parse.
    3. On second failure, raise ``PluginManifestInvalid``.

    Note on ``~=`` vs ``~`` disambiguation (risk R1):
    PEP 440 ``~=1.0`` means ``>=1.0,<2`` (compatible release) and is parsed
    in step 1.  npm ``~1.0.0`` means ``>=1.0.0,<1.1.0`` and is handled in
    step 2's tilde normalizer.  The two forms are distinguishable by the
    leading ``~=`` (PEP 440) vs bare ``~`` (npm), so disambiguation is
    unambiguous.

    Args:
        s: The raw ``protocol_version`` string from the manifest.

    Returns:
        A ``packaging.specifiers.SpecifierSet`` representing the parsed range.

    Raises:
        PluginManifestInvalid: If the string cannot be parsed as either form.
    """
    stripped = s.strip()

    # Step 1: try PEP 440 directly.
    try:
        return SpecifierSet(stripped)
    except InvalidSpecifier:
        pass

    # Step 2: try npm normalization then re-parse.
    normalized = _normalize_npm_caret(stripped)
    if normalized is not None:
        try:
            return SpecifierSet(normalized)
        except InvalidSpecifier:
            pass

    raise PluginManifestInvalid(
        plugin_id="<unknown>",
        reason=f"protocol_version {s!r} is not a valid PEP 440 specifier or npm semver range",
        path="spec.protocol_version",
    )


def validate_manifest(doc: dict[str, Any]) -> Manifest:
    """Validate a parsed manifest dict against the JSON Schema and return a ``Manifest``.

    Performs:
    1. JSON Schema validation against ``spec/schemas/sox-plugin.schema.json``.
    2. Structural assertion that ``spec.signatures`` is present and is a list
       (per ADR 0004 §6 / ``06-versioning.md §6.2``).  Contents are NOT enforced.
    3. Constructs and returns a :class:`Manifest` from the validated dict.

    Args:
        doc: Parsed YAML/JSON dict from a ``sox-plugin.yaml`` file.

    Returns:
        A validated :class:`Manifest` instance.

    Raises:
        PluginManifestInvalid: On schema validation failure or structural
            violation.
    """
    import jsonschema

    plugin_id: str = (
        doc.get("metadata", {}).get("id", "<unknown>")
        if isinstance(doc.get("metadata"), dict)
        else "<unknown>"
    )

    schema = _get_schema()
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as exc:
        path = ".".join(str(p) for p in exc.absolute_path) if exc.absolute_path else ""
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason=exc.message,
            path=path,
        ) from exc

    # Structural check: signatures present and is a list (schema already
    # enforces this, but be explicit for defence-in-depth).
    spec_block: dict[str, Any] = doc["spec"]
    if "signatures" not in spec_block or not isinstance(spec_block["signatures"], list):
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason="spec.signatures must be present and must be a list (may be empty)",
            path="spec.signatures",
        )

    # Log a one-time INFO if non-empty signatures are present (v1 deferred verification).
    if spec_block["signatures"]:
        _log.info(
            "Plugin %r has non-empty signatures array; "
            "signature verification is deferred to v1.x and not enforced in v1.",
            plugin_id,
        )

    metadata: dict[str, Any] = doc["metadata"]
    return Manifest(
        id=metadata["id"],
        version=metadata["version"],
        kind=spec_block["plugin_kind"],
        protocol_version=spec_block["protocol_version"],
        plugin_capabilities=spec_block.get("plugin_capabilities") or [],
        requires=spec_block.get("requires") or [],
        must_run_before=spec_block.get("must_run_before") or [],
        must_run_after=spec_block.get("must_run_after") or [],
        signatures=spec_block.get("signatures") or [],
        applies_to=spec_block.get("applies_to"),
    )


def check_protocol_version(
    manifest: Manifest,
    host_protocol_version: str,
) -> None:
    """Assert the host protocol version satisfies the plugin's declared range.

    Implements the §4.2 algorithm from ``06-versioning.md``:
    1. Parse ``manifest.protocol_version`` into a range R.
    2. Test whether ``host_protocol_version`` ∈ R.
    3. Accept → return None.
    4. Reject → raise :class:`PluginProtocolVersionMismatch` with the five-field
       envelope from §5.1.

    Pre-release semantics (§4.4): when ``host_protocol_version`` contains a
    pre-release identifier the range is evaluated with ``prereleases=True`` so
    that pre-release host versions can be matched by ranges that include a
    pre-release lower bound.

    Args:
        manifest: The validated plugin manifest.
        host_protocol_version: The host's single protocol version string
            (e.g. ``"1.0.0"``).

    Raises:
        PluginManifestInvalid: If ``manifest.protocol_version`` cannot be parsed
            (distinct from a version mismatch).
        PluginProtocolVersionMismatch: If the host version falls outside the
            plugin's declared range.
    """
    # Parse the plugin's declared range.
    try:
        specifier = parse_version_range(manifest.protocol_version)
    except PluginManifestInvalid:
        raise  # propagate with original context

    # Parse the host version so we can inspect for pre-release markers.
    try:
        host_ver = Version(host_protocol_version)
    except InvalidVersion as exc:
        raise PluginManifestInvalid(
            plugin_id=manifest.id,
            reason=f"host_protocol_version {host_protocol_version!r} is not a valid version: {exc}",
            path="",
        ) from exc

    # §4.4: enable prereleases when host is a pre-release build.
    prereleases = host_ver.is_prerelease
    if prereleases:
        specifier = SpecifierSet(str(specifier), prereleases=True)

    if host_ver in specifier:
        return  # compatible

    # Build a human-readable remediation hint.
    # Attempt to determine direction of mismatch.
    remediation = _build_remediation(manifest.protocol_version, host_protocol_version)

    raise PluginProtocolVersionMismatch(
        plugin_id=manifest.id,
        plugin_declares=manifest.protocol_version,
        host_supports=host_protocol_version,
        remediation=remediation,
    )


def _build_remediation(plugin_declares: str, host_version: str) -> str:
    """Build a human-readable remediation string for a version mismatch.

    Args:
        plugin_declares: The raw protocol_version string from the manifest.
        host_version: The host's protocol version string.

    Returns:
        A remediation hint string.
    """
    try:
        host_ver = Version(host_version)
        # Try to extract upper bound from PEP 440 specifier.
        specifier = SpecifierSet(plugin_declares)
        for spec in specifier:
            if spec.operator in ("<", "<="):
                try:
                    upper = Version(spec.version)
                    if host_ver >= upper:
                        return (
                            f"upgrade plugin to a version supporting protocol >={host_version}"
                        )
                except InvalidVersion:
                    pass
            if spec.operator in (">", ">="):
                try:
                    lower = Version(spec.version)
                    if host_ver < lower:
                        return (
                            f"upgrade host to protocol version >={spec.version} "
                            f"or use a plugin version supporting {host_version}"
                        )
                except InvalidVersion:
                    pass
    except (InvalidSpecifier, InvalidVersion):
        pass
    return "check protocol_version compatibility between plugin and host"


def assert_capability_orthogonality(manifest: Manifest) -> None:
    """Assert that ``observe_only`` and ``may_short_circuit`` are not both true.

    Per ``spec/ports/middleware/03-plugin-contract.md §2.3``, setting both
    flags is a logical contradiction: a plugin cannot promise never to
    short-circuit while also declaring that it may.

    The host MUST enforce this independently of JSON Schema validation.

    Args:
        manifest: The validated plugin manifest to check.

    Raises:
        PluginCapabilityConflict: If both ``observe_only: true`` and
            ``may_short_circuit: true`` appear in ``plugin_capabilities``.
    """
    observe_only = False
    may_short_circuit = False

    for cap in manifest.plugin_capabilities:
        if cap.get("observe_only") is True:
            observe_only = True
        if cap.get("may_short_circuit") is True:
            may_short_circuit = True

    if observe_only and may_short_circuit:
        raise PluginCapabilityConflict(
            plugin_id=manifest.id,
            message=(
                f"Plugin {manifest.id!r} declares both observe_only=true and "
                "may_short_circuit=true in plugin_capabilities; these flags are "
                "mutually exclusive per 03-plugin-contract.md §2.3"
            ),
        )


def canonicalize_env_var(plugin_id: str, key: str) -> str:
    """Derive the canonical environment variable name for a plugin configuration key.

    Algorithm (``spec/ports/middleware/03-plugin-contract.md §7.2``):
    1. Replace every ``.`` and ``-`` in *plugin_id* with ``_``.
    2. Convert to uppercase.
    3. Prefix with ``SOX_PLUGIN_``.
    4. Append ``_`` followed by *key* (uppercased).

    Example::

        canonicalize_env_var("org.example.sox-jwt-auth", "JWKS_URL")
        # → "SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_JWKS_URL"

    Args:
        plugin_id: The plugin's ``metadata.id`` string.
        key: The configuration key (typically already uppercase; will be
            uppercased by this function).

    Returns:
        The canonical environment variable name.
    """
    normalized_id = plugin_id.replace(".", "_").replace("-", "_").upper()
    return f"SOX_PLUGIN_{normalized_id}_{key.upper()}"


def read_manifest_for_entry_point(ep: Any) -> dict[str, Any]:
    """Locate and parse the ``sox-plugin.yaml`` for an entry-point.

    Strategy:
    1. Obtain the distribution object from ``ep.dist``.
    2. Walk ``distribution.files`` looking for a file named ``sox-plugin.yaml``.
    3. Resolve the file relative to the distribution's data path and parse it.
    4. If not found, raise :class:`PluginManifestInvalid`.

    The entry-point name is used as the plugin id for error reporting before
    the manifest is parsed.

    Args:
        ep: A ``importlib.metadata.EntryPoint`` instance with a ``.dist``
            attribute pointing to its :class:`~importlib.metadata.Distribution`.

    Returns:
        Parsed YAML dict (not yet validated against JSON Schema).

    Raises:
        PluginManifestInvalid: If ``sox-plugin.yaml`` cannot be found or parsed.
    """
    plugin_id: str = getattr(ep, "name", "<unknown>")

    dist = getattr(ep, "dist", None)
    if dist is None:
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason="Entry-point has no .dist attribute; cannot locate sox-plugin.yaml",
        )

    # Walk distribution.files for sox-plugin.yaml.
    dist_files = dist.files or []
    manifest_rel: Any = None
    for f in dist_files:
        if f.name == "sox-plugin.yaml":
            manifest_rel = f
            break

    if manifest_rel is None:
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason=(
                "sox-plugin.yaml not found in the distribution's file list. "
                "Ensure the manifest is included in the package's data files."
            ),
        )

    # Resolve to an absolute path via the distribution's locate_file helper.
    try:
        manifest_path = Path(dist.locate_file(manifest_rel))
    except Exception as exc:  # noqa: BLE001
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason=f"Could not resolve sox-plugin.yaml path: {exc}",
        ) from exc

    if not manifest_path.exists():
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason=f"sox-plugin.yaml resolved to {manifest_path} but the file does not exist",
        )

    try:
        with manifest_path.open(encoding="utf-8") as fh:
            doc: dict[str, Any] = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason=f"Failed to parse sox-plugin.yaml as YAML: {exc}",
        ) from exc

    if not isinstance(doc, dict):
        raise PluginManifestInvalid(
            plugin_id=plugin_id,
            reason="sox-plugin.yaml top-level value must be a YAML mapping",
        )

    return doc


# Re-export error classes so callers can import them from this module
# (per the plan's public_api list for plugin_loader.py).
__all__ = [
    "Manifest",
    "read_manifest_for_entry_point",
    "validate_manifest",
    "parse_version_range",
    "check_protocol_version",
    "assert_capability_orthogonality",
    "canonicalize_env_var",
    "PluginManifestInvalid",
    "PluginProtocolVersionMismatch",
    "PluginCapabilityConflict",
]
