# SPDX-License-Identifier: Apache-2.0
"""Thin wrapper that runs spec/conformance/runner/run.sh against the Python
reference implementation.

Architecture
------------
The SOX Python MCP server binds ``SOX_AGENT_ID`` at startup time — one
agent identity per process. Conformance scenarios involve multiple agent
identities (sender, receiver, broadcast subscribers, etc.).

This wrapper therefore:

1. Collects all distinct agent IDs used across every scenario file.
2. Starts one ``python -m sox_protocol.core.mcp_server`` HTTP process per
   agent ID, all sharing the **same SQLite backing store** (so messages sent
   by one agent's server are visible to another agent's server).
3. Builds an ``SOX_AGENT_URLS`` JSON map (agent_id -> HTTP URL) and passes
   it to ``spec/conformance/runner/run.sh``.
4. Streams runner output to stdout and propagates the exit code.
5. Shuts down all server processes when the runner exits.

Usage (direct):
    python packages/python/tests/conformance/run_python_impl.py

Usage (via pytest):
    pytest packages/python/tests/conformance/run_python_impl.py -v -m conformance

Environment overrides:
    SOX_CONFORMANCE_VERBOSE   Set to "1" to enable verbose MCP dumps in runner.
    SOX_CONFORMANCE_TIMEOUT   Seconds to wait for each server to start (default 20).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[4]
_PYTHON_PKG = _REPO_ROOT / "packages" / "python"
_CONFORMANCE_DIR = _REPO_ROOT / "spec" / "conformance"
_SCENARIOS_DIR = _CONFORMANCE_DIR / "scenarios"
_RUNNER = _CONFORMANCE_DIR / "runner" / "run.sh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Return an available TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _collect_agent_ids() -> list[str]:
    """Scan all scenario JSON files and return every distinct agent_id used."""
    ids: set[str] = set()
    for scenario_file in sorted(_SCENARIOS_DIR.glob("*.json")):
        scenario = json.loads(scenario_file.read_text())

        # From setup steps
        for step in scenario.get("setup", []):
            if "agent" in step:
                ids.add(step["agent"])

        # From main steps
        for step in scenario.get("steps", []):
            if "agent" in step:
                ids.add(step["agent"])

        # From agents dict (informational, but capture all values)
        agents = scenario.get("agents", {})
        for val in agents.values():
            if isinstance(val, str):
                ids.add(val)
            elif isinstance(val, list):
                ids.update(v for v in val if isinstance(v, str))

    return sorted(ids)


def _wait_for_server(url: str, timeout: float = 20.0) -> bool:
    """Poll until the MCP server at *url* responds to initialize."""
    deadline = time.monotonic() + timeout
    req_body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0.0.1"},
        },
    }).encode()
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                url,
                data=req_body,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


class _ConformanceHarness:
    """Manages a set of per-agent MCP server processes and runs the suite."""

    def __init__(self, db_path: str, timeout: float = 20.0) -> None:
        self._db_path = db_path
        self._timeout = timeout
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._urls: dict[str, str] = {}

    def start_agents(self, agent_ids: list[str]) -> None:
        for agent_id in agent_ids:
            port = _free_port()
            url = f"http://127.0.0.1:{port}/mcp"
            env = {
                **os.environ,
                "SOX_AGENT_ID": agent_id,
                "SOX_BACKING_STORE": f"sqlite://{self._db_path}",
                "SOX_MCP_TRANSPORT": "http",
                "SOX_HTTP_HOST": "127.0.0.1",
                "SOX_HTTP_PORT": str(port),
            }
            proc = subprocess.Popen(
                [sys.executable, "-m", "sox_protocol.core.mcp_server"],
                cwd=str(_PYTHON_PKG),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._procs[agent_id] = proc
            self._urls[agent_id] = url
            print(f"  Started server for {agent_id!r} on port {port}", flush=True)

    def wait_ready(self) -> None:
        for agent_id, url in self._urls.items():
            print(f"  Waiting for {agent_id!r} at {url} ...", flush=True)
            if not _wait_for_server(url, self._timeout):
                stderr = b""
                if self._procs[agent_id].poll() is not None:
                    _, stderr = self._procs[agent_id].communicate()
                raise RuntimeError(
                    f"Server for agent {agent_id!r} did not start within "
                    f"{self._timeout}s.\nstderr: {stderr.decode(errors='replace')}"
                )
            print(f"  Ready: {agent_id!r}", flush=True)

    def run_suite(self) -> int:
        agent_urls_json = json.dumps(self._urls)
        # Pick any URL as the default (runner uses SOX_AGENT_URLS for routing)
        default_url = next(iter(self._urls.values()))
        runner_env = {
            **os.environ,
            "SOX_SERVER_URL": default_url,
            "SOX_AGENT_URLS": agent_urls_json,
            "SCENARIOS_DIR": str(_SCENARIOS_DIR),
            "SCHEMAS_DIR": str(_CONFORMANCE_DIR / "schemas"),
            "SOX_VERBOSE": os.environ.get("SOX_CONFORMANCE_VERBOSE", "0"),
        }
        result = subprocess.run(
            ["sh", str(_RUNNER)],
            env=runner_env,
            cwd=str(_CONFORMANCE_DIR),
            check=False,
        )
        return result.returncode

    def shutdown(self) -> None:
        for agent_id, proc in self._procs.items():
            proc.terminate()
            try:
                _, err = proc.communicate(timeout=5)
                if err and os.environ.get("SOX_CONFORMANCE_VERBOSE") == "1":
                    print(f"\n[{agent_id} stderr]\n{err.decode(errors='replace')}",
                          flush=True)
            except subprocess.TimeoutExpired:
                proc.kill()


# ---------------------------------------------------------------------------
# pytest entry point
# ---------------------------------------------------------------------------

@pytest.mark.conformance
def test_python_conformance_suite() -> None:
    """Run all spec/conformance/scenarios/ against the Python MCP server.

    Starts one server process per agent identity in the scenarios (all sharing
    a SQLite backing store), then executes run.sh against them, then tears
    down. Fails if any scenario fails.
    """
    for cmd in ("sh", "jq", "curl"):
        if shutil.which(cmd) is None:
            pytest.skip(f"'{cmd}' not found — cannot run conformance suite")

    if not _RUNNER.exists():
        pytest.fail(f"Conformance runner not found: {_RUNNER}")

    scenarios = list(_SCENARIOS_DIR.glob("*.json"))
    if not scenarios:
        pytest.fail(f"No scenario files in {_SCENARIOS_DIR}")

    agent_ids = _collect_agent_ids()
    print(f"\nConformance suite: {len(scenarios)} scenarios, "
          f"{len(agent_ids)} agents: {agent_ids}", flush=True)

    timeout = float(os.environ.get("SOX_CONFORMANCE_TIMEOUT", "20"))

    with tempfile.TemporaryDirectory(prefix="sox-conformance-") as tmpdir:
        db_path = os.path.join(tmpdir, "conformance.db")
        harness = _ConformanceHarness(db_path=db_path, timeout=timeout)
        try:
            harness.start_agents(agent_ids)
            harness.wait_ready()
            exit_code = harness.run_suite()
        finally:
            harness.shutdown()

    if exit_code != 0:
        pytest.fail(
            f"Conformance suite FAILED (runner exit {exit_code}). "
            "See output above for per-scenario details."
        )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for _cmd in ("sh", "jq", "curl"):
        if not shutil.which(_cmd):
            print(f"ERROR: '{_cmd}' not found.", file=sys.stderr)
            sys.exit(1)

    _agent_ids = _collect_agent_ids()
    print(f"Agents found in scenarios: {_agent_ids}")

    _timeout = float(os.environ.get("SOX_CONFORMANCE_TIMEOUT", "20"))

    with tempfile.TemporaryDirectory(prefix="sox-conformance-") as _tmpdir:
        _db = os.path.join(_tmpdir, "conformance.db")
        _h = _ConformanceHarness(db_path=_db, timeout=_timeout)
        try:
            _h.start_agents(_agent_ids)
            _h.wait_ready()
            _rc = _h.run_suite()
        finally:
            _h.shutdown()

    sys.exit(_rc)
