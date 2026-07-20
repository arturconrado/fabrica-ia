import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


MAX_ARTIFACT_CHARS = 40_000
MAX_FILE_CHARS = 200_000
MAX_FILES_PER_STEP = 32
MAX_OUTPUT_UNITS = 32
MAX_ARTIFACT_SECTIONS = 12
MAX_FILES_PER_BATCH = 4
MAX_UNIT_ATTEMPTS = 3
MAX_UNIT_CONTINUATIONS = 2
SAFE_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SAFE_UNIT_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,95}$")


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_workspace_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be a safe relative workspace path")
    if not path.parts or path.parts[0] != "generated_app":
        raise ValueError("generated files must stay under generated_app/")
    return str(path)


class ContextReference(BaseModel):
    kind: Literal[
        "demand",
        "contract",
        "scope",
        "artifact",
        "file",
        "file_tree",
        "diff",
        "test",
        "rag",
        "decision",
        "lesson",
    ]
    ref_id: str
    label: str
    checksum: str
    content: str = Field(max_length=80_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactViewPolicy(BaseModel):
    mode: Literal["full", "sections", "digest"] = "full"
    headings: list[str] = Field(default_factory=list, max_length=30)
    max_tokens: int = Field(default=0, ge=0, le=64_000)


class ContextPolicy(BaseModel):
    """Versioned, explicit context contract carried by each workflow node."""

    version: str = "2.13.0"
    allowed_reference_types: list[str] = Field(default_factory=lambda: ["demand"])
    required_artifacts: list[str] = Field(default_factory=list)
    optional_artifacts: list[str] = Field(default_factory=list)
    input_budget_tokens: int = Field(default=16_000, ge=1_000, le=128_000)
    max_rag_chunks: int = Field(default=0, ge=0, le=20)
    max_lessons: int = Field(default=0, ge=0, le=10)
    lesson_budget_tokens: int = Field(default=0, ge=0, le=8_000)
    file_mode: Literal["none", "tree", "diff", "selected", "content"] = "none"
    file_globs: list[str] = Field(default_factory=list)
    use_digests: bool = True
    max_selected_references: int = Field(default=24, ge=1, le=80)
    per_kind_token_budgets: dict[str, int] = Field(default_factory=dict)
    reference_order: list[str] = Field(
        default_factory=lambda: ["demand", "contract", "scope", "artifact", "decision", "rag", "lesson", "file_tree", "diff", "file", "test"]
    )
    artifact_views: dict[str, ArtifactViewPolicy] = Field(default_factory=dict)
    min_rag_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    tokenizer_model: str = Field(default="", max_length=200)

    @field_validator("per_kind_token_budgets")
    @classmethod
    def validate_kind_budgets(cls, value: dict[str, int]) -> dict[str, int]:
        for kind, budget in value.items():
            if kind not in ContextReference.model_fields["kind"].annotation.__args__:
                raise ValueError(f"unsupported context reference kind: {kind}")
            if int(budget) < 0 or int(budget) > 128_000:
                raise ValueError(f"invalid token budget for reference kind: {kind}")
        return {str(kind): int(budget) for kind, budget in value.items()}


def estimate_tokens(value: str, model_name: str = "") -> int:
    """Conservative tokenizer-independent estimate used only for budgeting."""

    text = str(value or "")
    if not text:
        return 0
    if model_name:
        try:
            from litellm import token_counter

            counted = int(token_counter(model=model_name, text=text) or 0)
            if counted > 0:
                return counted
        except Exception:
            pass
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


class ContextBundle(BaseModel):
    tenant_id: str
    run_id: str
    node_id: str
    demand: str
    references: list[ContextReference] = Field(default_factory=list, max_length=80)
    constraints: list[str] = Field(default_factory=list)
    policy_version: str = "2.13.0"
    input_budget_tokens: int = 16_000
    estimated_input_tokens: int = 0
    discarded_tokens: int = 0
    discarded_references: list[dict[str, Any]] = Field(default_factory=list)
    selection_reasons: dict[str, str] = Field(default_factory=dict)
    final_instruction: str = "Use only selected evidence and satisfy the node contract without inventing facts."
    input_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> "ContextBundle":
        payload = {
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "demand": self.demand,
            "references": [reference.model_dump() for reference in self.references],
            "constraints": self.constraints,
            "policy_version": self.policy_version,
            "final_instruction": self.final_instruction,
        }
        self.estimated_input_tokens = estimate_tokens(
            self.demand
            + "\n".join(reference.content for reference in self.references)
            + "\n".join(self.constraints)
            + self.final_instruction
        )
        self.input_hash = stable_hash(payload)
        return self


class ArtifactOutput(BaseModel):
    model_config = {"extra": "forbid"}
    name: str
    artifact_type: Literal["markdown", "json", "text"] = "markdown"
    content: str = Field(min_length=1, max_length=MAX_ARTIFACT_CHARS)
    audience: Literal["internal", "reviewer", "client"] = "internal"
    evidence_classification: Literal["real", "calculated", "estimated", "recommendation", "declared"] = "recommendation"
    source_refs: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not SAFE_ARTIFACT_NAME.fullmatch(name):
            raise ValueError("artifact name contains unsupported characters")
        return name


class FileOperation(BaseModel):
    model_config = {"extra": "forbid"}
    operation: Literal["create", "update", "patch"]
    path: str
    content: str = Field(default="", max_length=MAX_FILE_CHARS)
    patch: str = Field(default="", max_length=MAX_FILE_CHARS)
    base_sha256: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    rationale: str = Field(default="", max_length=2000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _safe_workspace_path(value)

    @model_validator(mode="after")
    def validate_payload(self) -> "FileOperation":
        if self.operation in {"create", "update"} and not self.content:
            raise ValueError(f"{self.operation} requires complete file content")
        if self.operation == "patch" and not self.patch:
            raise ValueError("patch requires a unified diff payload")
        if self.operation in {"update", "patch"} and not self.base_sha256:
            raise ValueError(f"{self.operation} requires base_sha256")
        if self.operation == "patch" and self.content:
            raise ValueError("patch must not duplicate complete file content")
        return self


class OutputUnitDescriptor(BaseModel):
    """A small ordered output unit; it contains no generated long-form content."""

    model_config = {"extra": "forbid"}
    key: str
    unit_type: Literal["atomic", "artifact_section", "file_batch", "finalize"]
    targets: list[str] = Field(default_factory=list, max_length=4)
    order: int = Field(ge=0, le=31)
    dependencies: list[str] = Field(default_factory=list, max_length=16)
    input_budget_tokens: int = Field(default=0, ge=0, le=128_000)
    output_budget_tokens: int = Field(ge=128, le=32_000)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SAFE_UNIT_KEY.fullmatch(normalized):
            raise ValueError("unit key must be a stable lowercase identifier")
        return normalized

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in value]
        if any(not SAFE_UNIT_KEY.fullmatch(item) for item in normalized):
            raise ValueError("dependencies must reference stable unit keys")
        if len(set(normalized)) != len(normalized):
            raise ValueError("unit dependencies must be unique")
        return normalized

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for target in value:
            item = target.strip().replace("\\", "/")
            if not item or item.startswith("/") or ".." in PurePosixPath(item).parts:
                raise ValueError("unit targets must be safe relative paths or artifact names")
            normalized.append(item)
        if len(set(normalized)) != len(normalized):
            raise ValueError("unit targets must be unique")
        return normalized


class NodePlanResult(BaseModel):
    """Short manifest produced before a segmented node starts generating content."""

    model_config = {"extra": "forbid"}
    decision: Literal["success", "blocked"] = "success"
    summary: str = Field(min_length=1, max_length=4000)
    units: list[OutputUnitDescriptor] = Field(min_length=1, max_length=MAX_OUTPUT_UNITS)
    citations: list[str] = Field(default_factory=list, max_length=80)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_graph(self) -> "NodePlanResult":
        keys = [unit.key for unit in self.units]
        if len(set(keys)) != len(keys):
            raise ValueError("output unit keys must be unique")
        orders = [unit.order for unit in self.units]
        if len(set(orders)) != len(orders):
            raise ValueError("output unit order must be unique")
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("output unit order must be contiguous and start at zero")
        positions = {unit.key: unit.order for unit in self.units}
        for unit in self.units:
            if unit.key in unit.dependencies:
                raise ValueError(f"unit {unit.key} cannot depend on itself")
            unknown = set(unit.dependencies).difference(positions)
            if unknown:
                raise ValueError(f"unit {unit.key} has unknown dependencies: {sorted(unknown)}")
            if any(positions[dependency] >= positions[unit.key] for dependency in unit.dependencies):
                raise ValueError(f"unit {unit.key} dependencies must precede it")
        artifact_counts: dict[str, int] = {}
        for unit in self.units:
            if unit.unit_type != "artifact_section":
                continue
            for target in unit.targets:
                artifact_counts[target] = artifact_counts.get(target, 0) + 1
        if any(count > MAX_ARTIFACT_SECTIONS for count in artifact_counts.values()):
            raise ValueError(f"an artifact may contain at most {MAX_ARTIFACT_SECTIONS} sections")
        finalizers = [unit for unit in self.units if unit.unit_type == "finalize"]
        if len(finalizers) != 1 or finalizers[0].order != max(orders):
            raise ValueError("a segmented node plan requires exactly one final unit")
        return self

    def output_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class ArtifactSectionResult(BaseModel):
    model_config = {"extra": "forbid"}
    artifact_name: str
    artifact_type: Literal["markdown", "json", "text"] = "markdown"
    audience: Literal["internal", "reviewer", "client"] = "internal"
    section_key: str
    section_title: str = Field(default="", max_length=500)
    order: int = Field(ge=0, le=11)
    markdown: str = Field(min_length=1, max_length=MAX_ARTIFACT_CHARS)
    citations: list[str] = Field(default_factory=list, max_length=80)
    final: bool = False

    @field_validator("artifact_name")
    @classmethod
    def validate_artifact_name(cls, value: str) -> str:
        name = value.strip()
        if not SAFE_ARTIFACT_NAME.fullmatch(name):
            raise ValueError("artifact name contains unsupported characters")
        return name

    @field_validator("section_key")
    @classmethod
    def validate_section_key(cls, value: str) -> str:
        key = value.strip().lower()
        if not SAFE_UNIT_KEY.fullmatch(key):
            raise ValueError("section key must be a stable lowercase identifier")
        return key


class FileBatchResult(BaseModel):
    model_config = {"extra": "forbid"}
    batch_key: str
    operations: list[FileOperation] = Field(min_length=1, max_length=MAX_FILES_PER_BATCH)
    citations: list[str] = Field(default_factory=list, max_length=80)
    final: bool = False

    @field_validator("batch_key")
    @classmethod
    def validate_batch_key(cls, value: str) -> str:
        key = value.strip().lower()
        if not SAFE_UNIT_KEY.fullmatch(key):
            raise ValueError("batch key must be a stable lowercase identifier")
        return key

    @model_validator(mode="after")
    def validate_unique_paths(self) -> "FileBatchResult":
        paths = [operation.path for operation in self.operations]
        if len(paths) != len(set(paths)):
            raise ValueError("a file batch may mutate each path only once")
        return self


class NodeFinalizeResult(BaseModel):
    model_config = {"extra": "forbid"}
    decision: Literal[
        "success", "approved", "needs_changes", "tests_failed", "tests_passed",
        "passed", "blocked", "approved_for_homologation",
    ]
    summary: str = Field(min_length=1, max_length=8000)
    risks: list[str] = Field(default_factory=list, max_length=40)
    handoff: Optional["HandoffOutput"] = None
    produced_refs: list[str] = Field(default_factory=list, max_length=160)
    confidence: float = Field(ge=0, le=1)


SEGMENTED_ARTIFACT_NODES = frozenset(
    {
        "Acceptance Criteria Architect",
        "Product Manager",
        "UX UI Designer",
        "Architect",
        "Data Architect",
        "API Contract Engineer",
    }
)
SEGMENTED_WORKSPACE_NODES = frozenset({"Engineer"})


def output_strategy_for_node(node_id: str) -> Literal["atomic", "segmented_artifact", "segmented_workspace"]:
    if node_id in SEGMENTED_ARTIFACT_NODES:
        return "segmented_artifact"
    if node_id in SEGMENTED_WORKSPACE_NODES:
        return "segmented_workspace"
    return "atomic"


class RequirementOutput(BaseModel):
    model_config = {"extra": "forbid"}
    requirement_id: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,31}$")
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4000)
    priority: Literal["P0", "P1", "P2"]
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)


