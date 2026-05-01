#!/usr/bin/env tsx
// SPDX-License-Identifier: Apache-2.0
/**
 * validate-manifest.ts — manifest round-trip validation script.
 *
 * Loads each sox-plugin example YAML, validates against sox-plugin.schema.json
 * using AJV, and runs two negative tests:
 *   1. Wrong apiVersion is rejected.
 *   2. Capability conflict (observe_only:true + may_short_circuit:true) is rejected.
 *
 * Exits 0 on all-pass; non-zero with first-failure detail on any failure.
 *
 * Usage:
 *   cd packages/typescript && npx tsx scripts/validate-manifest.ts
 *
 * Spec reference: spec/schemas/sox-plugin.schema.json
 */

import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse as parseYaml } from 'yaml';
import AjvModule from 'ajv';
// AJV ships both CJS and ESM; the default export is the constructor in both
// module systems but TypeScript's NodeNext resolution surfaces the class via
// the named export when the package uses "exports" with conditions.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Ajv = (AjvModule as any).default ?? AjvModule;

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..', '..', '..');
const SCHEMA_PATH = resolve(REPO_ROOT, 'spec', 'schemas', 'sox-plugin.schema.json');
const EXAMPLES_DIR = resolve(REPO_ROOT, 'spec', 'schemas', 'examples');

// ---------------------------------------------------------------------------
// Load schema and compile validator
// ---------------------------------------------------------------------------

const schema = JSON.parse(readFileSync(SCHEMA_PATH, 'utf8'));
const ajv = new Ajv({ strict: false, allErrors: false });
const validate = ajv.compile(schema);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadYaml(filePath: string): unknown {
  return parseYaml(readFileSync(filePath, 'utf8'));
}

function assertValid(label: string, data: unknown): void {
  const ok = validate(data);
  if (!ok) {
    const detail = ajv.errorsText(validate.errors);
    console.error(`FAIL [${label}]: expected valid, got errors:\n  ${detail}`);
    process.exit(1);
  }
  console.log(`PASS [${label}]: valid`);
}

function assertInvalid(label: string, data: unknown): void {
  const ok = validate(data);
  if (ok) {
    console.error(`FAIL [${label}]: expected invalid, but schema accepted it`);
    process.exit(1);
  }
  console.log(`PASS [${label}]: correctly rejected — ${ajv.errorsText(validate.errors)}`);
}

// ---------------------------------------------------------------------------
// Positive tests — all 3 example fixtures must pass
// ---------------------------------------------------------------------------

assertValid(
  'interceptor example',
  loadYaml(resolve(EXAMPLES_DIR, 'sox-plugin.example.interceptor.yaml')),
);

assertValid(
  'transformer example',
  loadYaml(resolve(EXAMPLES_DIR, 'sox-plugin.example.transformer.yaml')),
);

assertValid(
  'provider example',
  loadYaml(resolve(EXAMPLES_DIR, 'sox-plugin.example.provider.yaml')),
);

// ---------------------------------------------------------------------------
// Negative test 1 — wrong apiVersion is rejected
// ---------------------------------------------------------------------------

assertInvalid('wrong apiVersion', {
  apiVersion: 'sox.dev/v2',  // not in enum ["sox.dev/v1"]
  kind: 'SoxPlugin',
  metadata: { id: 'org.example.test-plugin', version: '1.0.0' },
  spec: {
    protocol_version: '>=1.0,<2.0',
    plugin_kind: 'interceptor',
    signatures: [],
  },
});

// ---------------------------------------------------------------------------
// Negative test 2 — capability conflict: observe_only:true + may_short_circuit:true
// The schema's if/then constraint must reject this combination.
// ---------------------------------------------------------------------------

assertInvalid('capability conflict (observe_only + may_short_circuit)', {
  apiVersion: 'sox.dev/v1',
  kind: 'SoxPlugin',
  metadata: { id: 'org.example.conflict-plugin', version: '1.0.0' },
  spec: {
    protocol_version: '>=1.0,<2.0',
    plugin_kind: 'interceptor',
    plugin_capabilities: [
      { observe_only: true },
      { may_short_circuit: true },
    ],
    signatures: [],
  },
});

// ---------------------------------------------------------------------------
// All passed
// ---------------------------------------------------------------------------

console.log('\nAll 5 tests passed (3 positive + 2 negative). Schema round-trip: OK.');
