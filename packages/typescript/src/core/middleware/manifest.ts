// SPDX-License-Identifier: Apache-2.0
/**
 * SOX Plugin Manifest types — TypeScript binding of sox-plugin.schema.json.
 *
 * These types model the Backstage-style envelope (apiVersion/kind/metadata/spec)
 * adopted by ADR 0004 decision 2. They are types-only; no runtime validation
 * logic is present here. Schema validation uses AJV against
 * spec/schemas/sox-plugin.schema.json (see scripts/validate-manifest.ts).
 *
 * Spec references:
 *   spec/schemas/sox-plugin.schema.json
 *   docs/adr/0004-plugin-architecture.md §2
 *   spec/ports/middleware/06-versioning.md
 */

import type { PluginKind } from './protocol.js';

// ---------------------------------------------------------------------------
// SoxPluginSignature — reserved in v1 (signatures: [] is the expected value).
// v1.x adds hash pinning; v2.0 considers Sigstore/Cosign in-band verification.
// ---------------------------------------------------------------------------

export interface SoxPluginSignature {
  /** Signature algorithm identifier (reserved; no normative v1 values). */
  readonly algorithm: string;
  /** Signature value, algorithm-specific encoding. */
  readonly value: string;
}

// ---------------------------------------------------------------------------
// AppliesTo — optional scope restriction on operations and transports.
// Absent means applies to all operations on all transports.
// ---------------------------------------------------------------------------

export type SoxOperation =
  | '*'
  | 'send'
  | 'recv'
  | 'subscribe'
  | 'unsubscribe'
  | 'list_agents'
  | 'list_channels'
  | 'replay'
  | 'channels_ack'
  | 'channels_collect'
  | 'channels_heartbeat'
  | 'group_create'
  | 'group_invite'
  | 'group_join'
  | 'group_leave'
  | 'group_list_members';

export type SoxTransport = '*' | 'stdio' | 'http';

export interface SoxPluginAppliesTo {
  readonly operations?: readonly SoxOperation[];
  readonly transports?: readonly SoxTransport[];
}

// ---------------------------------------------------------------------------
// CapabilityItem — a single capability declaration.
// Each object has exactly one key:
//   Reserved boolean flags: observe_only, may_short_circuit (interceptor-only).
//   Capability strings: any other dot-namespaced key with a string value.
// ---------------------------------------------------------------------------

export type CapabilityItem =
  | { readonly observe_only: boolean }
  | { readonly may_short_circuit: boolean }
  | { readonly [capabilityKey: string]: string };

// ---------------------------------------------------------------------------
// SoxPluginSpec — the spec payload within the manifest envelope.
// ---------------------------------------------------------------------------

export interface SoxPluginSpec {
  /**
   * SOX plugin-protocol version range this plugin is compatible with.
   * Accepts PEP 440 specifier form (canonical) or npm semver range form.
   * Examples: ">=1.0,<2.0", "^1.0.0", "~=1.0", "==1.0.0"
   */
  readonly protocolVersion: string;

  /** Plugin taxonomy kind (4-kind 2-axis). */
  readonly pluginKind: PluginKind;

  /**
   * Declared capability flags and capability strings.
   * Max 16 items. Orthogonality: observe_only:true + may_short_circuit:true
   * is a plugin_capability_conflict startup error.
   */
  readonly pluginCapabilities?: readonly CapabilityItem[];

  /**
   * Optional scope restriction. Absent = applies to all operations/transports.
   * Irrelevant for lifecycle-axis kinds (provider, hook).
   */
  readonly appliesTo?: SoxPluginAppliesTo;

  /**
   * Capability strings or plugin ids that MUST be present before this plugin
   * can be loaded. Plugin_requirement_unmet if unsatisfied at startup.
   */
  readonly requires?: readonly string[];

  /** Ordering: this plugin MUST execute before the listed plugins/capabilities. */
  readonly mustRunBefore?: readonly string[];

  /** Ordering: this plugin MUST execute after the listed plugins/capabilities. */
  readonly mustRunAfter?: readonly string[];

  /**
   * Optional relative path or URL to JSON Schema validating this plugin's
   * runtime configuration (delivered via env vars SOX_PLUGIN_<ID>_<KEY> in v1).
   */
  readonly configSchemaRef?: string;

  /**
   * Reserved field. MUST be present; MAY be empty array.
   * v1 host ignores contents. v1.x adds hash pinning; v2.0 Sigstore/Cosign.
   */
  readonly signatures: readonly SoxPluginSignature[];
}

// ---------------------------------------------------------------------------
// SoxPluginMetadata — stable identifying metadata for the plugin.
// ---------------------------------------------------------------------------

export interface SoxPluginMetadata {
  /**
   * Globally unique, stable reverse-DNS plugin identifier.
   * ASCII lowercase, dots separate namespace segments, hyphens within segments.
   * Pattern: ^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$
   * Examples: "org.example.sox-jwt-auth", "io.sox.schema-strict"
   */
  readonly id: string;

  /**
   * Plugin content version. Full SemVer 2.0.0.
   * This is the plugin author's release version, not the protocol version.
   */
  readonly version: string;

  /** Optional human-readable name for UI and log display. */
  readonly displayName?: string;

  /** Optional human-readable description. Not used by the host runtime. */
  readonly description?: string;
}

// ---------------------------------------------------------------------------
// SoxPluginManifest — top-level envelope.
// Backstage/Kubernetes-style: apiVersion + kind + metadata + spec.
// ---------------------------------------------------------------------------

export interface SoxPluginManifest {
  /**
   * Manifest schema version. Fixed at 'sox.dev/v1' for the v1 contract.
   * A future incompatible revision uses 'sox.dev/v2'.
   */
  readonly apiVersion: 'sox.dev/v1';

  /**
   * Resource kind discriminator. Always 'SoxPlugin' for plugin manifests.
   */
  readonly kind: 'SoxPlugin';

  /** Stable identifying metadata. */
  readonly metadata: SoxPluginMetadata;

  /** Plugin contract specification. */
  readonly spec: SoxPluginSpec;
}

// ---------------------------------------------------------------------------
// Note on snake_case vs camelCase:
// The JSON/YAML schema uses snake_case (protocol_version, plugin_kind, etc.)
// These TypeScript types use camelCase for the interface field names per TS
// convention. The validate-manifest.ts script reads raw YAML (snake_case) and
// validates it against the JSON Schema directly without going through these
// types. These types represent the idiomatic TS-side shape after any
// deserialization/mapping layer.
// ---------------------------------------------------------------------------
