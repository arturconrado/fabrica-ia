from app.optimizer.aflow_adapter import AFlowOptimizerAdapter


def propose(workflow_id: str, score: float) -> dict:
    return AFlowOptimizerAdapter().propose_candidate(workflow_id, [], score)
