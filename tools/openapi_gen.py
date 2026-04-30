# SPDX-License-Identifier: Apache-2.0
"""OpenAPI 3.1 document generator for the SOX HTTP transport.

Reads ``spec/operations/*.{input,output}.schema.json`` and emits
``spec/transports/http/openapi.yaml``.

Deterministic ordering: operations are sorted alphabetically; schema keys are
sorted at every level.

Usage::

    python3 tools/openapi_gen.py
    python3 -m openapi_spec_validator spec/transports/http/openapi.yaml

Spec reference: ``spec/operations/*.json``
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC_OPS_DIR = _REPO_ROOT / "spec" / "operations"
_OUT_PATH = _REPO_ROOT / "spec" / "transports" / "http" / "openapi.yaml"

_PROTOCOL_VERSION = "1.0"

# Operations that should be marked x-experimental (x-status: planned in schema)
_PLANNED_MARKER = "x-status: planned"


def _load_schema(path: Path) -> dict[str, object]:
    """Load and return a JSON schema from *path*.

    Args:
        path: Path to a ``.json`` schema file.

    Returns:
        Parsed schema dict.
    """
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[return-value]


def _strip_meta(schema: dict[str, object]) -> dict[str, object]:
    """Remove JSON Schema meta-fields not needed in OpenAPI.

    Args:
        schema: Raw JSON schema dict.

    Returns:
        Cleaned schema dict (with ``$schema``, ``$id``, ``$comment``,
        ``examples`` removed from the top level).
    """
    drop = {"$schema", "$id", "$comment", "examples"}
    return {k: v for k, v in schema.items() if k not in drop}


def _discover_operations(spec_dir: Path) -> list[str]:
    """Discover all operation names from input schema files.

    Args:
        spec_dir: Directory containing ``<op>.input.schema.json`` files.

    Returns:
        Sorted list of operation name strings.
    """
    ops: list[str] = []
    for p in sorted(spec_dir.glob("*.input.schema.json")):
        name = p.name.replace(".input.schema.json", "")
        ops.append(name)
    return sorted(ops)


def generate(spec_dir: Path, out_path: Path) -> None:
    """Generate the OpenAPI 3.1 document and write it to *out_path*.

    Args:
        spec_dir: Directory containing operation schema JSON files.
        out_path: Output path for the generated YAML.
    """
    operations = _discover_operations(spec_dir)

    # Build components/schemas from all input+output schemas
    components_schemas: dict[str, object] = {}
    paths: dict[str, object] = {}

    for op in operations:
        input_path = spec_dir / f"{op}.input.schema.json"
        output_path = spec_dir / f"{op}.output.schema.json"

        input_schema = _strip_meta(_load_schema(input_path))
        output_schema = _strip_meta(_load_schema(output_path))

        # Check for planned/experimental marker
        input_raw = input_path.read_text(encoding="utf-8")
        is_planned = _PLANNED_MARKER in input_raw

        input_ref = f"{op}Input"
        output_ref = f"{op}Output"
        components_schemas[input_ref] = input_schema
        components_schemas[output_ref] = output_schema

        # Build path item
        path_key = f"/v1/ops/{op}"
        operation_obj: dict[str, object] = {
            "summary": f"SOX {op} operation",
            "operationId": op,
            "tags": [_tag_for(op)],
            "security": [{"BearerAuth": []}],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{input_ref}"}
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{output_ref}"}
                        }
                    },
                },
                "400": {"description": "Validation error (sox-error envelope)"},
                "401": {"description": "Missing or invalid credential"},
                "500": {"description": "Internal server error"},
            },
        }
        if is_planned:
            operation_obj["deprecated"] = True
            operation_obj["x-experimental"] = True

        paths[path_key] = {"post": operation_obj}

    # Add /v1/stream (SSE)
    paths["/v1/stream"] = {
        "get": {
            "summary": "Live message stream (Server-Sent Events)",
            "operationId": "stream",
            "tags": ["streaming"],
            "security": [{"BearerAuth": []}],
            "parameters": [
                {
                    "name": "Last-Event-ID",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Resume cursor: last received seq value.",
                }
            ],
            "responses": {
                "200": {
                    "description": "SSE stream of message events",
                    "content": {"text/event-stream": {"schema": {"type": "string"}}},
                },
                "401": {"description": "Missing or invalid credential"},
            },
        }
    }

    # Add /health
    paths["/health"] = {
        "get": {
            "summary": "Server health probe",
            "operationId": "health",
            "tags": ["meta"],
            "security": [],
            "responses": {
                "200": {
                    "description": "Server is live",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "protocol_version": {"type": "string"},
                                    "store_ok": {"type": "boolean"},
                                    "uptime_s": {"type": "number"},
                                },
                            }
                        }
                    },
                }
            },
        }
    }

    # Add sox-error schema
    components_schemas["SoxError"] = {
        "type": "object",
        "required": ["error_code", "message"],
        "properties": {
            "error_code": {"type": "string"},
            "message": {"type": "string"},
            "detail": {"nullable": True},
            "retry_after": {"type": "integer", "nullable": True},
        },
    }

    doc: dict[str, object] = {
        "openapi": "3.1.0",
        "info": {
            "title": "SOX Protocol HTTP Transport",
            "version": _PROTOCOL_VERSION,
            "description": (
                "SOX Protocol — inter-agent channels over HTTP. "
                "All operations are POST to /v1/ops/<operation>. "
                "Live push via GET /v1/stream (Server-Sent Events)."
            ),
        },
        "servers": [{"url": "http://localhost:8765", "description": "Local development"}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Bearer token resolved to agent_id by the identity layer.",
                }
            },
            "schemas": dict(sorted(components_schemas.items())),
        },
        "paths": dict(sorted(paths.items())),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.dump(doc, sort_keys=True, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Generated {out_path.relative_to(_REPO_ROOT)}")


def _tag_for(op: str) -> str:
    """Derive an OpenAPI tag from an operation name.

    Args:
        op: Operation name (e.g. ``group_create``).

    Returns:
        Tag string (e.g. ``"groups"`` or ``"channels"``).
    """
    if op.startswith("group"):
        return "groups"
    if op.startswith("channels"):
        return "channels"
    if op in ("send", "recv", "subscribe", "unsubscribe", "replay", "list_channels"):
        return "channels"
    if op == "list_agents":
        return "presence"
    return "operations"


def main() -> None:
    """CLI entrypoint: generate OpenAPI doc and exit."""
    generate(_SPEC_OPS_DIR, _OUT_PATH)


if __name__ == "__main__":
    main()
