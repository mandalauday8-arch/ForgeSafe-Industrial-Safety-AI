from collections import deque
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from forgesafe.agents import (
    ActionAgent,
    CctvAgent,
    MachineAgent,
    RagAgent,
    SafetyAgent,
    SupervisorAgent,
)
from forgesafe.rag import KnowledgeBase
from forgesafe.schemas import DetectionEvent, SupervisorDecision, utc_now


class ForgeSafeWorkflow:
    """Central orchestrator coordinating the multi-agent industrial safety pipeline."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.knowledge = KnowledgeBase(self.root / "knowledge")
        self.cctv = SafetyAgent()
        self.safety = self.cctv
        self.machine = MachineAgent()
        self.rag = RagAgent(self.knowledge)
        self.supervisor = SupervisorAgent(self.knowledge)
        self.action = ActionAgent()

        self.history: deque = deque(maxlen=100)
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.simulated_machine_states: Dict[str, Dict[str, Any]] = {}
        self.machine_incident_keys: Dict[str, str] = {}
        self.machine_incident_times: Dict[str, float] = {}
        self.frozen_machines = set()

    def process_events(self, events: List[DetectionEvent]) -> List[Dict[str, Any]]:
        """Run the Supervisor -> RAG -> Action pipeline on a batch of detection events."""
        decisions = []
        for event in events:
            decision = self.supervisor.decide(event)
            report = self.action.report(decision)
            self.incidents[report["report_id"]] = report
            decisions.append({
                "decision": decision.to_dict(),
                "report": report,
            })

        self.history.extendleft(decisions)
        return decisions

    def process_cctv(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process visual detections from CCTV, live cameras, or uploaded inspection files."""
        events = self.cctv.inspect(detections)
        return self.process_events(events)

    def process_machine(self, machine: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process telemetry data and ML failure risk from an industrial machine."""
        machine_id = str(machine.get("id", "MC_UNKNOWN"))
        if machine_id in self.frozen_machines:
            return []

        last_incident_at = self.machine_incident_times.get(machine_id)
        if last_incident_at is not None and time.monotonic() - last_incident_at < 60:
            return []

        events = self.machine.inspect(machine)
        if not events:
            return []

        self.machine_incident_keys[machine_id] = machine_id
        self.machine_incident_times[machine_id] = time.monotonic()
        return self.process_events(events)

    def clear_machine_incident(self, machine_id: str) -> None:
        """Allow a machine to raise a new incident after returning to nominal."""
        machine_id = str(machine_id)
        self.machine_incident_keys.pop(machine_id, None)
        self.machine_incident_times.pop(machine_id, None)

    def freeze_machine(self, machine_id: str) -> None:
        """Stop telemetry processing and incident creation for one machine."""
        self.frozen_machines.add(str(machine_id))

    def unfreeze_machine(self, machine_id: str) -> None:
        """Resume telemetry processing for one machine."""
        self.frozen_machines.discard(str(machine_id))

    def snapshot(self) -> List[Dict[str, Any]]:
        """Return the recent decision and event history."""
        return list(self.history)

    def get_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the tracked incident reports sorted newest first."""
        sorted_incidents = sorted(
            self.incidents.values(),
            key=lambda inc: inc.get("created_at", ""),
            reverse=True,
        )
        return sorted_incidents[:limit]

    def clear_incidents(self) -> None:
        """Clear the incident audit log without resetting agent metrics or machine controls."""
        self.incidents.clear()
        self.history.clear()
        self.machine_incident_keys.clear()
        self.machine_incident_times.clear()

    def reset_all(self) -> None:
        """Return the in-memory workflow to its initial runtime state."""
        self.clear_incidents()
        self.simulated_machine_states.clear()
        self.frozen_machines.clear()
        self.cctv.processed_count = 0
        self.machine.processed_count = 0
        self.rag.query_count = 0
        self.supervisor.decisions_count = 0
        self.supervisor.rag_agent.query_count = 0
        self.action.actions_count = 0

    def execute_simulated_action(
        self,
        report_id: str,
        action_type: str,
        target_id: Optional[str] = None,
        operator: str = "Alex Rivera",
    ) -> Dict[str, Any]:
        """Execute or acknowledge a simulated machine control action from the dashboard."""
        incident = self.incidents.get(report_id)
        target = target_id or (incident["simulated_action"]["target_id"] if incident and incident.get("simulated_action") else None)

        if incident:
            incident["status"] = "ACTION_EXECUTED"
            incident["updated_at"] = utc_now()
            incident["resolution"] = {
                "executed_action": action_type,
                "operator": operator,
                "timestamp": utc_now(),
            }

        # Apply simulated machine control state
        if target and str(target).startswith("MC_"):
            if action_type in {"simulated_shutdown", "simulated_estop"}:
                state = "SIMULATED SHUTDOWN"
            elif action_type in {"lockout_tagout", "loto"}:
                state = "LOCKED OUT"
            elif action_type in {"dispatch_maintenance", "maintenance_order"}:
                state = "MAINTENANCE PENDING"
            else:
                state = "ACTION EXECUTED"

            self.simulated_machine_states[target] = {
                "state": state,
                "action": action_type,
                "report_id": report_id,
                "operator": operator,
                "timestamp": utc_now(),
            }

        return {
            "success": True,
            "report_id": report_id,
            "action_type": action_type,
            "target": target,
            "simulated_states": self.simulated_machine_states,
        }

    def reset_machine(self, machine_id: str) -> Dict[str, Any]:
        """Reset a machine from a simulated control state back to live operational telemetry."""
        removed = self.simulated_machine_states.pop(machine_id, None)
        self.clear_machine_incident(machine_id)
        self.unfreeze_machine(machine_id)
        return {
            "success": True,
            "machine_id": machine_id,
            "was_overridden": removed is not None,
            "simulated_states": self.simulated_machine_states,
        }

    def get_machine_override(self, machine_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve active simulated control state for a specific machine."""
        return self.simulated_machine_states.get(machine_id)

    def status(self) -> Dict[str, Any]:
        """Return system-wide multi-agent status, document stats, and performance metrics."""
        return {
            "agents": ["cctv", "machine", "supervisor", "rag", "action"],
            "knowledge_documents": len(self.supervisor.knowledge_base.chunks),
            "open_decisions": len(self.history),
            "active_incidents": len([i for i in self.incidents.values() if i.get("status") == "OPEN"]),
            "simulated_overrides": len(self.simulated_machine_states),
            "agent_stats": {
                "safety_agent": {"processed": self.cctv.processed_count},
                "machine_agent": {"processed": self.machine.processed_count},
                "supervisor_agent": {"decisions": self.supervisor.decisions_count},
                "rag_agent": {"queries": self.rag.query_count},
                "action_agent": {"actions": self.action.actions_count},
            },
        }
