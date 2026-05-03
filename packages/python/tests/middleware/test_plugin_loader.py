# SPDX-License-Identifier: Apache-2.0
"""Unit tests for plugin_loader.py.

Covers: manifest validation, parse_version_range, check_protocol_version,
assert_capability_orthogonality, and canonicalize_env_var.

Spec references:
    - spec/ports/middleware/03-plugin-contract.md §2.3 (orthogonality)
    - spec/ports/middleware/03-plugin-contract.md §7.2 (env-var canonicalization)
    - spec/ports/middleware/06-versioning.md §4 (negotiation algorithm)
    - spec/ports/middleware/06-versioning.md §5.1 (mismatch envelope)
    - spec/ports/middleware/06-versioning.md §6.2 (signatures v1 enforcement)
"""

from __future__ import annotations

from typing import Any

import pytest

from sox_protocol.core.middleware.errors import (
    PluginCapabilityConflict,
    PluginManifestInvalid,
    PluginProtocolVersionMismatch,
)
from sox_protocol.core.middleware.plugin_loader import (
    Manifest,
    assert_capability_orthogonality,
    canonicalize_env_var,
    check_protocol_version,
    parse_version_range,
    validate_manifest,
)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_valid_manifest(
    *,
    plugin_id: str = "io.sox.test-plugin",
    version: str = "1.0.0",
    plugin_kind: str = "interceptor",
    protocol_version: str = ">=1.0,<2.0",
    plugin_capabilities: list[dict[str, Any]] | None = None,
    requires: list[str] | None = None,
    must_run_before: list[str] | None = None,
    must_run_after: list[str] | None = None,
    signatures: list[dict[str, Any]] | None = None,
    applies_to: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal valid sox-plugin manifest dict."""
    spec: dict[str, Any] = {
        "protocol_version": protocol_version,
        "plugin_kind": plugin_kind,
        "signatures": signatures if signatures is not None else [],
    }
    if plugin_capabilities is not None:
        spec["plugin_capabilities"] = plugin_capabilities
    if requires is not None:
        spec["requires"] = requires
    if must_run_before is not None:
        spec["must_run_before"] = must_run_before
    if must_run_after is not None:
        spec["must_run_after"] = must_run_after
    if applies_to is not None:
        spec["applies_to"] = applies_to

    return {
        "apiVersion": "sox.dev/v1",
        "kind": "SoxPlugin",
        "metadata": {
            "id": plugin_id,
            "version": version,
        },
        "spec": spec,
    }


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------


class TestValidateManifest:
    def test_valid_minimum_interceptor(self) -> None:
        """Minimal interceptor manifest (kind=interceptor, signatures=[]) validates."""
        doc = _make_valid_manifest()
        m = validate_manifest(doc)
        assert isinstance(m, Manifest)
        assert m.id == "io.sox.test-plugin"
        assert m.version == "1.0.0"
        assert m.kind == "interceptor"
        assert m.protocol_version == ">=1.0,<2.0"
        assert m.signatures == []

    def test_valid_transformer_kind(self) -> None:
        """Transformer kind manifest validates."""
        doc = _make_valid_manifest(plugin_kind="transformer")
        m = validate_manifest(doc)
        assert m.kind == "transformer"

    def test_valid_provider_kind(self) -> None:
        doc = _make_valid_manifest(plugin_kind="provider")
        m = validate_manifest(doc)
        assert m.kind == "provider"

    def test_valid_hook_kind(self) -> None:
        doc = _make_valid_manifest(plugin_kind="hook")
        m = validate_manifest(doc)
        assert m.kind == "hook"

    def test_invalid_missing_signatures_field(self) -> None:
        """Manifest without signatures raises PluginManifestInvalid (ADR 0004 §6)."""
        doc = _make_valid_manifest()
        del doc["spec"]["signatures"]
        with pytest.raises(PluginManifestInvalid) as exc_info:
            validate_manifest(doc)
        assert exc_info.value.error_code == "plugin_manifest_invalid"
        assert "signatures" in str(exc_info.value).lower() or "signatures" in exc_info.value.reason.lower()

    def test_invalid_missing_protocol_version(self) -> None:
        doc = _make_valid_manifest()
        del doc["spec"]["protocol_version"]
        with pytest.raises(PluginManifestInvalid) as exc_info:
            validate_manifest(doc)
        assert exc_info.value.error_code == "plugin_manifest_invalid"

    def test_invalid_missing_metadata_id(self) -> None:
        doc = _make_valid_manifest()
        del doc["metadata"]["id"]
        with pytest.raises(PluginManifestInvalid):
            validate_manifest(doc)

    def test_invalid_bad_api_version(self) -> None:
        doc = _make_valid_manifest()
        doc["apiVersion"] = "sox.dev/v99"
        with pytest.raises(PluginManifestInvalid):
            validate_manifest(doc)

    def test_invalid_bad_plugin_kind(self) -> None:
        """A manifest with plugin_kind='guard' (former kind) is rejected."""
        doc = _make_valid_manifest()
        doc["spec"]["plugin_kind"] = "guard"
        with pytest.raises(PluginManifestInvalid):
            validate_manifest(doc)

    def test_signatures_present_but_contents_unenforced(self) -> None:
        """Non-empty signatures array loads cleanly in v1 (R5 reservation)."""
        doc = _make_valid_manifest(
            signatures=[{"algorithm": "sha256-manifest-hash", "value": "abc123"}]
        )
        m = validate_manifest(doc)
        assert len(m.signatures) == 1
        assert m.signatures[0]["algorithm"] == "sha256-manifest-hash"

    def test_validate_returns_correct_capabilities(self) -> None:
        doc = _make_valid_manifest(
            plugin_capabilities=[{"may_short_circuit": True}, {"auth.method": "jwt-bearer"}]
        )
        m = validate_manifest(doc)
        assert len(m.plugin_capabilities) == 2

    def test_validate_envelope_path_populated(self) -> None:
        """PluginManifestInvalid.to_envelope() includes plugin_id and reason."""
        doc = _make_valid_manifest()
        del doc["spec"]["signatures"]
        with pytest.raises(PluginManifestInvalid) as exc_info:
            validate_manifest(doc)
        env = exc_info.value.to_envelope()
        assert "error_code" in env
        assert env["error_code"] == "plugin_manifest_invalid"
        assert "reason" in env

    def test_id_pattern_valid(self) -> None:
        """Plugin id with multiple segments and hyphens is accepted."""
        doc = _make_valid_manifest(plugin_id="org.example.sox-jwt-auth")
        m = validate_manifest(doc)
        assert m.id == "org.example.sox-jwt-auth"

    def test_id_pattern_invalid_single_segment(self) -> None:
        """Single-segment id (no dots) is rejected by schema pattern."""
        doc = _make_valid_manifest(plugin_id="nodotsid")
        with pytest.raises(PluginManifestInvalid):
            validate_manifest(doc)


# ---------------------------------------------------------------------------
# parse_version_range
# ---------------------------------------------------------------------------


class TestParseVersionRange:
    def test_pep440_range_accepted(self) -> None:
        """PEP 440 '>=1.0,<2.0' parses without fallback."""
        spec = parse_version_range(">=1.0,<2.0")
        from packaging.version import Version

        assert Version("1.0.0") in spec
        assert Version("1.9.9") in spec
        assert Version("2.0.0") not in spec

    def test_pep440_compatible_release(self) -> None:
        """PEP 440 '~=1.0' (compatible release) parses directly."""
        spec = parse_version_range("~=1.0")
        from packaging.version import Version

        assert Version("1.5.0") in spec
        # ~=1.0 means >=1.0, <2 (not patch-only)
        assert Version("2.0.0") not in spec

    def test_pep440_exact_pin(self) -> None:
        spec = parse_version_range("==1.0.0")
        from packaging.version import Version

        assert Version("1.0.0") in spec
        assert Version("1.0.1") not in spec

    def test_npm_caret_accepted(self) -> None:
        """npm caret '^1.0.0' parses via npm normalizer (R1 dual-form path)."""
        spec = parse_version_range("^1.0.0")
        from packaging.version import Version

        assert Version("1.0.0") in spec
        assert Version("1.9.9") in spec
        assert Version("2.0.0") not in spec

    def test_npm_caret_vs_pep440_tilde_disambiguation(self) -> None:
        """~=1.0 (PEP 440, >=1.0,<2) vs ~1.0.0 (npm, >=1.0.0,<1.1.0) — R1."""
        from packaging.version import Version

        # PEP 440 compatible-release: ~=1.0 matches 1.5
        pep440 = parse_version_range("~=1.0")
        assert Version("1.5.0") in pep440

        # npm tilde: ~1.0.0 is patch-only >=1.0.0,<1.1.0 — does NOT match 1.5
        npm_tilde = parse_version_range("~1.0.0")
        assert Version("1.0.5") in npm_tilde
        assert Version("1.5.0") not in npm_tilde

    def test_npm_wildcard_major_minor(self) -> None:
        spec = parse_version_range("1.0.x")
        from packaging.version import Version

        assert Version("1.0.0") in spec
        assert Version("1.0.9") in spec
        assert Version("1.1.0") not in spec

    def test_npm_wildcard_major(self) -> None:
        spec = parse_version_range("1.x")
        from packaging.version import Version

        assert Version("1.0.0") in spec
        assert Version("1.9.0") in spec
        assert Version("2.0.0") not in spec

    def test_bare_version_pin(self) -> None:
        """Plain '1.0.0' (no operator) treated as ==1.0.0."""
        spec = parse_version_range("1.0.0")
        from packaging.version import Version

        assert Version("1.0.0") in spec
        assert Version("1.0.1") not in spec

    def test_invalid_string_raises_manifest_invalid(self) -> None:
        """Unparseable string raises PluginManifestInvalid, not raw packaging error."""
        with pytest.raises(PluginManifestInvalid) as exc_info:
            parse_version_range("not a range !!!!")
        assert exc_info.value.error_code == "plugin_manifest_invalid"
        assert "protocol_version" in str(exc_info.value)

    def test_empty_string_is_caught_at_schema_level(self) -> None:
        """Empty protocol_version ('') is rejected by schema minLength:1 at validate_manifest.

        parse_version_range('') itself returns an unconstrained SpecifierSet
        (PEP 440 valid) — the empty-string gate is the JSON Schema validator,
        not the range parser.  Confirm the schema validation rejects it.
        """
        doc = _make_valid_manifest(protocol_version="")
        with pytest.raises(PluginManifestInvalid):
            validate_manifest(doc)

    def test_returns_specifier_set_type(self) -> None:
        from packaging.specifiers import SpecifierSet

        result = parse_version_range(">=1.0,<2.0")
        assert isinstance(result, SpecifierSet)


# ---------------------------------------------------------------------------
# check_protocol_version
# ---------------------------------------------------------------------------


class TestCheckProtocolVersion:
    def _manifest(self, protocol_version: str = ">=1.0,<2.0") -> Manifest:
        return Manifest(
            id="io.sox.test-plugin",
            version="1.0.0",
            kind="interceptor",
            protocol_version=protocol_version,
        )

    def test_compatible_pep440_passes(self) -> None:
        """Host 1.0.0 in >=1.0,<2.0 — no exception."""
        check_protocol_version(self._manifest(">=1.0,<2.0"), "1.0.0")  # must not raise

    def test_compatible_npm_caret_passes(self) -> None:
        """npm caret '^1.0.0', host 1.0.0 — no exception (R1 dual-form path)."""
        check_protocol_version(self._manifest("^1.0.0"), "1.0.0")

    def test_compatible_host_1_5(self) -> None:
        check_protocol_version(self._manifest(">=1.0,<2.0"), "1.5.0")

    def test_incompatible_host_too_new(self) -> None:
        """Host 2.0.0 outside >=1.0,<2.0 — PluginProtocolVersionMismatch."""
        with pytest.raises(PluginProtocolVersionMismatch) as exc_info:
            check_protocol_version(self._manifest(">=1.0,<2.0"), "2.0.0")
        exc = exc_info.value
        assert exc.error_code == "plugin_protocol_version_mismatch"
        assert exc.plugin_id == "io.sox.test-plugin"
        assert exc.plugin_declares == ">=1.0,<2.0"
        assert exc.host_supports == "2.0.0"
        assert exc.remediation  # non-empty

    def test_incompatible_host_too_old(self) -> None:
        """Host 0.9.0 outside >=1.0,<2.0 — PluginProtocolVersionMismatch."""
        with pytest.raises(PluginProtocolVersionMismatch):
            check_protocol_version(self._manifest(">=1.0,<2.0"), "0.9.0")

    def test_mismatch_envelope_five_fields(self) -> None:
        """Five-field envelope per 06-versioning.md §5.1."""
        with pytest.raises(PluginProtocolVersionMismatch) as exc_info:
            check_protocol_version(self._manifest(">=1.0,<2.0"), "2.0.0")
        env = exc_info.value.to_envelope()
        for field in ("error_code", "plugin_id", "plugin_declares", "host_supports", "remediation"):
            assert field in env, f"Missing field {field!r} in mismatch envelope"

    def test_plugin_declares_verbatim(self) -> None:
        """plugin_declares must reproduce the verbatim protocol_version string."""
        raw = ">=1.0,<2.0"
        with pytest.raises(PluginProtocolVersionMismatch) as exc_info:
            check_protocol_version(self._manifest(raw), "2.0.0")
        assert exc_info.value.plugin_declares == raw

    def test_unparseable_protocol_version_raises_manifest_invalid(self) -> None:
        """Unparseable protocol_version raises PluginManifestInvalid (not mismatch)."""
        with pytest.raises(PluginManifestInvalid):
            check_protocol_version(self._manifest("not a version!!!"), "1.0.0")

    def test_prerelease_host_with_explicit_opt_in(self) -> None:
        """Host 1.0.0rc1, plugin range >=1.0.0a0,<2.0 — plugin opted in."""
        check_protocol_version(self._manifest(">=1.0.0a0,<2.0"), "1.0.0rc1")

    def test_prerelease_host_no_opt_in_refused(self) -> None:
        """Host 1.0.0rc1, plugin range >=1.0.0,<2.0 — no opt-in → refused (§4.4)."""
        with pytest.raises(PluginProtocolVersionMismatch):
            check_protocol_version(self._manifest(">=1.0.0,<2.0"), "1.0.0rc1")

    def test_remediation_upgrade_plugin(self) -> None:
        """When host is newer than upper bound, remediation says 'upgrade plugin'."""
        with pytest.raises(PluginProtocolVersionMismatch) as exc_info:
            check_protocol_version(self._manifest(">=0.5,<1.0"), "1.0.0")
        assert "upgrade plugin" in exc_info.value.remediation.lower()

    def test_remediation_upgrade_host(self) -> None:
        """When host is older than lower bound, remediation says 'upgrade host'."""
        with pytest.raises(PluginProtocolVersionMismatch) as exc_info:
            check_protocol_version(self._manifest(">=2.0,<3.0"), "1.0.0")
        assert "upgrade host" in exc_info.value.remediation.lower()


# ---------------------------------------------------------------------------
# assert_capability_orthogonality
# ---------------------------------------------------------------------------


class TestAssertCapabilityOrthogonality:
    def _manifest(self, caps: list[dict[str, Any]]) -> Manifest:
        return Manifest(
            id="io.sox.test-plugin",
            version="1.0.0",
            kind="interceptor",
            protocol_version=">=1.0,<2.0",
            plugin_capabilities=caps,
        )

    def test_no_flags_passes(self) -> None:
        assert_capability_orthogonality(self._manifest([]))

    def test_observe_only_alone_passes(self) -> None:
        assert_capability_orthogonality(self._manifest([{"observe_only": True}]))

    def test_may_short_circuit_alone_passes(self) -> None:
        assert_capability_orthogonality(self._manifest([{"may_short_circuit": True}]))

    def test_observe_only_false_and_may_short_circuit_true_passes(self) -> None:
        """observe_only=false + may_short_circuit=true is the guard pattern — ok."""
        assert_capability_orthogonality(
            self._manifest([{"observe_only": False}, {"may_short_circuit": True}])
        )

    def test_both_true_raises_conflict(self) -> None:
        """observe_only=true + may_short_circuit=true → PluginCapabilityConflict."""
        with pytest.raises(PluginCapabilityConflict) as exc_info:
            assert_capability_orthogonality(
                self._manifest([{"observe_only": True}, {"may_short_circuit": True}])
            )
        exc = exc_info.value
        assert exc.error_code == "plugin_capability_conflict"
        assert exc.plugin_id == "io.sox.test-plugin"

    def test_conflict_with_extra_caps(self) -> None:
        """Conflict detected even when mixed with capability strings."""
        with pytest.raises(PluginCapabilityConflict):
            assert_capability_orthogonality(
                self._manifest([
                    {"observe_only": True},
                    {"auth.method": "jwt-bearer"},
                    {"may_short_circuit": True},
                ])
            )

    def test_conflict_to_envelope(self) -> None:
        with pytest.raises(PluginCapabilityConflict) as exc_info:
            assert_capability_orthogonality(
                self._manifest([{"observe_only": True}, {"may_short_circuit": True}])
            )
        env = exc_info.value.to_envelope()
        assert env["error_code"] == "plugin_capability_conflict"
        assert "plugin_id" in env


# ---------------------------------------------------------------------------
# canonicalize_env_var
# ---------------------------------------------------------------------------


class TestCanonicalizeEnvVar:
    def test_example_from_spec(self) -> None:
        """Spec §7.2 example: org.example.sox-jwt-auth + JWKS_URL."""
        result = canonicalize_env_var("org.example.sox-jwt-auth", "JWKS_URL")
        assert result == "SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_JWKS_URL"

    def test_dots_replaced_with_underscore(self) -> None:
        result = canonicalize_env_var("my.plugin", "KEY")
        assert "." not in result

    def test_hyphens_replaced_with_underscore(self) -> None:
        result = canonicalize_env_var("my-plugin.x", "KEY")
        assert "-" not in result

    def test_result_is_uppercase(self) -> None:
        result = canonicalize_env_var("my.plugin-x", "api_key")
        assert result == result.upper()

    def test_sox_plugin_prefix(self) -> None:
        result = canonicalize_env_var("io.sox.schema-strict", "DB_URL")
        assert result.startswith("SOX_PLUGIN_")

    def test_multi_segment_id(self) -> None:
        """Implementation plan test case: my.plugin-x + API_KEY."""
        result = canonicalize_env_var("my.plugin-x", "API_KEY")
        assert result == "SOX_PLUGIN_MY_PLUGIN_X_API_KEY"

    def test_complex_reverse_dns_id(self) -> None:
        """Test case from test_plan: org.example.sox-jwt-auth + JWKS_URL."""
        result = canonicalize_env_var("org.example.sox-jwt-auth", "JWKS_URL")
        assert result == "SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_JWKS_URL"

    def test_key_is_lowercased_input(self) -> None:
        """Key should be uppercased even if passed in lowercase."""
        result = canonicalize_env_var("io.sox.plugin", "my_key")
        assert result == "SOX_PLUGIN_IO_SOX_PLUGIN_MY_KEY"

    def test_provider_example_from_spec(self) -> None:
        """Spec §7.2 provider example: com.myco.sox-provider-redis-pool."""
        result = canonicalize_env_var("com.myco.sox-provider-redis-pool", "REDIS_URL")
        assert result == "SOX_PLUGIN_COM_MYCO_SOX_PROVIDER_REDIS_POOL_REDIS_URL"


# ---------------------------------------------------------------------------
# Integration: validate_manifest → check_protocol_version round-trip
# ---------------------------------------------------------------------------


class TestManifestRoundTrip:
    def test_full_valid_manifest_round_trip(self) -> None:
        """Full manifest: validate → check_protocol_version → orthogonality — all pass."""
        doc = _make_valid_manifest(
            plugin_id="org.example.sox-jwt-auth",
            version="1.2.0",
            plugin_kind="interceptor",
            protocol_version=">=1.0,<2.0",
            plugin_capabilities=[
                {"auth.method": "jwt-bearer"},
                {"may_short_circuit": True},
                {"observe_only": False},
            ],
            requires=["identity.registry"],
            must_run_before=["persistence.terminal"],
            signatures=[],
        )
        m = validate_manifest(doc)
        check_protocol_version(m, "1.0.0")
        assert_capability_orthogonality(m)
        assert m.id == "org.example.sox-jwt-auth"

    def test_orthogonality_conflict_surfaces_after_validation(self) -> None:
        """Schema if/then catches the conflict at validate_manifest time."""
        doc = _make_valid_manifest(
            plugin_capabilities=[{"observe_only": True}, {"may_short_circuit": True}]
        )
        # Schema if/then block should catch this at JSON Schema validation time.
        with pytest.raises((PluginManifestInvalid, PluginCapabilityConflict)):
            m = validate_manifest(doc)
            # If schema didn't catch it, our runtime check must.
            assert_capability_orthogonality(m)
