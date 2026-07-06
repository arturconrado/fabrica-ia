def validate_workflow(workflow: dict) -> bool:
    graph = workflow.get("graph", {})
    return bool(graph.get("id") and graph.get("nodes", []) is not None)
