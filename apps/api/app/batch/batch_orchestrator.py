from app.services.run_service import provider


class BatchOrchestrator:
    def __init__(self):
        self.provider = provider

    def run_enterprise(self, db):
        raise RuntimeError("In-process batch orchestration is disabled; use the Temporal-backed /batches API")
