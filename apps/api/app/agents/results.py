from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class AgentResult:
    status: str
    summary: str
    payload: Dict[str, Any] = field(default_factory=dict)
