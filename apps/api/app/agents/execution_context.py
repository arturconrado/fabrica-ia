from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentExecutionContext:
    run_id: str
    workspace: Path
    demand: str
