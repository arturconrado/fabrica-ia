from app.services.run_service import provider


class LocalIndustrialWorkflowRunner:
    def __init__(self):
        self.provider = provider

    def run_enterprise(self, db, demand):
        raise RuntimeError("Local in-process workflow runner is disabled in the production-only runtime")
