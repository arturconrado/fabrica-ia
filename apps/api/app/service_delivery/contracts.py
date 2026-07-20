from dataclasses import dataclass, field
from typing import Any, Dict, Protocol


@dataclass(frozen=True)
class ExecutionContext:
    tenant_id: str
    actor_user_id: str
    correlation_id: str


@dataclass(frozen=True)
class LLMRequest:
    prompt: str


@dataclass(frozen=True)
class LLMResponse:
    content: Dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float


class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest, context: ExecutionContext) -> LLMResponse:
        ...


@dataclass(frozen=True)
class WorkflowStatus:
    workflow_id: str
    status: str
    payload: Dict[str, Any] = field(default_factory=dict)


class WorkflowRunner(Protocol):
    async def start(self, workflow_id: str, payload: Dict[str, Any], context: ExecutionContext) -> WorkflowStatus:
        ...

    async def signal(self, workflow_id: str, signal: str, payload: Dict[str, Any], context: ExecutionContext) -> WorkflowStatus:
        ...

    async def cancel(self, workflow_id: str, context: ExecutionContext) -> WorkflowStatus:
        ...

    async def get_status(self, workflow_id: str, context: ExecutionContext) -> WorkflowStatus:
        ...


class ConnectorBroker(Protocol):
    async def authorize(self, connector_id: str, capability: str, context: ExecutionContext) -> bool:
        ...

    async def execute(self, connector_id: str, operation: str, payload: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        ...

    async def health_check(self, connector_id: str, context: ExecutionContext) -> Dict[str, Any]:
        ...


@dataclass(frozen=True)
class CalculationResult:
    formula_code: str
    formula_version: str
    value: float
    explanation: Dict[str, Any]


class CalculationEngine(Protocol):
    def calculate(self, formula_code: str, formula_version: str, inputs: Dict[str, Any]) -> CalculationResult:
        ...
