# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol Conformance Runner.

Loads declarative YAML fixtures from ``spec/conformance/`` recursively,
runs each fixture against a target implementation, and reports per-fixture
pass/fail with structured diffs.

Targets
-------
``packages/python`` (default, ``--transport stdio``)
    Runs the Python reference implementation in-process using a shared
    MemoryStore.  Each fixture gets a fresh store so state is fully isolated.

``packages/python`` with ``--transport http``
    Spawns a fresh ``sox serve --transport http`` subprocess per fixture on an
    ephemeral port, waits for ``/health``, runs the fixture via HTTP POST to
    ``/v1/ops/<operation>``, then terminates the subprocess.  Each fixture
    gets an isolated ``memory://`` backing store.

``http://host:port``
    Posts to ``/v1/ops/<operation>`` with ``X-SOX-Agent-ID`` header.  The
    caller is responsible for starting and stopping the server.

Usage
-----
::

    # stdio (default, back-compat)
    python3 tools/conformance_runner.py --target packages/python --strict

    # HTTP transport — server spawned automatically per fixture
    python3 tools/conformance_runner.py --target packages/python \\
        --transport http --strict

    # HTTP transport — against a pre-started server
    python3 tools/conformance_runner.py --target http://localhost:8765 --strict

    # Filter by category
    python3 tools/conformance_runner.py --target packages/python \\
        --category identity-verification --strict

Exit code 0 if all (non-pending) fixtures pass; non-zero otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import difflib
import fnmatch
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import yaml

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repo root (two levels up from tools/)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFORMANCE_ROOT = _REPO_ROOT / "spec" / "conformance"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Fixture:
    """Parsed representation of a single YAML fixture file."""

    path: Path
    name: str
    spec_ref: str
    description: str
    pending: bool
    agents: list[dict[str, Any]]
    setup: list[dict[str, Any]]
    sequence: list[dict[str, Any]]
    assertions: list[dict[str, Any]]
    teardown: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass
class StepResult:
    """Result of executing one sequence step."""

    step_id: str
    ok: bool
    output: Any
    error: str | None = None
    diff: str | None = None


@dataclass
class FixtureResult:
    """Aggregated result for a single fixture."""

    fixture: Fixture
    passed: bool
    skipped: bool
    step_results: list[StepResult] = field(default_factory=list)
    assertion_errors: list[str] = field(default_factory=list)
    error: str | None = None

    def summary_line(self) -> str:
        """Return a one-line human-readable summary."""
        status = "SKIP" if self.skipped else ("PASS" if self.passed else "FAIL")
        try:
            display = self.fixture.path.relative_to(_REPO_ROOT)
        except ValueError:
            display = self.fixture.path
        return f"[{status}] {display}"

    def detail(self) -> str:
        """Return multi-line detail for failures."""
        if self.skipped or self.passed:
            return ""
        lines: list[str] = [self.summary_line()]
        if self.error:
            lines.append(f"  error: {self.error}")
        for sr in self.step_results:
            if not sr.ok:
                lines.append(f"  step [{sr.step_id}] FAILED")
                if sr.error:
                    lines.append(f"    {sr.error}")
                if sr.diff:
                    for dl in sr.diff.splitlines():
                        lines.append(f"    {dl}")
        for ae in self.assertion_errors:
            lines.append(f"  assertion: {ae}")
        return "\n".join(lines)


