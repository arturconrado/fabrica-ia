import uuid
from typing import Callable

from sqlalchemy.orm import Session

from app.events.event_service import emit_event
from app.models import (
    AcceptanceCriterion,
    AgentStepExecution,
    Artifact,
    FileChange,
    HomologationPackage,
    HomologationReport,
    QualityGate,
    QualityScore,
    Requirement,
    RequirementTrace,
    TestReport,
    WorkflowRun,
)
from app.quality.quality_gate_engine import QUALITY_GATES
from app.observability.tracing import trace_span


class AINativeQualityEvaluator:
    REQUIRED_TEST_COMMAND_MARKERS = {
        "tests": [
            "generated_app/backend/tests",
            "from generated_app.backend.app.main import app",
            "generated_app/frontend run test",
            "generated_app/frontend run build",
        ],
        "visual_qa": ["test:visual"],
        "accessibility": ["test:a11y"],
        "security": ["bandit"],
    }

    def evaluate(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        package_builder: Callable[[Session, WorkflowRun, float, str, list[str]], None],
    ) -> tuple[float, list[str]]:
        with trace_span("quality.gates", {"asf.gate_count": len(QUALITY_GATES)}):
            return self._evaluate(db, run=run, package_builder=package_builder)

    def _evaluate(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        package_builder: Callable[[Session, WorkflowRun, float, str, list[str]], None],
    ) -> tuple[float, list[str]]:
        artifacts = {
            artifact.name: artifact
            for artifact in db.query(Artifact).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        }
        files = (
            db.query(FileChange)
            .filter_by(tenant_id=run.tenant_id, run_id=run.id)
            .filter(FileChange.file_path.like("generated_app/%"))
            .all()
        )
        test_reports = db.query(TestReport).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        steps = db.query(AgentStepExecution).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()

        evidence = {
            "requirements": db.query(Requirement).filter_by(tenant_id=run.tenant_id, run_id=run.id).count() > 0,
            "acceptance_criteria": db.query(AcceptanceCriterion).filter_by(tenant_id=run.tenant_id, run_id=run.id).count() > 0,
            "scope": "SCOPE.md" in artifacts,
            "architecture": "SYSTEM_DESIGN.md" in artifacts,
            "ux": "UX_SPEC.md" in artifacts,
            "data": "DATA_MODEL.md" in artifacts,
            "api": "API_SPEC.md" in artifacts,
            "implementation": bool(files),
            "code_review": any(step.node_id == "Code Reviewer" and step.decision == "approved" and step.status == "completed" for step in steps),
            "tests": self._profiles_passed(test_reports, self.REQUIRED_TEST_COMMAND_MARKERS["tests"]),
            "traceability": db.query(RequirementTrace).filter_by(tenant_id=run.tenant_id, run_id=run.id).count() > 0,
            "visual_qa": self._profiles_passed(test_reports, self.REQUIRED_TEST_COMMAND_MARKERS["visual_qa"]),
            "accessibility": self._profiles_passed(test_reports, self.REQUIRED_TEST_COMMAND_MARKERS["accessibility"]),
            "security": self._profiles_passed(test_reports, self.REQUIRED_TEST_COMMAND_MARKERS["security"]),
            "documentation": "RELEASE_NOTES.md" in artifacts and any(change.file_path.endswith("README.md") for change in files),
            "homologation_package": False,
            "human_approval": False,
        }

        db.query(QualityGate).filter_by(tenant_id=run.tenant_id, run_id=run.id).delete(synchronize_session=False)
        gate_rows: list[QualityGate] = []
        blockers: list[str] = []
        for gate_id, name, category in QUALITY_GATES:
            if gate_id == "human_approval":
                status, score, classification = "pending", 0.0, "declared"
            elif gate_id == "homologation_package":
                status, score, classification = "pending", 0.0, "real"
            elif evidence.get(gate_id):
                status, score, classification = "passed", 100.0, "real" if gate_id in self.REQUIRED_TEST_COMMAND_MARKERS else "calculated"
            else:
                status, score, classification = "blocked", 0.0, "calculated"
                blockers.append(f"Missing verified evidence for {gate_id}")
            gate = QualityGate(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                gate_id=gate_id,
                name=name,
                category=category,
                status=status,
                score=score,
                blockers_json=[] if status != "blocked" else [blockers[-1]],
                warnings_json=[] if status == "passed" else (["Explicit human decision required"] if gate_id == "human_approval" else []),
                evidence_json={"classification": classification, "observed": evidence.get(gate_id, False)},
            )
            db.add(gate)
            gate_rows.append(gate)
            emit_event(
                db,
                run.id,
                "quality.gate_passed" if status == "passed" else "quality.gate_blocked" if status == "blocked" else "quality.gate_review_required",
                f"{name}: {status}.",
                node_id="Quality Governor",
                phase="quality_governance",
                status=status,
                payload={"gate_id": gate_id, "classification": classification},
            )
        db.flush()

        provisional = round(sum(gate.score for gate in gate_rows) / len(gate_rows), 2)
        status = "blocked" if blockers else "awaiting_human_review"
        report = HomologationReport(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            status=status,
            score=provisional,
            blockers_json=blockers,
            risks_json=[],
            summary="AI-produced deliverables evaluated only from persisted files, sandbox executions and deterministic gates.",
        )
        db.add(report)
        if not blockers:
            package_builder(db, run, provisional, status, blockers)
            package = (
                db.query(HomologationPackage)
                .filter_by(tenant_id=run.tenant_id, run_id=run.id)
                .order_by(HomologationPackage.created_at.desc())
                .first()
            )
            package_gate = next(gate for gate in gate_rows if gate.gate_id == "homologation_package")
            if package:
                package_gate.status = "passed"
                package_gate.score = 100.0
                package_gate.evidence_json = {"classification": "real", "package_id": package.id}

        score = round(sum(gate.score for gate in gate_rows) / len(gate_rows), 2)
        run.homologation_readiness_score = score
        report.score = score
        db.add(
            QualityScore(
                id=str(uuid.uuid4()),
                tenant_id=run.tenant_id,
                run_id=run.id,
                category="AI-native observed gate coverage",
                score=score,
                weight=100,
                weighted_score=score,
                evidence_json={"classification": "calculated", "gate_count": len(gate_rows), "blockers": blockers},
            )
        )
        emit_event(
            db,
            run.id,
            "quality.score_updated",
            f"AI-native HRS provisório calculado: {score}.",
            node_id="Quality Governor",
            phase="quality_governance",
            payload={"score": score, "status": status, "blockers": blockers},
        )
        return score, blockers

    @staticmethod
    def _profiles_passed(reports: list[TestReport], markers: list[str]) -> bool:
        for marker in markers:
            matching = [report for report in reports if marker in report.command]
            if not matching or matching[-1].status != "passed":
                return False
        return True
