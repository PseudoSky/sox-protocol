# SPDX-License-Identifier: Apache-2.0
"""In-process liveness / presence backing store for the HTTP transport.

Tracks agent heartbeats and derives presence states per
``spec/primitives/presence.md §3``.

This is a lightweight in-memory store that is NOT persisted.  It is updated
by the ``channels_heartbeat`` route handler and queried by ``list_agents``.

Spec reference: ``spec/primitives/presence.md``
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

# Thresholds from spec/primitives/presence.md §3
_STALE_THRESHOLD_S: float = 30.0
_OFFLINE_THRESHOLD_S: float = 90.0


@dataclass
class AgentRecord:
    """Liveness record for a single agent.

    Attributes:
        agent_id: Authenticated agent identity.
        last_heartbeat_at_ns: Unix nanoseconds of last heartbeat; 0 if never.
        reported_status: The status last reported by the agent via heartbeat.
        namespace: Namespace the agent authenticated into, or None.
    """

    agent_id: str
    last_heartbeat_at_ns: int = 0
    reported_status: str = "online"
    namespace: str | None = None


class LivenessStore:
    """Thread-safe in-memory store for agent liveness records.

    Usage::

        store = LivenessStore()
        store.record_heartbeat("agent-a", "online")
        agents = store.list_agents()
    """

    def __init__(self) -> None:
        self._records: dict[str, AgentRecord] = {}
        self._lock: Lock = Lock()

    def record_heartbeat(
        self,
        agent_id: str,
        status: str,
        namespace: str | None = None,
    ) -> None:
        """Update the liveness record for *agent_id*.

        Args:
            agent_id: Authenticated agent identity.
            status: Agent-reported status (``online``, ``busy``, ``offline``).
            namespace: Optional namespace for the agent.
        """
        now_ns = time.time_ns()
        with self._lock:
            rec = self._records.get(agent_id)
            if rec is None:
                rec = AgentRecord(agent_id=agent_id, namespace=namespace)
                self._records[agent_id] = rec
            rec.last_heartbeat_at_ns = now_ns
            rec.reported_status = status
            if namespace is not None:
                rec.namespace = namespace

    def ensure_agent(self, agent_id: str, namespace: str | None = None) -> None:
        """Register *agent_id* if not already known (without updating heartbeat time).

        Args:
            agent_id: Authenticated agent identity.
            namespace: Optional namespace.
        """
        with self._lock:
            if agent_id not in self._records:
                self._records[agent_id] = AgentRecord(
                    agent_id=agent_id, namespace=namespace
                )

    def _derive_state(self, rec: AgentRecord) -> str:
        """Compute the server-derived presence state for *rec*.

        Args:
            rec: The agent's liveness record.

        Returns:
            One of ``"online"``, ``"busy"``, ``"stale"``, ``"offline"``.
        """
        if rec.last_heartbeat_at_ns == 0:
            return "offline"
        if rec.reported_status == "offline":
            return "offline"
        age_s = (time.time_ns() - rec.last_heartbeat_at_ns) / 1_000_000_000
        if age_s >= _OFFLINE_THRESHOLD_S:
            return "offline"
        if age_s >= _STALE_THRESHOLD_S:
            return "stale"
        if rec.reported_status == "busy":
            return "busy"
        return "online"

    def list_agents(
        self,
        status_filter: list[str] | None = None,
        namespace: str | None = None,
    ) -> list[dict[str, object]]:
        """Return agent liveness records matching the given filters.

        Args:
            status_filter: If set, only return agents in these presence states.
            namespace: If set, only return agents in this namespace.

        Returns:
            List of dicts conforming to ``list_agents.output.schema.json``.
        """
        with self._lock:
            records = list(self._records.values())

        result: list[dict[str, object]] = []
        for rec in records:
            state = self._derive_state(rec)
            if status_filter is not None and state not in status_filter:
                continue
            if namespace is not None and rec.namespace != namespace:
                continue
            result.append(
                {
                    "agent_id": rec.agent_id,
                    "presence_state": state,
                    "last_heartbeat_at": rec.last_heartbeat_at_ns,
                    "namespace": rec.namespace,
                }
            )
        return result
