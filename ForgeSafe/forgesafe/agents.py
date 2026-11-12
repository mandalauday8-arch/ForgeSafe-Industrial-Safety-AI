from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from forgesafe.rag import KnowledgeBase
from forgesafe.schemas import DetectionEvent, IncidentReport, SupervisorDecision, utc_now


SEVERITY_ORDER = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


class SafetyAgent:
    """Agent responsible for inspecting vision streams (CCTV, images, videos) for safety hazards."""

    def __init__(self):
        self.name = "Safety Agent"
        self.processed_count = 0

    def inspect(self, detections: List[Dict[str, Any]]) -> List[DetectionEvent]:
        """Analyze detection results from YOLO and generate hazard detection events."""
        events = []
        for det in detections:
            raw_class = det.get("class", "")
            confidence = det.get("confidence", 1.0)
            box = det.get("box", [])

            # Detect missing PPE violations
            if raw_class.startswith("NO-") or "NO-" in raw_class:
                self.processed_count += 1
                kind = "ppe_violation"
                normalized_item = raw_class.replace("NO-", "").strip()

                if normalized_item in {"Hardhat", "Helmet"}:
                    severity = "HIGH"
                    title = "PPE violation: Missing Hardhat"
                elif normalized_item in {"Safety Vest", "Vest"}:
                    severity = "HIGH"
                    title = "PPE violation: Missing Safety Vest"
                elif normalized_item in {"Mask"}:
                    severity = "MEDIUM"
                    title = "PPE violation: Missing Protective Mask"
                else:
                    severity = "HIGH"
                    title = f"PPE violation: Missing {normalized_item}"

                detail = (
                    f"Operator without required {normalized_item} detected "
                    f"with {round(confidence * 100)}% model confidence."
                )

                events.append(
                    DetectionEvent(
                        source="cctv",
                        kind=kind,
                        severity=severity,
                        title=title,
                        detail=detail,
                        metadata={
                            "class": raw_class,
                            "item": normalized_item,
                            "confidence": round(confidence, 3),
                            "box": box,
                        },
                    )
                )

            # Detect hazardous spills or restricted area proximity if flagged
            elif raw_class.lower() in {"spill", "chemical_spill", "leak"}:
                self.processed_count += 1
                events.append(
                    DetectionEvent(
                        source="cctv",
                        kind="hazard_condition",
                        severity="CRITICAL",
                        title="Hazard Condition: Fluid Spill on Active Floor",
                        detail=f"Floor spill detected with {round(confidence * 100)}% confidence. Slip and fire hazard.",
                        metadata={"class": raw_class, "confidence": round(confidence, 3), "box": box},
                    )
                )

        return events


# Alias CctvAgent to SafetyAgent for backward compatibility
CctvAgent = SafetyAgent


class MachineAgent:
    """Agent responsible for inspecting machine telemetry and CatBoost failure predictions."""

    def __init__(self):
        self.name = "Machine Agent"
        self.processed_count = 0

    def inspect(self, machine: Dict[str, Any]) -> List[DetectionEvent]:
        """Analyze machine telemetry row and generate anomaly detection events."""
        risk = machine.get("risk", "LOW").upper()
        anomaly_detected = bool(machine.get("anomalyDetected"))
        demo_status = str(machine.get("demoStatus", "")).upper()
        name = machine.get("name", "Industrial Machine")
        machine_id = machine.get("id", "MC_UNKNOWN")
        probability = machine.get("failureProbability", 0.0)
        anomaly_type = machine.get("anomalyType")

        # Ignore machines with low risk and no anomalies
        if risk == "LOW" and not anomaly_detected and demo_status not in {"FAULT", "DEGRADING"}:
            return []

        self.processed_count += 1

        if risk == "CRITICAL" or demo_status == "FAULT" or probability >= 80:
            severity = "CRITICAL"
        elif risk == "HIGH" or demo_status == "DEGRADING" or probability >= 60:
            severity = "HIGH"
        elif risk == "MEDIUM" or probability >= 30:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        if anomaly_detected and anomaly_type:
            title = f"{name}: {anomaly_type}"
            detail = (
                f"{demo_status} anomaly state detected on {name} ({machine_id}). "
                f"Model failure risk: {risk} ({probability}% probability within 7 days)."
            )
        else:
            title = f"{name} anomaly"
            detail = (
                f"{risk} risk telemetry anomaly detected on {name} ({machine_id}) "
                f"with {probability}% 7-day failure probability."
            )

        # Include active sensor readings
        sensors = machine.get("sensorReadings", [])
        if sensors:
            sensor_str = ", ".join(f"{s.get('label')}: {s.get('value')}" for s in sensors)
            detail += f" Critical telemetry readings: [{sensor_str}]."

        return [
            DetectionEvent(
                source="machine",
                kind="machine_anomaly",
                severity=severity,
                title=title,
                detail=detail,
                metadata={
                    "machine_id": machine_id,
                    "machine_name": name,
                    "risk": risk,
                    "failure_probability": probability,
                    "demo_status": demo_status,
                    "anomaly_type": anomaly_type,
                    "sensor_readings": sensors,
                },
            )
        ]


