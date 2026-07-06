class NodeExecutor:
    def execute(self, node_id: str) -> dict:
        return {"node_id": node_id, "status": "delegated_to_production_provider"}