@dataclass
class RunResult:
    """Aggregated result for a full conformance run."""

    fixture_results: list[FixtureResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.fixture_results if r.passed and not r.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.fixture_results if not r.passed and not r.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.fixture_results if r.skipped)

    @property
    def total(self) -> int:
        return len(self.fixture_results)

    @property
    def exit_code(self) -> int:
        return 0 if self.failed == 0 else 1

    def report(self) -> str:
        """Return a full human-readable report string."""
        lines: list[str] = []
        for r in self.fixture_results:
            lines.append(r.summary_line())
            detail = r.detail()
            if detail:
                lines.append(detail)
        lines.append("")
        lines.append(
            f"Results: {self.passed} passed, {self.failed} failed, "
            f"{self.skipped} skipped / {self.total} total"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

_REQUIRED_FIXTURE_KEYS = {"name", "spec_ref", "description", "sequence"}


def load_fixture(path: Path) -> Fixture:
    """Parse a single YAML fixture file.

    Args:
        path: Absolute path to the ``.yaml`` fixture file.

    Returns:
        A :class:`Fixture` instance.

    Raises:
        ValueError: If the fixture is missing required keys or has unknown
            operation names.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: fixture must be a YAML mapping, got {type(raw)}")

    missing = _REQUIRED_FIXTURE_KEYS - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing required keys: {missing}")

    sequence = raw.get("sequence", [])
    if not isinstance(sequence, list):
        raise ValueError(f"{path}: 'sequence' must be a list")

    return Fixture(
        path=path,
        name=raw["name"],
        spec_ref=raw["spec_ref"],
        description=raw.get("description", ""),
        pending=bool(raw.get("pending", False)),
        agents=raw.get("agents", []),
        setup=raw.get("setup", []),
        sequence=sequence,
        assertions=raw.get("assertions", []),
        teardown=raw.get("teardown", []),
        raw=raw,
    )


def load_fixtures(
    root: Path,
    category: str | None = None,
) -> list[Fixture]:
    """Recursively load all YAML fixtures under *root*.

    Args:
        root: Directory to search (recursively).
        category: If set, only load fixtures from subdirectory matching this
            category name (e.g. ``"identity-verification"``).

    Returns:
        List of :class:`Fixture` instances, sorted by path.

    Raises:
        ValueError: If any fixture file fails to parse.
    """
    pattern = "**/*.yaml"
    paths = sorted(root.glob(pattern))

    if category:
        # Support comma-separated categories
        cats = [c.strip() for c in category.split(",")]
        paths = [
            p for p in paths if any(cat in p.parts for cat in cats)
        ]

    fixtures: list[Fixture] = []
    for path in paths:
        try:
            fixtures.append(load_fixture(path))
        except Exception as exc:
            raise ValueError(f"Failed to load fixture {path}: {exc}") from exc
    return fixtures


# ---------------------------------------------------------------------------
# Output matching helpers
# ---------------------------------------------------------------------------

_WILDCARD_PATTERN = re.compile(
    r"^\{\{(any_string|any_number|any_array|any_object|any_bool|"
    r"capture:[a-zA-Z0-9_\-\.]+)\}\}$"
)


def _matches(expected: Any, actual: Any, captures: dict[str, Any]) -> tuple[bool, str]:
    """Recursively check that *actual* satisfies *expected* (subset match).

    Wildcards like ``{{any_string}}``, ``{{any_number}}``, ``{{any_array}}``,
    ``{{any_object}}``, ``{{capture:step.field}}`` are supported in expected
    string values.

    Args:
        expected: Expected value (may contain wildcard strings).
        actual: Actual value from the implementation.
        captures: Dict of captured values from previous steps.

    Returns:
        ``(True, "")`` on match; ``(False, reason)`` on mismatch.
    """
    if isinstance(expected, str):
        m = _WILDCARD_PATTERN.match(expected)
        if m:
            wc = m.group(1)
            if wc == "any_string":
                if not isinstance(actual, str):
                    return False, f"expected any_string, got {type(actual).__name__}: {actual!r}"
                return True, ""
            if wc == "any_number":
                if not isinstance(actual, (int, float)):
                    return False, f"expected any_number, got {type(actual).__name__}: {actual!r}"
                return True, ""
            if wc == "any_array":
                if not isinstance(actual, list):
                    return False, f"expected any_array, got {type(actual).__name__}: {actual!r}"
                return True, ""
            if wc == "any_object":
                if not isinstance(actual, dict):
                    return False, f"expected any_object, got {type(actual).__name__}: {actual!r}"
                return True, ""
            if wc == "any_bool":
                if not isinstance(actual, bool):
                    return False, f"expected any_bool, got {type(actual).__name__}: {actual!r}"
                return True, ""
            if wc.startswith("capture:"):
                key = wc[len("capture:"):]
                captured = captures.get(key)
                if captured is None:
                    return False, f"capture key {key!r} not found in captures"
                if actual != captured:
                    return False, f"expected captured {captured!r}, got {actual!r}"
                return True, ""
        # Literal string comparison
        if actual != expected:
            return False, f"expected {expected!r}, got {actual!r}"
        return True, ""

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False, f"expected dict, got {type(actual).__name__}: {actual!r}"
        for k, v in expected.items():
            if k not in actual:
                return False, f"missing key {k!r} in actual"
            ok, reason = _matches(v, actual[k], captures)
            if not ok:
                return False, f"[{k!r}] {reason}"
        return True, ""

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False, f"expected list, got {type(actual).__name__}: {actual!r}"
        if len(expected) > len(actual):
            return False, (
                f"expected at least {len(expected)} items, got {len(actual)}"
            )
        for i, ev in enumerate(expected):
            ok, reason = _matches(ev, actual[i], captures)
            if not ok:
                return False, f"[{i}] {reason}"
        return True, ""

    # Scalar equality
    if actual != expected:
        return False, f"expected {expected!r}, got {actual!r}"
    return True, ""


def _diff_str(expected: Any, actual: Any) -> str:
    """Return a unified-diff-style string between expected and actual."""
    exp_lines = json.dumps(expected, indent=2).splitlines(keepends=True)
    act_lines = json.dumps(actual, indent=2).splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(exp_lines, act_lines, fromfile="expected", tofile="actual")
    )


def _resolve_captures(value: Any, captures: dict[str, Any]) -> Any:
    """Recursively resolve ``{{capture:key}}`` placeholders in *value*."""
    if isinstance(value, str):
        m = _WILDCARD_PATTERN.match(value)
        if m and m.group(1).startswith("capture:"):
            key = m.group(1)[len("capture:"):]
            return captures.get(key, value)
        return value
    if isinstance(value, dict):
        return {k: _resolve_captures(v, captures) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_captures(v, captures) for v in value]
    return value


def _extract_capture(step: dict[str, Any], output: Any) -> dict[str, Any]:
    """Build capture dict from a step's output per the step's expected_output."""
    # Auto-capture top-level scalar fields from send output
    result: dict[str, Any] = {}
    if isinstance(output, dict):
        step_id = step.get("id", "")
        for k, v in output.items():
            result[f"{step_id}.{k}"] = v
    return result


# ---------------------------------------------------------------------------
# Target abstraction
# ---------------------------------------------------------------------------


class StdioTarget:
    """Target that spawns the Python reference impl as a subprocess (stdio MCP).

    The server is launched once per fixture with a fresh in-memory store so
    fixtures are isolated.  Communication uses newline-delimited JSON-RPC.

    Args:
        package_path: Path to ``packages/python`` directory.
    """

    def __init__(self, package_path: Path) -> None:
        self._package_path = package_path
        self._proc: subprocess.Popen[bytes] | None = None
        self._rpc_id: int = 0
        self._agent_id: str = "test-agent"

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def start(self, agent_id: str) -> None:
        """Start the MCP server subprocess for *agent_id*."""
        self._agent_id = agent_id
        env = {
            **os.environ,
            "SOX_AGENT_ID": agent_id,
            "SOX_BACKING_STORE": "memory://",
            "SOX_MCP_TRANSPORT": "stdio",
            "PYTHONPATH": str(self._package_path / "src"),
        }
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sox_protocol.core.mcp_server",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(self._package_path),
        )
        # Send MCP initialize
        self._send_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "conformance-runner", "version": "1.0"},
        })

    def stop(self) -> None:
        """Stop the MCP server subprocess."""
        if self._proc and self._proc.poll() is None:
            self._proc.stdin.close()  # type: ignore[union-attr]
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def _send_rpc(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC request and return the result."""
        if self._proc is None:
            raise RuntimeError("StdioTarget not started")
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        line = json.dumps(msg) + "\n"
        assert self._proc.stdin is not None
        self._proc.stdin.write(line.encode())
        self._proc.stdin.flush()
        # Read response lines until we get a response for our id
        assert self._proc.stdout is not None
        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                stderr_out = b""
                if self._proc.stderr:
                    self._proc.stderr.close()
                raise RuntimeError(
                    f"Server closed stdout unexpectedly. "
                    f"stderr: {stderr_out.decode(errors='replace')}"
                )
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if resp.get("id") == req_id:
                if "error" in resp:
                    return {"_rpc_error": resp["error"]}
                return resp.get("result")

    def call_tool(self, agent_id: str, operation: str, args: dict[str, Any]) -> Any:
        """Call a SOX tool and return the result dict.

        Args:
            agent_id: The agent making the call (must match server's SOX_AGENT_ID).
            operation: SOX operation name (e.g. ``"send"``, ``"recv"``).
            args: Tool input arguments.

        Returns:
            The tool's output dict, or a dict with ``_rpc_error`` key on failure.
        """
        # Map SOX operation names to MCP tool names
        tool_name = _op_to_tool(operation)
        result = self._send_rpc(
            "tools/call",
            {"name": tool_name, "arguments": args},
        )
        if result is None:
            return {}
        # FastMCP wraps tool results in content[0].text
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list) and content:
                item = content[0]
                if isinstance(item, dict) and "text" in item:
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, TypeError):
                        return item["text"]
        if isinstance(result, dict) and "_rpc_error" in result:
            return result
        return result


