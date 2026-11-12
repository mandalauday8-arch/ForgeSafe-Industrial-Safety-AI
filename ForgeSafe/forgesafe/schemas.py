from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    """Return an ISO 8601 formatted UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


SEVERITY_ORDER = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


@dataclass
class DetectionEvent:
    """Represents a safety hazard or machine anomaly detected by perceptual agents."""
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    source: str = "cctv"  # 'cctv', 'machine', 'inspection'
    kind: str = "ppe_violation"  # 'ppe_violation', 'machine_anomaly', 'hazard_condition', 'zone_intrusion'
    severity: str = "HIGH"  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    title: str = ""
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeChunk:
    """Represents a chunked section of a safety manual or SOP."""
    source: str
    title: str
    text: str
    tags: tuple
    standard: str = ""
    sop_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "tags": list(self.tags),
            "standard": self.standard,
            "sop_id": self.sop_id,
        }


@dataclass
class SupervisorDecision:
    """Consolidated decision formulated by the Supervisor Agent using RAG."""
    event: DetectionEvent
    action: str
    owner: str
    rationale: str
    guidance: List[Dict[str, Any]] = field(default_factory=list)
    simulated_action: Optional[Dict[str, Any]] = None
    decision_id: str = field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["event"] = self.event.to_dict() if isinstance(self.event, DetectionEvent) else self.event
        return result


@dataclass
class IncidentReport:
    """Incident report generated and tracked by the Action/Reporting Agent."""
    report_id: str
    status: str  # 'OPEN', 'ACKNOWLEDGED', 'ACTION_EXECUTED', 'RESOLVED', 'LOGGED'
    action: str
    owner: str
    severity: str
    source: str
    title: str
    detail: str
    event: Dict[str, Any]
    rationale: str
    guidance: List[Dict[str, Any]]
    simulated_action: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