class RagAgent:
    """Agent responsible for querying and retrieving safety SOPs, standards, and emergency procedures."""

    def __init__(self, knowledge_base: KnowledgeBase):
        self.name = "RAG Agent"
        self.knowledge_base = knowledge_base
        self.query_count = 0

    def retrieve_procedure(self, event: DetectionEvent, limit: int = 3) -> List[Dict[str, Any]]:
        """Retrieve relevant standard operating procedures matching the event."""
        self.query_count += 1
        query = f"{event.kind} {event.title} {event.detail}"
        return self.knowledge_base.search(query, limit=limit)


class SupervisorAgent:
    """Coordinator Agent evaluating events, severity, RAG procedures, and formulating decisions."""

    def __init__(self, knowledge_base: KnowledgeBase):
        self.name = "Supervisor Agent"
        self.knowledge_base = knowledge_base
        self.rag_agent = RagAgent(knowledge_base)
        self.decisions_count = 0

    def decide(self, event: DetectionEvent) -> SupervisorDecision:
        """Evaluate event, retrieve applicable SOPs via RAG, and determine action and ownership."""
        self.decisions_count += 1
        guidance = self.rag_agent.retrieve_procedure(event)

        # Determine severity-governed action, ownership, and recommended simulated action
        if event.severity == "CRITICAL":
            action = "Stop work and escalate immediately"
            owner = "Site supervisor"
            simulated_action = {
                "type": "simulated_shutdown" if event.source == "machine" else "evacuate_zone",
                "label": "Simulate Emergency Shutdown (E-Stop)" if event.source == "machine" else "Simulate Zone Evacuation",
                "target_id": event.metadata.get("machine_id", "WORK_ZONE"),
                "status": "AVAILABLE",
            }
        elif event.severity == "HIGH":
            action = "Notify supervisor and create corrective action"
            owner = "Safety lead" if event.source in {"cctv", "inspection"} else "Maintenance lead"
            simulated_action = {
                "type": "lockout_tagout" if event.source == "machine" else "safety_hold",
                "label": "Simulate Lockout/Tagout (LOTO)" if event.source == "machine" else "Simulate Safety Hold",
                "target_id": event.metadata.get("machine_id", "WORK_ZONE"),
                "status": "AVAILABLE",
            }
        elif event.severity == "MEDIUM":
            action = "Schedule inspection before next shift"
            owner = "Maintenance lead"
            simulated_action = {
                "type": "dispatch_maintenance",
                "label": "Dispatch Maintenance Order",
                "target_id": event.metadata.get("machine_id", "WORK_ZONE"),
                "status": "AVAILABLE",
            }
        else:
            action = "Log and continue monitoring"
            owner = "Control room"
            simulated_action = None

        rationale = (
            f"{event.source.capitalize()} reported a {event.severity.lower()}-severity "
            f"{event.kind.replace('_', ' ')}. {event.detail}"
        )

        return SupervisorDecision(
            event=event,
            action=action,
            owner=owner,
            rationale=rationale,
            guidance=guidance,
            simulated_action=simulated_action,
        )


class ActionAgent:
    """Agent that creates alerts, logs incidents, tracks audits, and executes simulated actions."""

    def __init__(self):
        self.name = "Action Agent"
        self.actions_count = 0

    def report(self, decision: SupervisorDecision) -> Dict[str, Any]:
        """Convert a supervisor decision into an official incident report."""
        self.actions_count += 1
        event = decision.event
        status = "OPEN" if event.severity != "LOW" else "LOGGED"

        return {
            "report_id": f"inc_{event.event_id}",
            "status": status,
            "action": decision.action,
            "owner": decision.owner,
            "severity": event.severity,
            "source": event.source,
            "title": event.title,
            "detail": event.detail,
            "event": event.to_dict() if isinstance(event, DetectionEvent) else event,
            "rationale": decision.rationale,
            "guidance": decision.guidance,
            "simulated_action": decision.simulated_action,
            "created_at": event.created_at,
            "updated_at": utc_now(),
        }
