import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.paths import run_workspace
from app.events.event_service import emit_event
from app.models import TestReport, WorkflowRun
from app.observability.tracing import trace_span
from app.sandbox.executor import SandboxExecutor


@dataclass(frozen=True)
class ToolProfile:
    name: str
    command: str
    evidence_kind: str


TOOL_PROFILES = {
    "backend_tests": ToolProfile("backend_tests", "python -m pytest generated_app/backend/tests", "test"),
    "backend_smoke": ToolProfile(
        "backend_smoke",
        'python -c "from generated_app.backend.app.main import app; assert app"',
        "build",
    ),
    "frontend_tests": ToolProfile("frontend_tests", "npm --prefix generated_app/frontend run test", "test"),
    "frontend_build": ToolProfile("frontend_build", "npm --prefix generated_app/frontend run build", "build"),
    "visual_tests": ToolProfile("visual_tests", "npm --prefix generated_app/frontend run test:visual", "visual"),
    "accessibility_tests": ToolProfile("accessibility_tests", "npm --prefix generated_app/frontend run test:a11y", "accessibility"),
    "security_scan": ToolProfile("security_scan", "bandit -q -r generated_app/backend -f json", "security"),
}


NODE_REQUIRED_PROFILES = {
    "QA Engineer": ["backend_tests", "backend_smoke", "frontend_tests", "frontend_build"],
    "Visual QA Agent": ["visual_tests"],
    "Accessibility QA Agent": ["accessibility_tests"],
    "Security Engineer": ["security_scan"],
}


def allowed_commands() -> list[str]:
    return [profile.command for profile in TOOL_PROFILES.values()]


class ToolProfileRunner:
    def run(self, db: Session, *, run: WorkflowRun, node_id: str, profile_name: str) -> TestReport:
        profile = TOOL_PROFILES.get(profile_name)
        if not profile:
            raise ValueError(f"Unknown allowlisted tool profile: {profile_name}")
        emit_event(
            db,
            run.id,
            "tool.profile_started",
            f"{node_id} iniciou o perfil allowlisted {profile_name}.",
            node_id=node_id,
            agent_name=node_id,
            payload={"profile": profile_name, "command": profile.command},
        )
        with trace_span("sandbox.profile", {"asf.profile": profile_name, "asf.node": node_id}):
            result = SandboxExecutor().run(
                command=profile.command,
                workspace=run_workspace(run.id, run.tenant_id),
                timeout=None,
                db=db,
                tenant_id=run.tenant_id,
                run_id=run.id,
            )
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        passed_count, failed_count = self._counts(stdout, profile.evidence_kind, str(result.get("status")))
        report = TestReport(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            sandbox_execution_id=str(result["sandbox_execution_id"]),
            command=profile.command,
            status=str(result["status"]),
            passed_count=passed_count,
            failed_count=failed_count,
            stdout=stdout,
            stderr=stderr,
            timed_out=bool(result.get("timed_out")),
            duration_seconds=float(result.get("duration_seconds") or 0.0),
        )
        db.add(report)
        emit_event(
            db,
            run.id,
            "tool.profile_completed",
            f"Perfil {profile_name}: {report.status}.",
            node_id=node_id,
            agent_name=node_id,
            status=report.status,
            payload={"profile": profile_name, "test_report_id": report.id, "sandbox_execution_id": report.sandbox_execution_id},
        )
        return report

    @staticmethod
    def _counts(stdout: str, evidence_kind: str, status: str) -> tuple[int, int]:
        passed_match = re.search(r"(\d+) passed", stdout)
        failed_match = re.search(r"(\d+) failed", stdout)
        if passed_match or failed_match:
            return int(passed_match.group(1)) if passed_match else 0, int(failed_match.group(1)) if failed_match else 0
        if status == "passed":
            return 1, 0
        return 0, 1 if evidence_kind in {"test", "build", "visual", "accessibility", "security"} else 0