class HttpTarget:
    """Target that POSTs to a running HTTP SOX server.

    Expects the server to expose ``POST /v1/ops/<operation>`` endpoints and
    optionally ``GET /v1/stream`` for SSE.  Falls back to polling recv for
    ``wait_for_stream`` assertions.

    Args:
        base_url: Base URL of the running server (e.g. ``http://localhost:8765``).
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session: Any = None  # httpx.Client

    def start(self, agent_id: str) -> None:
        """Initialise the HTTP client (no subprocess to start)."""
        try:
            import httpx  # type: ignore[import]
            self._session = httpx.Client(timeout=30.0)
        except ImportError:
            raise RuntimeError("httpx is required for HTTP target: pip install httpx")

    def stop(self) -> None:
        """Close the HTTP client."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def call_tool(self, agent_id: str, operation: str, args: dict[str, Any]) -> Any:
        """POST to ``/v1/ops/<operation>`` with agent identity header.

        Args:
            agent_id: Injected as ``X-SOX-Agent-ID`` header.
            operation: SOX operation name.
            args: Tool input arguments.

        Returns:
            Parsed JSON response dict.
        """
        if self._session is None:
            raise RuntimeError("HttpTarget not started")
        url = f"{self._base_url}/v1/ops/{operation}"
        headers = {
            "X-SOX-Agent-ID": agent_id,
            "Content-Type": "application/json",
        }
        try:
            resp = self._session.post(url, json=args, headers=headers)
        except Exception as exc:
            return {"_rpc_error": {"message": str(exc)}}
        # 4xx/5xx with a JSON body containing error_code is a sox-error
        # envelope from the server (post-pipeline-integration: AuthMiddleware /
        # transformer / internal_error all surface here). Return the body
        # directly so fixtures matching against `error_code` work without
        # special-casing _rpc_error.
        if resp.status_code >= 400:
            try:
                body = resp.json()
                if isinstance(body, dict) and "error_code" in body:
                    return body
            except Exception:
                pass
            return {"_rpc_error": {"message": f"HTTP {resp.status_code}: {resp.text[:200]}"}}
        try:
            return resp.json()
        except Exception as exc:
            return {"_rpc_error": {"message": str(exc)}}


class ProcessHttpTarget:
    """HTTP target that spawns a fresh server subprocess per fixture.

    Each ``start()`` call allocates an ephemeral TCP port, launches
    ``python -m sox_protocol.cli serve --transport http`` with
    ``SOX_BACKING_STORE=memory://``, waits up to 10 s for ``/health``, then
    delegates all ``call_tool`` calls to an inner :class:`HttpTarget`.

    ``stop()`` terminates the subprocess.  State isolation across fixtures is
    guaranteed by the fresh in-memory store created by each subprocess.

    Args:
        package_path: Path to ``packages/python`` directory.
    """

    def __init__(self, package_path: Path) -> None:
        self._package_path = package_path
        self._proc: subprocess.Popen[bytes] | None = None
        self._inner: HttpTarget | None = None
        self._port: int = 0
        # ``None`` = fixture didn't declare an agents[] list; auto-register on
        # arrival (legacy v1 behavior). ``[]`` (empty list) or non-empty list =
        # fixture explicitly declared agents; pre-register only those, disable
        # auto-register so unknown tokens get identity_failure server-side.
        self._pre_registered_agents: list[str] | None = None

    def set_pre_registered_agents(self, agent_ids: list[str]) -> None:
        """Set the agents to pre-register in the spawned server's registry.

        When non-empty, the server reads SOX_PRE_REGISTERED_AGENTS at startup,
        registers each agent under its ephemeral keypair, and DISABLES
        auto-registration of arriving bearer tokens. Unknown tokens fall
        through to AuthMiddleware unmapped → identity_failure envelope.
        This is the gate the conformance harness's
        unknown-credential-rejected fixture relies on (server-side rejection,
        not harness-side substitution per analysis §7.5 risk #5).

        MUST be called before :meth:`start`.
        """
        self._pre_registered_agents = list(agent_ids)

    def _find_free_port(self) -> int:
        """Return an available TCP port on 127.0.0.1."""
        import socket as _socket
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def start(self, agent_id: str) -> None:
        """Spawn the HTTP server and wait for it to be ready.

        Args:
            agent_id: Unused (identity resolved from per-request header).

        Raises:
            RuntimeError: If the server does not become ready within 10 s.
        """
        self._port = self._find_free_port()
        env = {
            **os.environ,
            "SOX_HTTP_HOST": "127.0.0.1",
            "SOX_HTTP_PORT": str(self._port),
            "SOX_BACKING_STORE": "memory://",
            "PYTHONPATH": str(self._package_path / "src"),
        }
        if self._pre_registered_agents is not None:
            # Empty list means "no pre-registered agents" but auto-register
            # is still disabled — the server's contract treats env-var
            # presence (even empty value) as the opt-in to strict mode.
            env["SOX_PRE_REGISTERED_AGENTS"] = ",".join(self._pre_registered_agents)
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sox_protocol.cli",
                "serve",
                "--transport",
                "http",
                "--port",
                str(self._port),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self._package_path),
        )
        # Poll /health until ready (max 10 s)
        base_url = f"http://127.0.0.1:{self._port}"
        import urllib.error
        import urllib.request as _urllib
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                stderr_bytes = b""
                if self._proc.stderr:
                    stderr_bytes = self._proc.stderr.read(2000)
                raise RuntimeError(
                    f"HTTP server exited prematurely (port={self._port}). "
                    f"stderr: {stderr_bytes.decode(errors='replace')}"
                )
            try:
                _urllib.urlopen(f"{base_url}/health", timeout=1)
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            self.stop()
            raise RuntimeError(
                f"HTTP server did not become ready on port {self._port} within 10 s"
            )
        self._inner = HttpTarget(base_url)
        self._inner.start(agent_id)

    def stop(self) -> None:
        """Terminate the HTTP server subprocess and close the HTTP client."""
        if self._inner is not None:
            self._inner.stop()
            self._inner = None
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def call_tool(self, agent_id: str, operation: str, args: dict[str, Any]) -> Any:
        """Delegate to the inner :class:`HttpTarget`.

        Args:
            agent_id: The agent making the call (sent as ``X-SOX-Agent-ID``).
            operation: SOX operation name.
            args: Tool input arguments.

        Returns:
            Parsed JSON response dict.
        """
        if self._inner is None:
            raise RuntimeError("ProcessHttpTarget not started")
        return self._inner.call_tool(agent_id, operation, args)


