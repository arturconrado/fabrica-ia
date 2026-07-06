from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.agents.production_pipeline_provider import ProductionPipelineProvider
from app.agents.production_contracts import DEMO_DEMAND
from app.events.event_service import emit_event
from app.providers.model_gateway import ModelGateway


class LiteLLMIndustrialAgentProvider(ProductionPipelineProvider):
    def __init__(self) -> None:
        self.gateway = ModelGateway()

    def generate_structured(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        agent_name: str,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.gateway.call(
            db=db,
            tenant_id=tenant_id,
            run_id=run_id,
            agent_name=agent_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are an industrial software factory agent. Return compact JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            response_schema=schema,
        )

    def start_enterprise_run(
        self,
        db: Session,
        demand: str = DEMO_DEMAND,
        project_id: Optional[str] = None,
        project_name: str = "ContractFlow Enterprise",
        tenant_id: str = "local-dev",
        run_id: Optional[str] = None,
    ):
        run = super().start_enterprise_run(
            db,
            demand=demand,
            project_id=project_id,
            project_name=project_name,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        run.provider = "production-litellm"
        db.commit()
        db.refresh(run)
        return run

    def _start_node(self, db: Session, run, node_id: str, phase: str, iteration: int = 1, max_iterations: int = 1):
        state = super()._start_node(db, run, node_id, phase, iteration=iteration, max_iterations=max_iterations)
        model_result = self.generate_structured(
            db,
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name=node_id,
            prompt=(
                f"Run demand:\n{run.demand}\n\n"
                f"Agent: {node_id}\nPhase: {phase}\nIteration: {iteration}/{max_iterations}\n"
                "Return a compact JSON object with keys decision, reasoning_summary, output_refs, risks, next_action. "
                "Do not include hidden chain-of-thought."
            ),
            schema={
                "type": "object",
                "required": ["decision", "reasoning_summary", "output_refs", "risks", "next_action"],
            },
        )
        emit_event(
            db,
            run.id,
            "model.call_completed",
            f"{node_id} called the production LiteLLM gateway.",
            node_id=node_id,
            phase=phase,
            agent_name=node_id,
            tenant_id=run.tenant_id,
            model_call_id=str(model_result["id"]),
            payload={"model": model_result["model"], "provider": "litellm"},
        )
        return state
