"""Pure workflow graph validation and transition rules shared by inline and Temporal runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.workflow.condition_evaluator import condition_matches


class WorkflowTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class TransitionState:
    current_node: str
    total_steps: int = 0
    node_iterations: Mapping[str, int] = field(default_factory=dict)
    edge_iterations: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionResult:
    source_node: str
    target_node: str
    decision: str
    target_iteration: int
    state: TransitionState


class WorkflowTransitionEngine:
    """Deterministic graph interpreter with no database, clock or provider dependencies."""

    def __init__(self, graph: Mapping[str, Any]) -> None:
        self.graph = dict(graph)
        node_rows = list(self.graph.get("nodes") or [])
        edge_rows = list(self.graph.get("edges") or [])
        self.nodes = {str(row.get("id") or ""): dict(row) for row in node_rows}
        self.edges = tuple(dict(row) for row in edge_rows)
        self.max_total_steps = int((self.graph.get("execution") or {}).get("max_total_steps") or 32)
        self._validate()

    def _validate(self) -> None:
        if not self.nodes or "USER" not in self.nodes or "FINAL" not in self.nodes:
            raise WorkflowTransitionError("workflow must define USER and FINAL nodes")
        if "" in self.nodes or len(self.nodes) != len(list(self.graph.get("nodes") or [])):
            raise WorkflowTransitionError("workflow node identifiers must be non-empty and unique")
        for edge in self.edges:
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            if source not in self.nodes or target not in self.nodes:
                raise WorkflowTransitionError(f"workflow edge references an unknown node: {source}->{target}")
            if "condition" not in edge:
                raise WorkflowTransitionError(f"workflow edge has no condition: {source}->{target}")
            limit = int(edge.get("max_iterations") or 0)
            if limit < 0:
                raise WorkflowTransitionError(f"workflow edge has a negative loop limit: {source}->{target}")
        reachable = {"USER"}
        changed = True
        while changed:
            changed = False
            for edge in self.edges:
                if str(edge["from"]) in reachable and str(edge["to"]) not in reachable:
                    reachable.add(str(edge["to"]))
                    changed = True
        unreachable = set(self.nodes).difference(reachable)
        if unreachable:
            raise WorkflowTransitionError(f"workflow contains unreachable nodes: {sorted(unreachable)}")

    def first_executable_node(self) -> str:
        return self.transition(TransitionState(current_node="USER"), "success").target_node

    def transition(self, state: TransitionState, decision: str) -> TransitionResult:
        if state.current_node not in self.nodes:
            raise WorkflowTransitionError(f"unknown current node: {state.current_node}")
        matching = [
            edge
            for edge in self.edges
            if str(edge.get("from")) == state.current_node and condition_matches(edge.get("condition"), decision)
        ]
        if not matching:
            raise WorkflowTransitionError(f"no edge matches {state.current_node} decision {decision}")
        if len(matching) > 1:
            raise WorkflowTransitionError(f"ambiguous edges match {state.current_node} decision {decision}")

        next_steps = state.total_steps + (0 if state.current_node == "USER" else 1)
        if next_steps > self.max_total_steps:
            raise WorkflowTransitionError("workflow exceeded its persisted maximum step count")

        edge = matching[0]
        target = str(edge["to"])
        edge_key = f"{state.current_node}->{target}"
        node_iterations = dict(state.node_iterations)
        edge_iterations = dict(state.edge_iterations)
        target_iteration = int(node_iterations.get(target, 0)) + 1
        node_iterations[target] = target_iteration

        loop_limit = int(edge.get("max_iterations") or 0)
        if loop_limit:
            edge_iterations[edge_key] = int(edge_iterations.get(edge_key, 0)) + 1
            if edge_iterations[edge_key] > loop_limit:
                raise WorkflowTransitionError(f"workflow loop limit exceeded for {edge_key}")

        next_state = TransitionState(
            current_node=target,
            total_steps=next_steps,
            node_iterations=node_iterations,
            edge_iterations=edge_iterations,
        )
        return TransitionResult(
            source_node=state.current_node,
            target_node=target,
            decision=decision,
            target_iteration=target_iteration,
            state=next_state,
        )