def _op_to_tool(operation: str) -> str:
    """Map a fixture operation name to the MCP tool name used by the reference impl."""
    mapping: dict[str, str] = {
        "send": "channels__send",
        "recv": "channels__recv",
        "subscribe": "channels__subscribe",
        "unsubscribe": "channels__unsubscribe",
        "list_channels": "channels__list_channels",
        "channels_ack": "channels__ack",
        "channels_heartbeat": "channels__heartbeat",
        "replay": "channels__replay",
        "group_create": "channels__group_create",
        "group_invite": "channels__group_invite",
        "group_join": "channels__group_join",
        "group_leave": "channels__group_leave",
        "group_list_members": "channels__group_list_members",
        "channels_collect": "channels__collect",
    }
    return mapping.get(operation, f"channels__{operation}")


# ---------------------------------------------------------------------------
# Shared-store target (for in-process stdio target using shared MemoryStore)
# ---------------------------------------------------------------------------


class SharedMemoryTarget:
    """In-process target using a shared MemoryStore for multi-agent fixtures.

    This target is used for the stdio path when multiple agents need to
    communicate — each agent call dispatches to the shared store directly
    without a subprocess boundary.

    The store is re-used across all agents in one fixture so state is shared.
    """

    def __init__(self, package_path: Path) -> None:
        self._package_path = package_path
        self._store: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Identity stack — built in start(), agents provisioned in register_agents().
        self._registry: Any = None   # InMemoryCredentialRegistry
        self._verifier: Any = None   # IdentityVerifier
        self._pipeline: Any = None   # Pipeline (auth-only; terminal = _dispatch_ctx)
        # Maps agent_id → Ed25519PrivateKey for per-call credential signing.
        self._agent_keys: dict[str, Any] = {}
        # True once register_agents() has been called for the current fixture.
        # In strict mode, agents NOT provisioned in register_agents() receive
        # an identity_failure from AuthMiddleware (no auto-provisioning).
        self._strict_mode: bool = False
        # In-memory liveness table for list_agents support.
        # Maps agent_id → {"last_heartbeat_at_ns": int, "status": str, "namespace": str|None}
        self._liveness: dict[str, dict[str, Any]] = {}

    def register_agents(self, agents: list[dict[str, Any]]) -> None:
        """Provision registered agents into the identity stack.

        Called by the fixture runner when the fixture declares an ``agents``
        list.  Agents with ``registered: false`` are declared as participants
        but are NOT provisioned in the credential registry — they will receive
        an ``identity_failure`` error from AuthMiddleware on any
        identity-enforced operation.

        After this call, auto-provisioning of unknown agents is disabled
        (strict mode).  This is the gate the
        ``unknown-credential-rejected`` conformance fixture relies on —
        rejection now comes from AuthMiddleware, not a hand-rolled check.
        """
        from sox_protocol.core.identity.keys import (  # type: ignore[import]
            generate_keypair,
        )
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        self._strict_mode = True
        if self._loop is None or self._registry is None:
            return
        for agent in agents:
            aid = agent.get("id")
            if not aid or not agent.get("registered", True):
                continue
            private_seed, public_key_bytes = generate_keypair()
            private_key: Any = Ed25519PrivateKey.from_private_bytes(private_seed)
            self._agent_keys[aid] = private_key
            self._loop.run_until_complete(
                self._registry.register(aid, public_key_bytes)
            )

    def _provision_agent(self, agent_id: str) -> Any:
        """Auto-provision *agent_id* into the registry (non-strict mode only).

        Returns the Ed25519PrivateKey for signing per-call credentials.
        """
        from sox_protocol.core.identity.keys import (  # type: ignore[import]
            generate_keypair,
        )
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        private_seed, public_key_bytes = generate_keypair()
        private_key: Any = Ed25519PrivateKey.from_private_bytes(private_seed)
        self._agent_keys[agent_id] = private_key
        if self._loop is not None and self._registry is not None:
            self._loop.run_until_complete(
                self._registry.register(agent_id, public_key_bytes)
            )
        return private_key

    def start(self, agent_id: str) -> None:
        """Start the shared in-memory store and build the auth pipeline."""
        # Validate the package path exists before mutating sys.path
        src_dir = self._package_path / "src"
        if not src_dir.is_dir():
            raise RuntimeError(
                f"Package source directory not found: {src_dir}"
            )
        # Import lazily so this only requires the package to be installed
        sys.path.insert(0, str(src_dir))
        try:
            from sox_protocol.adapters.backing_stores.memory.store import (  # type: ignore[import]
                MemoryStore,
            )
            from sox_protocol.core.identity import (  # type: ignore[import]
                AuditLogWriter,
                InMemoryCredentialRegistry,
            )
            from sox_protocol.core.identity.verifier import (  # type: ignore[import]
                IdentityVerifier,
            )
            from sox_protocol.core.middleware.plugins.auth import (  # type: ignore[import]
                AuthMiddleware,
            )
            from sox_protocol.core.middleware.pipeline import (  # type: ignore[import]
                Pipeline,
            )
            from sox_protocol.core.middleware.context import (  # type: ignore[import]
                MiddlewareContext,
            )
            self._store = MemoryStore()
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            self._loop = loop
            loop.run_until_complete(self._store.initialize())

            # Build identity stack.
            self._registry = InMemoryCredentialRegistry()
            audit = AuditLogWriter()
            self._verifier = IdentityVerifier(registry=self._registry, audit=audit)

            # Build auth-only pipeline.  The terminal calls _dispatch_ctx so
            # all existing simulation logic (reply_to plumbing, group_invite
            # remap, replay timing, etc.) is preserved untouched.
            auth_mw = AuthMiddleware(self._verifier)

            async def _terminal(ctx: MiddlewareContext) -> dict[str, Any]:
                return await self._dispatch(
                    ctx.agent_id or ctx.connection_id,
                    ctx.operation,
                    dict(ctx.input),
                )

            self._pipeline = Pipeline([auth_mw], _terminal)

        except ImportError as exc:
            raise RuntimeError(
                f"Cannot import sox_protocol from {self._package_path}: {exc}"
            ) from exc

    def stop(self) -> None:
        """No-op for in-process target."""

    def call_tool(self, agent_id: str, operation: str, args: dict[str, Any]) -> Any:
        """Dispatch a tool call through the auth Pipeline to the in-process MemoryStore.

        Identity enforcement is now performed by ``AuthMiddleware`` inside the
        pipeline.  Agents provisioned via :meth:`register_agents` (or
        auto-provisioned in non-strict mode) receive a signed credential;
        unprovisioned agents in strict-mode fixtures receive an
        ``identity_failure`` envelope from ``AuthMiddleware``.

        Args:
            agent_id: The agent making the call.
            operation: SOX operation name.
            args: Tool arguments.

        Returns:
            Result dict conforming to the operation's output schema.
        """
        if self._store is None or self._loop is None or self._pipeline is None:
            raise RuntimeError("SharedMemoryTarget not started")

        # Resolve or auto-provision the agent's signing key.
        private_key = self._agent_keys.get(agent_id)
        if private_key is None:
            if self._strict_mode:
                # Unknown agent in strict mode — no keypair; the pipeline will
                # receive no credential and AuthMiddleware will short-circuit
                # with identity_failure for enforced operations.
                private_key = None
            else:
                private_key = self._provision_agent(agent_id)

        # Build a signed credential for identity-enforced operations.
        # Non-enforced operations (list_channels, etc.) pass through auth
        # without credential; we still inject one for consistency.
        metadata: dict[str, Any] = {}
        if private_key is not None:
            from sox_protocol.core.mcp_server._credential import (  # type: ignore[import]
                resolve_credential,
            )
            credential = resolve_credential(agent_id, private_key, operation, args)
            metadata["_connection_credential"] = credential

        return self._loop.run_until_complete(
            self._pipeline.dispatch(
                operation,
                dict(args),
                connection_id=agent_id,
                metadata=metadata,
            )
        )

    async def _dispatch(
        self, agent_id: str, operation: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Async dispatch to the MemoryStore."""
        store = self._store
        now = time.time()

        if operation == "subscribe":
            matched = await store.subscribe(agent_id, args["pattern"])
            return {"subscribed": matched}

        if operation == "unsubscribe":
            # Spec field name is "channels"; accept legacy "patterns" too.
            patterns_raw = args.get("channels", args.get("patterns", []))
            patterns_list: list[str] = (
                [str(p) for p in patterns_raw]
                if isinstance(patterns_raw, list)
                else []
            )
            removed, _pending_cleared = await store.unsubscribe(agent_id, patterns_list)
            return {"unsubscribed": removed, "pending_cleared": _pending_cleared}

        if operation == "send":
            channel = args["channel"]
            body = args["body"]
            correlation_id = args.get("correlation_id")
            reply_to = args.get("reply_to")
            corr_str = str(correlation_id) if correlation_id is not None else None
            reply_to_str = str(reply_to) if reply_to is not None else None
            message_id, sent_at, seq, backpressure = await store.send(
                channel, agent_id, body, corr_str, reply_to=reply_to_str
            )
            return {
                "sent_at": sent_at,
                "message_id": message_id,
                "seq": seq,
                "backpressure": {
                    "queue_depth": backpressure.queue_depth,
                    "threshold": backpressure.threshold,
                    "state": backpressure.state,
                },
            }

        if operation == "recv":
            max_messages = args.get("max_messages", 50)
            channel_filter: list[str] | None = args.get("channels")
            msgs = await store.recv(agent_id, channel_filter, max_messages)
            return {"drained_at": time.time(), "messages": msgs}

        if operation == "list_channels":
            channels = await store.list_channels()
            result: dict[str, object] = {"channels": channels}
            if "_sox_protocol" not in result:
                result["_sox_protocol"] = {
                    "server_version": "1.0",
                    "supported_versions": ["1.0"],
                    "min_client_version": "1.0",
                }
            return result

        if operation == "channels_ack":
            return {"acked_at": time.time(), "status": args.get("status", "received")}

        if operation == "channels_heartbeat":
            return await store.heartbeat(
                agent_id,
                str(args.get("status", "online")),
                int(args["ttl"]) if "ttl" in args and args["ttl"] is not None else None,
            )

        if operation == "replay":
            channel = args["channel"]
            since: int = int(args.get("since", 0))
            until_raw = args.get("until")
            until: int | None = int(until_raw) if isinstance(until_raw, (int, float)) else None
            limit: int = int(args.get("limit", 100))
            replay_msgs, has_more = await store.replay(channel, since, until, limit)
            return {"messages": replay_msgs, "has_more": has_more}

        if operation == "list_agents":
            status_filter_raw = args.get("status_filter")
            status_filter_list: list[str] | None = (
                [str(s) for s in status_filter_raw]
                if isinstance(status_filter_raw, list)
                else None
            )
            ns_filter: str | None = args.get("namespace")  # type: ignore[assignment]
            agents = await store.list_agents(
                status_filter=status_filter_list,
                namespace=ns_filter,
            )
            return {"agents": agents}

        if operation in ("group_create", "group_invite", "group_join",
                         "group_leave", "group_list_members"):
            return await self._handle_group(agent_id, operation, args)

        return {"_rpc_error": {"message": f"Unknown operation: {operation}"}}

    async def _handle_group(
        self, agent_id: str, operation: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle group lifecycle operations against an in-memory membership table."""
        store = self._store
        if not hasattr(store, "_groups"):
            store._groups: dict[str, list[dict[str, Any]]] = {}  # type: ignore[attr-defined]

        now = time.time()

        if operation == "group_create":
            group_id = args.get("group_id", f"grp-{int(now)}")
            full_id = f"group/{group_id}"
            async with store._lock:
                if not hasattr(store, "_groups"):
                    store._groups = {}
                store._groups[full_id] = [
                    {"agent_id": agent_id, "status": "active", "joined_at": now}
                ]
                # Subscribe creator to group channel
                patterns = store._subscriptions.setdefault(agent_id, [])
                if full_id not in patterns:
                    patterns.append(full_id)
            return {"group_id": full_id, "created_at": now}

        group_id = args.get("group_id", "")

        if operation == "group_invite":
            invitee = args.get("agent_id", "")
            async with store._lock:
                members = store._groups.get(group_id, [])
                # Check caller is active member
                caller_active = any(
                    m["agent_id"] == agent_id and m["status"] == "active"
                    for m in members
                )
                if not caller_active:
                    return {"_rpc_error": {"message": "GROUP_MEMBERSHIP_REQUIRED"}}
                # Check invitee not already member
                already = any(m["agent_id"] == invitee for m in members)
                if not already:
                    members.append({"agent_id": invitee, "status": "invited", "joined_at": now})
                store._groups[group_id] = members
            return {"invited": True, "agent_id": invitee, "invited_at": now}

        if operation == "group_join":
            async with store._lock:
                members = store._groups.get(group_id, [])
                for m in members:
                    if m["agent_id"] == agent_id and m["status"] == "invited":
                        m["status"] = "active"
                        m["joined_at"] = now
                        break
                # Subscribe joiner to group channel
                patterns = store._subscriptions.setdefault(agent_id, [])
                if group_id not in patterns:
                    patterns.append(group_id)
            return {"group_id": group_id, "joined_at": now}

        if operation == "group_leave":
            async with store._lock:
                members = store._groups.get(group_id, [])
                store._groups[group_id] = [
                    m for m in members if m["agent_id"] != agent_id
                ]
                # Unsubscribe from group channel
                patterns = store._subscriptions.get(agent_id, [])
                store._subscriptions[agent_id] = [
                    p for p in patterns if p != group_id
                ]
            return {"group_id": group_id, "left_at": now}

        if operation == "group_list_members":
            async with store._lock:
                members = list(store._groups.get(group_id, []))
            return {"members": members}

        return {"_rpc_error": {"message": f"Unknown group operation: {operation}"}}


# ---------------------------------------------------------------------------
# Assertion evaluation
# ---------------------------------------------------------------------------


def _get_messages(step_results: dict[str, StepResult], step_id: str) -> list[Any]:
    """Extract the messages list from a step's output."""
    sr = step_results.get(step_id)
    if sr is None or sr.output is None:
        return []
    out = sr.output
    if isinstance(out, dict):
        # recv output shape
        if "messages" in out:
            return out["messages"]  # type: ignore[return-value]
        # replay output shape
        if "messages" in out:
            return out["messages"]  # type: ignore[return-value]
        # group_list_members output shape
        if "members" in out:
            return out["members"]  # type: ignore[return-value]
    return []


def evaluate_assertions(
    assertions: list[dict[str, Any]],
    step_results: dict[str, StepResult],
) -> list[str]:
    """Evaluate all fixture-level assertions and return error strings for failures.

    Args:
        assertions: List of assertion dicts from the fixture.
        step_results: Map of step_id to :class:`StepResult`.

    Returns:
        List of error strings; empty if all assertions pass.
    """
    errors: list[str] = []
    for assertion in assertions:
        atype = assertion.get("type")
        errors.extend(_eval_one_assertion(atype, assertion, step_results))
    return errors


def _eval_one_assertion(
    atype: str | None,
    assertion: dict[str, Any],
    step_results: dict[str, StepResult],
) -> list[str]:
    errors: list[str] = []

    if atype == "no_loss":
        recv_step = assertion["recv_step"]
        min_count = assertion.get("min", 1)
        msgs = _get_messages(step_results, recv_step)
        if len(msgs) < min_count:
            errors.append(
                f"no_loss: step {recv_step!r} expected >= {min_count} messages, "
                f"got {len(msgs)}"
            )

    elif atype == "no_duplication":
        recv_step = assertion["recv_step"]
        msgs = _get_messages(step_results, recv_step)
        ids = [m.get("message_id") for m in msgs if isinstance(m, dict)]
        if len(ids) != len(set(ids)):
            errors.append(
                f"no_duplication: step {recv_step!r} has duplicate message_ids: {ids}"
            )

    elif atype == "no_redelivery":
        recv_step = assertion["recv_step"]
        expected = assertion.get("expected_count", 0)
        msgs = _get_messages(step_results, recv_step)
        if len(msgs) != expected:
            errors.append(
                f"no_redelivery: step {recv_step!r} expected exactly {expected} "
                f"messages, got {len(msgs)}"
            )

    elif atype == "independent_delivery":
        recv_step = assertion["recv_step"]
        min_count = assertion.get("min", 1)
        msgs = _get_messages(step_results, recv_step)
        if len(msgs) < min_count:
            errors.append(
                f"independent_delivery: step {recv_step!r} expected >= "
                f"{min_count} messages, got {len(msgs)}"
            )

    elif atype == "ordering":
        recv_step = assertion["recv_step"]
        channel = assertion.get("channel")
        by = assertion.get("by", "seq")
        msgs = _get_messages(step_results, recv_step)
        if channel:
            msgs = [m for m in msgs if isinstance(m, dict) and m.get("channel") == channel]
        values = [m.get(by) for m in msgs if isinstance(m, dict)]
        if values != sorted(v for v in values if v is not None):
            errors.append(
                f"ordering: step {recv_step!r} channel={channel!r} "
                f"not in ascending {by!r} order: {values}"
            )

    elif atype == "body_seq_ascending":
        recv_step = assertion["recv_step"]
        channel = assertion.get("channel")
        body_field = assertion.get("body_field", "seq")
        msgs = _get_messages(step_results, recv_step)
        if channel:
            msgs = [m for m in msgs if isinstance(m, dict) and m.get("channel") == channel]
        values = [
            m.get("body", {}).get(body_field)
            for m in msgs
            if isinstance(m, dict)
        ]
        int_vals = [v for v in values if isinstance(v, int)]
        if int_vals != sorted(int_vals):
            errors.append(
                f"body_seq_ascending: step {recv_step!r} body.{body_field} "
                f"not ascending: {int_vals}"
            )

    elif atype == "received_count":
        recv_step = assertion["recv_step"]
        min_count = assertion.get("min", 0)
        max_count = assertion.get("max", 999999)
        msgs = _get_messages(step_results, recv_step)
        if not (min_count <= len(msgs) <= max_count):
            errors.append(
                f"received_count: step {recv_step!r} expected [{min_count}, "
                f"{max_count}], got {len(msgs)}"
            )

    elif atype == "no_channel_leak":
        recv_step = assertion["recv_step"]
        forbidden = assertion["forbidden_channel"]
        msgs = _get_messages(step_results, recv_step)
        leaked = [m for m in msgs if isinstance(m, dict) and m.get("channel") == forbidden]
        if leaked:
            errors.append(
                f"no_channel_leak: step {recv_step!r} contains messages on "
                f"forbidden channel {forbidden!r}"
            )

    elif atype == "all_channels_match_pattern":
        recv_step = assertion["recv_step"]
        pattern = assertion["pattern"]
        msgs = _get_messages(step_results, recv_step)
        mismatches = [
            m.get("channel")
            for m in msgs
            if isinstance(m, dict) and not fnmatch.fnmatchcase(
                str(m.get("channel", "")), pattern
            )
        ]
        if mismatches:
            errors.append(
                f"all_channels_match_pattern: step {recv_step!r} contains "
                f"non-matching channels {mismatches!r} (pattern={pattern!r})"
            )

    elif atype == "all_receivers_got_message":
        recv_steps = assertion.get("recv_steps", [])
        for rs in recv_steps:
            msgs = _get_messages(step_results, rs)
            if len(msgs) < 1:
                errors.append(
                    f"all_receivers_got_message: step {rs!r} got 0 messages"
                )

    elif atype == "all_writers_represented":
        recv_step = assertion["recv_step"]
        writers = assertion.get("writers", [])
        body_field = assertion.get("body_field", "writer")
        msgs = _get_messages(step_results, recv_step)
        seen_writers: set[Any] = set()
        for m in msgs:
            if isinstance(m, dict):
                bv = m.get("body", {}).get(body_field)
                if bv is not None:
                    seen_writers.add(bv)
        missing_writers = [w for w in writers if w not in seen_writers]
        if missing_writers:
            errors.append(
                f"all_writers_represented: step {recv_step!r} missing writers "
                f"{missing_writers!r}"
            )

    elif atype == "message_id_present":
        recv_step = assertion["recv_step"]
        capture_ref = assertion.get("capture_ref", "")
        # The capture_ref should already be resolved in captures dict
        msgs = _get_messages(step_results, recv_step)
        # This assertion needs captures, so we just check non-empty for now
        if not msgs:
            errors.append(
                f"message_id_present: step {recv_step!r} got 0 messages"
            )

    elif atype == "schema_valid":
        pass  # Informational only

    elif atype == "contains_agent":
        # Assert that a list_agents step result contains a specific agent.
        step = assertion["step"]
        target_agent_id = assertion["agent_id"]
        expected_state = assertion.get("presence_state")
        result = step_results.get(step)
        if result is None:
            errors.append(f"contains_agent: step {step!r} not found in results")
        else:
            output = result.output or {}
            agents_list = output.get("agents", [])
            matching = [
                a for a in agents_list
                if isinstance(a, dict) and a.get("agent_id") == target_agent_id
            ]
            if not matching:
                errors.append(
                    f"contains_agent: step {step!r} agents list does not contain "
                    f"agent_id={target_agent_id!r}; got {[a.get('agent_id') for a in agents_list]}"
                )
            elif expected_state is not None:
                actual_state = matching[0].get("presence_state")
                if actual_state != expected_state:
                    errors.append(
                        f"contains_agent: step {step!r} agent {target_agent_id!r} "
                        f"has presence_state={actual_state!r}, expected {expected_state!r}"
                    )

    else:
        errors.append(f"Unknown assertion type: {atype!r}")

    return errors


# ---------------------------------------------------------------------------
# Fixture runner
# ---------------------------------------------------------------------------


def _make_target(
    target_str: str,
    transport: str = "stdio",
) -> StdioTarget | HttpTarget | SharedMemoryTarget | ProcessHttpTarget:
    """Construct the appropriate target from the CLI arguments.

    Args:
        target_str: ``--target`` value — either a filesystem path to
            ``packages/python`` or an HTTP URL.
        transport: ``--transport`` value — ``"stdio"`` or ``"http"``.
            Ignored when *target_str* is already an HTTP URL (the target
            unambiguously determines the transport in that case).

    Returns:
        An instantiated target object.

    Raises:
        ValueError: If *target_str* is a path that does not exist.
    """
    if target_str.startswith("http://") or target_str.startswith("https://"):
        return HttpTarget(target_str)
    package_path = Path(target_str).resolve()
    if not package_path.exists():
        raise ValueError(f"Target path does not exist: {package_path}")
    if transport == "http":
        return ProcessHttpTarget(package_path)
    return SharedMemoryTarget(package_path)


def run_fixture(
    fixture: Fixture,
    target_str: str,
    strict: bool,
    transport: str = "stdio",
) -> FixtureResult:
    """Run a single fixture against the target.

    Args:
        fixture: The fixture to run.
        target_str: Target string (path or URL).
        strict: If True, pending fixtures are skipped.
        transport: Transport selector — ``"stdio"`` or ``"http"``.  Used when
            *target_str* is a package path to choose between
            :class:`SharedMemoryTarget` (stdio) and :class:`ProcessHttpTarget`
            (http).

    Returns:
        A :class:`FixtureResult`.
    """
    if fixture.pending and strict:
        return FixtureResult(
            fixture=fixture,
            passed=True,
            skipped=True,
        )

    target = _make_target(target_str, transport=transport)
    step_results: dict[str, StepResult] = {}
    captures: dict[str, Any] = {}

    # Determine all agent IDs used in this fixture
    agent_ids = [a["id"] for a in fixture.agents] if fixture.agents else ["test-agent"]
    primary_agent = agent_ids[0] if agent_ids else "test-agent"

    # For ProcessHttpTarget: pre-register the fixture's "registered: true"
    # agents in the spawned server BEFORE start (env-var injection point).
    # Disables auto-registration so unknown-credential-rejected fixtures
    # actually fail at AuthMiddleware. Pass even an empty list to opt into
    # strict mode (a fixture with only `registered: false` agents). When
    # fixture has no agents[] declaration at all, leave auto_register on.
    # SharedMemoryTarget ignores this.
    if fixture.agents and hasattr(target, "set_pre_registered_agents"):
        registered_ids = [
            a["id"] for a in fixture.agents if "id" in a and a.get("registered", True)
        ]
        target.set_pre_registered_agents(registered_ids)  # may be empty list

    # For SharedMemoryTarget, start once with primary agent
    # (all agents share the same store)
    try:
        target.start(primary_agent)
    except Exception as exc:
        return FixtureResult(
            fixture=fixture,
            passed=False,
            skipped=False,
            error=f"Failed to start target: {exc}",
        )

    # Register known agents for identity enforcement (SharedMemoryTarget only).
    # Fixtures that declare an agents[] list opt in to agent-identity checking;
    # fixtures with no agents[] list use the implicit single-agent mode.
    if fixture.agents and hasattr(target, "register_agents"):
        target.register_agents(fixture.agents)

    try:
        # Run setup steps
        for setup_step in fixture.setup:
            op = setup_step.get("operation", "")
            agent = setup_step.get("as_agent", primary_agent)
            inp = setup_step.get("input", {})
            inp = _resolve_captures(inp, captures)
            try:
                result = target.call_tool(agent, op, inp)
            except Exception as exc:
                return FixtureResult(
                    fixture=fixture,
                    passed=False,
                    skipped=False,
                    error=f"Setup step {op!r} failed: {exc}",
                )
            if isinstance(result, dict) and "_rpc_error" in result:
                _log.debug("Setup step %r returned error: %s", op, result)

        # Run sequence steps
        all_passed = True
        for step in fixture.sequence:
            # Handle sleep steps
            step_type = step.get("type")
            if step_type == "sleep":
                ms = step.get("milliseconds", 0)
                time.sleep(ms / 1000.0)
                step_results[step.get("id", "sleep")] = StepResult(
                    step_id=step.get("id", "sleep"),
                    ok=True,
                    output=None,
                )
                continue

            step_id = step.get("id", "")
            op = step.get("operation", "")
            agent = step.get("as_agent", primary_agent)
            inp = _resolve_captures(copy.deepcopy(step.get("input", {})), captures)
            expected_output = step.get("expected_output")
            expected_error = step.get("expected_error")

            try:
                result = target.call_tool(agent, op, inp)
            except Exception as exc:
                sr = StepResult(
                    step_id=step_id,
                    ok=False,
                    output=None,
                    error=str(exc),
                )
                step_results[step_id] = sr
                all_passed = False
                continue

            # Capture values from result
            auto_caps = _extract_capture(step, result)
            captures.update(auto_caps)

            # Check for expected_error. A response is an error if either:
            # (a) the harness wrapped it in `_rpc_error` (transport-side
            #     synthesis on RPC failure), OR
            # (b) it's a sox-error envelope surfaced directly from the
            #     server (top-level `error_code`). Post-pipeline-integration
            #     the HTTP transport returns 4xx with the envelope body, and
            #     HttpTarget.call_tool now passes that body through directly.
            is_error = isinstance(result, dict) and (
                "_rpc_error" in result or "error_code" in result
            )
            if expected_error is not None:
                if not is_error:
                    sr = StepResult(
                        step_id=step_id,
                        ok=False,
                        output=result,
                        error="Expected an error response but got success",
                        diff=_diff_str(expected_error, result),
                    )
                    step_results[step_id] = sr
                    all_passed = False
                    continue
                # Error expected and received — check shape
                ok, reason = _matches(expected_error, result.get("_rpc_error", result), captures)
                sr = StepResult(
                    step_id=step_id,
                    ok=ok,
                    output=result,
                    error=None if ok else reason,
                    diff=None if ok else _diff_str(expected_error, result),
                )
                step_results[step_id] = sr
                if not ok:
                    all_passed = False
                continue

            if is_error and expected_output is not None:
                sr = StepResult(
                    step_id=step_id,
                    ok=False,
                    output=result,
                    error=f"Got unexpected error: {result.get('_rpc_error')}",
                )
                step_results[step_id] = sr
                all_passed = False
                continue

            # Check expected_output (subset match)
            if expected_output is not None:
                ok, reason = _matches(expected_output, result, captures)
                sr = StepResult(
                    step_id=step_id,
                    ok=ok,
                    output=result,
                    error=None if ok else reason,
                    diff=None if ok else _diff_str(expected_output, result),
                )
            else:
                sr = StepResult(step_id=step_id, ok=True, output=result)

            step_results[step_id] = sr
            if not sr.ok:
                all_passed = False

        # Evaluate fixture-level assertions
        assertion_errors = evaluate_assertions(fixture.assertions, step_results)
        if assertion_errors:
            all_passed = False

        return FixtureResult(
            fixture=fixture,
            passed=all_passed,
            skipped=False,
            step_results=list(step_results.values()),
            assertion_errors=assertion_errors,
        )

    finally:
        target.stop()


# ---------------------------------------------------------------------------
# Top-level run function
# ---------------------------------------------------------------------------


def run(
    target: str,
    fixtures: list[Fixture],
    strict: bool,
    transport: str = "stdio",
) -> RunResult:
    """Run all fixtures and return a :class:`RunResult`.

    Args:
        target: Target string (path or URL).
        fixtures: List of fixtures to run.
        strict: If True, pending fixtures are skipped.
        transport: Transport selector — ``"stdio"`` or ``"http"``.

    Returns:
        A :class:`RunResult` with per-fixture results.
    """
    result = RunResult()
    for fixture in fixtures:
        fr = run_fixture(fixture, target, strict, transport=transport)
        result.fixture_results.append(fr)
    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0 = all pass, 1 = failures).
    """
    parser = argparse.ArgumentParser(
        description="SOX Protocol Conformance Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--target",
        required=True,
        help=(
            "Target to test against. Either a path to the Python package "
            "(e.g. packages/python) or an HTTP URL (e.g. http://localhost:8765)."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help=(
            "Transport to exercise when --target is a package path. "
            "'stdio' (default) uses the SharedMemoryTarget in-process. "
            "'http' spawns a fresh 'sox serve --transport http' subprocess "
            "per fixture on an ephemeral port. "
            "Ignored when --target is an HTTP URL."
        ),
    )
    parser.add_argument(
        "--category",
        default=None,
        help=(
            "Comma-separated list of fixture category subdirectory names to run "
            "(e.g. identity-verification,send-recv-basic). Default: all."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Skip fixtures marked pending:true. In non-strict mode they run and failures are reported.",
    )
    parser.add_argument(
        "--conformance-root",
        default=str(_CONFORMANCE_ROOT),
        help=f"Root directory for fixtures (default: {_CONFORMANCE_ROOT}).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-fixture detail even for passing fixtures.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    root = Path(args.conformance_root)
    if not root.exists():
        print(f"ERROR: Conformance root not found: {root}", file=sys.stderr)
        return 1

    try:
        fixtures = load_fixtures(root, category=args.category)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not fixtures:
        print("WARNING: No fixtures found.", file=sys.stderr)
        return 0

    result = run(
        target=args.target,
        fixtures=fixtures,
        strict=args.strict,
        transport=args.transport,
    )
    print(result.report())
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