class TestRequest(BaseModel):
    model_config = {"extra": "forbid"}
    profile: Literal[
        "backend_tests",
        "frontend_tests",
        "frontend_build",
        "visual_tests",
        "accessibility_tests",
        "security_scan",
    ]
    reason: str = Field(min_length=1, max_length=2000)


class HandoffOutput(BaseModel):
    model_config = {"extra": "forbid"}
    to: str
    summary: str = Field(min_length=1, max_length=4000)
    output_refs: list[str] = Field(default_factory=list, max_length=80)


NodeFinalizeResult.model_rebuild()


class AgentStepResult(BaseModel):
    model_config = {"extra": "forbid"}
    status: Literal["success", "failed", "blocked"] = "success"
    decision: Literal[
        "success",
        "approved",
        "needs_changes",
        "tests_failed",
        "tests_passed",
        "passed",
        "blocked",
        "approved_for_homologation",
    ]
    summary: str = Field(min_length=1, max_length=8000)
    artifacts: list[ArtifactOutput] = Field(default_factory=list, max_length=20)
    file_operations: list[FileOperation] = Field(default_factory=list, max_length=MAX_FILES_PER_STEP)
    requirements: list[RequirementOutput] = Field(default_factory=list, max_length=80)
    test_requests: list[TestRequest] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=40)
    citations: list[str] = Field(default_factory=list, max_length=80)
    handoff: Optional[HandoffOutput] = None
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_output(self) -> "AgentStepResult":
        if self.status == "success" and not (
            self.artifacts or self.file_operations or self.requirements or self.test_requests or self.decision
        ):
            raise ValueError("a successful agent step must produce a validated output")
        if self.decision == "blocked" and self.status != "blocked":
            self.status = "blocked"
        return self

    @classmethod
    def response_schema(cls) -> dict[str, Any]:
        return cls.model_json_schema()

    def output_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class ArtifactStepResult(BaseModel):
    """Compact response for roles that create artifacts but never mutate code."""

    model_config = {"extra": "forbid"}
    status: Literal["success", "failed", "blocked"] = "success"
    decision: Literal[
        "success", "approved", "needs_changes", "tests_failed", "tests_passed",
        "passed", "blocked", "approved_for_homologation",
    ]
    summary: str = Field(min_length=1, max_length=8000)
    artifacts: list[ArtifactOutput] = Field(default_factory=list, max_length=20)
    citations: list[str] = Field(default_factory=list, max_length=80)
    handoff: Optional[HandoffOutput] = None
    confidence: float = Field(ge=0, le=1)


class RiskArtifactStepResult(ArtifactStepResult):
    risks: list[str] = Field(default_factory=list, max_length=40)


class RequirementsArtifactStepResult(RiskArtifactStepResult):
    requirements: list[RequirementOutput] = Field(default_factory=list, max_length=80)


class EngineeringStepResult(RiskArtifactStepResult):
    file_operations: list[FileOperation] = Field(default_factory=list, max_length=MAX_FILES_PER_STEP)


class QAStepResult(RiskArtifactStepResult):
    test_requests: list[TestRequest] = Field(default_factory=list, max_length=8)


def result_contract_for_node(node_id: str) -> type[BaseModel]:
    if node_id in {"Acceptance Criteria Architect", "Scope Governor", "Product Manager"}:
        return RequirementsArtifactStepResult
    if node_id == "Engineer":
        return EngineeringStepResult
    if node_id == "QA Engineer":
        return QAStepResult
    if node_id in {
        "UX UI Designer", "Architect", "Data Architect", "API Contract Engineer", "Code Reviewer",
        "Visual QA Agent", "Accessibility QA Agent", "Security Engineer", "DevOps Engineer", "Quality Governor",
    }:
        return RiskArtifactStepResult
    return ArtifactStepResult
