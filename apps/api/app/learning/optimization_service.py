import hashlib
import hmac
import re
import statistics
import uuid
from collections import Counter
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import (
    AIInvocation,
    AgentStepExecution,
    GlobalLearningEvidence,
    LearningCandidate,
    LearningEvaluation,
    LearningLesson,
    LearningPolicy,
    ModelCall,
    QualityGate,
    Requirement,
    RequirementTrace,
    TestReport,
    WorkflowRun,
    utcnow,
)
from app.core.config import get_settings
from app.service_delivery.ledger import append_ledger_event


class LearningOptimizationError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"code": code, "message": message}


_REDACTIONS = {
    "secret": re.compile(r"(?i)(?:sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]{12,}|(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S+)"),
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "uuid": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE),
    "url": re.compile(r"https?://\S+", re.IGNORECASE),
    "ip": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "code": re.compile(r"```[\s\S]*?```"),
    "path": re.compile(r"(?:^|\s)(?:/[\w.-]+){2,}|\b(?:generated_app|apps?)/[\w./-]+"),
}


def anonymize_abstract_pattern(text: str) -> tuple[str, dict[str, Any]]:
    sanitized = str(text or "").strip()
    counts: dict[str, int] = {}
    for label, pattern in _REDACTIONS.items():
        sanitized, count = pattern.subn(f"[{label.upper()}_REMOVIDO]", sanitized)
        counts[label] = count
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    evidence = {
        "method": "deterministic-redaction-v1",
        "redaction_counts": counts,
        "source_sha256": hashlib.sha256(str(text or "").encode()).hexdigest(),
        "result_sha256": hashlib.sha256(sanitized.encode()).hexdigest(),
        "contains_raw_source": False,
    }
    return sanitized, evidence


def extract_abstract_rule(text: str, agent_name: str) -> tuple[str, dict[str, Any]]:
    """Map private feedback to a closed, client-free quality rubric."""

    redacted, evidence = anonymize_abstract_pattern(text)
    normalized = redacted.casefold()
    categories = [
        ("security", ("security", "segurança", "vulnerability", "vulnerabilidade", "secret")),
        ("grounding", ("citation", "citação", "source", "fonte", "rag", "evidence", "evidência")),
        ("verification", ("test", "teste", "build", "qa", "rework", "retrabalho")),
        ("context", ("context", "contexto", "token", "reference", "referência")),
        ("accessibility", ("accessibility", "acessibilidade", "wcag", "axe")),
        ("requirements", ("requirement", "requisito", "acceptance", "aceite", "scope", "escopo")),
        ("review", ("review", "revisão", "diff", "code", "código")),
    ]
    category = next((name for name, terms in categories if any(term in normalized for term in terms)), "quality")
    rules = {
        "security": "Treat critical security evidence as blocking and require a verified remediation before approval.",
        "grounding": "Require every material claim to reference supplied evidence and reject unsupported assertions.",
        "verification": "Require deterministic test evidence for acceptance criteria and route real failures through bounded rework.",
        "context": "Select only task-relevant references under an explicit context budget and record why each reference was included.",
        "accessibility": "Require automated accessibility evidence plus an auditable review before approval.",
        "requirements": "Compare delivered behavior with explicit acceptance criteria and block approval when coverage is incomplete.",
        "review": "Review changed behavior against requirements, architecture and diffs before approving implementation.",
        "quality": "Require explicit evidence against the applicable quality rubric before completing the task.",
    }
    role = agent_name if agent_name in {
        "Demand Classifier", "Acceptance Criteria Architect", "Scope Governor", "Product Manager",
        "UX UI Designer", "Architect", "Data Architect", "API Contract Engineer", "Project Manager",
        "Engineer", "Code Reviewer", "QA Engineer", "Visual QA Agent", "Accessibility QA Agent",
        "Security Engineer", "DevOps Engineer", "Release Manager", "Quality Governor", "Learning Curator",
    } else "Responsible Agent"
    pattern = f"Role: {role}. Rule: {rules[category]}"
    evidence = {
        **evidence,
        "method": "closed-rubric-local-abstraction-v1",
        "category": category,
        "result_sha256": hashlib.sha256(pattern.encode()).hexdigest(),
        "contains_raw_source": False,
        "contains_client_facts": False,
    }
    return pattern, evidence


class LearningOptimizationService:
    def enforce_runtime_rollback(self, db: Session, *, run: WorkflowRun) -> list[str]:
        """Restore the previous pointer when an active policy regresses critically."""

        self._record_cost_benchmark_evidence(db, run)

        active = db.query(LearningPolicy).filter_by(tenant_id=run.tenant_id, status="active").all()
        if not active:
            return []
        baseline = self._benchmark_metrics(db, run.tenant_id, "2.11.0")
        medians = baseline.get("medians") or {}
        if medians.get("cost_usd") is None or medians.get("hrs") is None:
            return []
        calls = db.query(ModelCall).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        steps = db.query(AgentStepExecution).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        gates = db.query(QualityGate).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        current_cost = sum(call.estimated_cost_usd for call in calls)
        benchmark = (run.context_manifest_json or {}).get("optimization_benchmark") or {}
        reasons = []
        if current_cost > float(medians["cost_usd"]) * 1.10:
            reasons.append("cost_increased_more_than_10_percent")
        if float(run.homologation_readiness_score or 0) < float(medians["hrs"]):
            reasons.append("hrs_regressed")
        if any(call.status != "success" for call in calls):
            reasons.append("model_call_regression")
        if gates and (len(gates) != 17 or any(gate.status not in {"passed", "pass", "approved"} for gate in gates)):
            reasons.append("quality_gate_regression")
        if int(benchmark.get("cross_tenant_exposures") or 0) > 0:
            reasons.append("cross_tenant_exposure")
        if medians.get("retries") is not None and sum(1 for step in steps if step.attempt > 1) > float(medians["retries"]):
            reasons.append("retries_increased")
        if medians.get("rework") is not None and int(benchmark.get("rework_cycles") or 0) > float(medians["rework"]):
            reasons.append("rework_increased")
        blind_score = benchmark.get("blinded_deliverable_quality_score")
        if blind_score is not None and medians.get("blinded_deliverable_quality") is not None and float(blind_score) < float(medians["blinded_deliverable_quality"]):
            reasons.append("blinded_deliverable_quality_regressed")
        if not reasons:
            return []
        restored: list[str] = []
        for policy in active:
            previous = db.get(LearningPolicy, policy.previous_policy_id) if policy.previous_policy_id else None
            policy.status = "rolled_back"
            policy.retired_at = utcnow()
            if previous and previous.tenant_id == run.tenant_id:
                previous.status = "active"
                previous.activated_at = utcnow()
                restored.append(previous.id)
            append_ledger_event(
                db,
                tenant_id=run.tenant_id,
                aggregate_type="learning_policy",
                aggregate_id=policy.id,
                event_type="learning.policy_auto_rolled_back",
                actor_user_id="system:quality-governor",
                correlation_id=run.id,
                payload={
                    "summary": "Critical runtime regression restored the previous policy pointer",
                    "run_id": run.id,
                    "reasons": reasons,
                    "restored_policy_id": previous.id if previous else None,
                },
            )
        return restored

    def propose_cost_policy(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor_user_id: str,
        title: str = "",
    ) -> LearningCandidate:
        fingerprint = hashlib.sha256(b"cost-policy:2.13.0").hexdigest()
        candidate = LearningCandidate(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_lesson_id=None,
            candidate_type="cost_policy",
            scope="global",
            title=(title or "Política de custo e contexto v2.13")[:240],
            abstract_pattern="Apply immutable v2.13 role contracts, bounded section context, cost envelopes and classified retries.",
            target_agents_json=[],
            evidence_json={
                "pattern_fingerprint": fingerprint,
                "workflow_version": "2.13.0",
                "benchmark_id": "asf-cost-governor-v2.13",
                "same_model_aliases": True,
                "contains_tenant_identifiers": False,
            },
            anonymization_json={
                "method": "server-owned-policy-no-client-content-v1",
                "contains_raw_source": False,
                "contains_client_facts": False,
            },
            status="candidate",
        )
        db.add(candidate)
        self._refresh_evidence_counts(db, candidate)
        append_ledger_event(
            db,
            tenant_id=tenant_id,
            aggregate_type="learning_candidate",
            aggregate_id=candidate.id,
            event_type="learning.cost_policy_proposed",
            actor_user_id=actor_user_id,
            payload={
                "summary": "Immutable v2.13 cost policy proposed for benchmark evaluation",
                "workflow_version": "2.13.0",
                "benchmark_id": "asf-cost-governor-v2.13",
            },
        )
        db.flush()
        return candidate

    def _record_cost_benchmark_evidence(self, db: Session, run: WorkflowRun) -> None:
        marker = (run.context_manifest_json or {}).get("optimization_benchmark") or {}
        if str(marker.get("policy_version") or "") != "2.13.0":
            return
        fingerprint = hashlib.sha256(b"cost-policy:2.13.0").hexdigest()
        tenant_pseudonym = self._pseudonym(run.tenant_id)
        run_fingerprint = self._pseudonym(run.id)
        if db.query(GlobalLearningEvidence).filter_by(
            pattern_fingerprint=fingerprint,
            tenant_pseudonym=tenant_pseudonym,
            run_fingerprint=run_fingerprint,
        ).first():
            return
        db.add(
            GlobalLearningEvidence(
                id=str(uuid.uuid4()),
                pattern_fingerprint=fingerprint,
                tenant_pseudonym=tenant_pseudonym,
                run_fingerprint=run_fingerprint,
                critical_security=False,
            )
        )

    def propose_global_candidate(
        self,
        db: Session,
        *,
        tenant_id: str,
        lesson_id: str,
        actor_user_id: str,
        title: str = "",
        target_agents: Optional[list[str]] = None,
        critical_security: bool = False,
    ) -> LearningCandidate:
        lesson = db.query(LearningLesson).filter_by(id=lesson_id, tenant_id=tenant_id).first()
        if not lesson:
            raise LearningOptimizationError(404, "LESSON_NOT_FOUND", "Lesson not found")
        if lesson.status != "approved":
            raise LearningOptimizationError(409, "LESSON_NOT_APPROVED", "Only an approved tenant-private lesson can be proposed")
        pattern, anonymization = extract_abstract_rule(lesson.lesson, lesson.agent_name)
        if len(pattern) < 24:
            raise LearningOptimizationError(422, "PATTERN_TOO_SHORT", "The anonymized pattern is too short to evaluate")
        candidate = LearningCandidate(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_lesson_id=lesson.id,
            candidate_type="critical_security" if critical_security else "lesson",
            scope="global",
            title=(title or "Padrão abstrato para avaliação")[:240],
            abstract_pattern=pattern,
            target_agents_json=list(dict.fromkeys(target_agents or [lesson.agent_name])),
            evidence_json={
                "source_lesson_hash": hashlib.sha256(lesson.id.encode()).hexdigest(),
                "run_hashes": [hashlib.sha256(lesson.run_id.encode()).hexdigest()] if lesson.run_id else [],
            },
            anonymization_json=anonymization,
            evidence_run_count=1 if lesson.run_id else 0,
            evidence_tenant_count=1,
            status="candidate",
        )
        db.add(candidate)
        pattern_fingerprint = hashlib.sha256(pattern.casefold().encode()).hexdigest()
        tenant_pseudonym = self._pseudonym(tenant_id)
        run_fingerprint = self._pseudonym(lesson.run_id or lesson.id)
        evidence = (
            db.query(GlobalLearningEvidence)
            .filter_by(
                pattern_fingerprint=pattern_fingerprint,
                tenant_pseudonym=tenant_pseudonym,
                run_fingerprint=run_fingerprint,
            )
            .first()
        )
        if not evidence:
            db.add(
                GlobalLearningEvidence(
                    id=str(uuid.uuid4()),
                    pattern_fingerprint=pattern_fingerprint,
                    tenant_pseudonym=tenant_pseudonym,
                    run_fingerprint=run_fingerprint,
                    critical_security=critical_security,
                )
            )
        candidate.evidence_json = {
            **candidate.evidence_json,
            "pattern_fingerprint": pattern_fingerprint,
        }
        append_ledger_event(
            db,
            tenant_id=tenant_id,
            aggregate_type="learning_candidate",
            aggregate_id=candidate.id,
            event_type="learning.candidate_proposed",
            actor_user_id=actor_user_id,
            payload={
                "summary": "An anonymized global learning candidate was proposed",
                "candidate_type": candidate.candidate_type,
                "anonymization": anonymization,
            },
        )
        db.flush()
        return candidate

    def evaluate_candidate(
        self,
        db: Session,
        *,
        candidate: LearningCandidate,
        actor_user_id: str,
    ) -> LearningEvaluation:
        self._refresh_evidence_counts(db, candidate)
        evaluation = LearningEvaluation(
            id=str(uuid.uuid4()),
            tenant_id=candidate.tenant_id,
            candidate_id=candidate.id,
            baseline_version="2.11.0",
            candidate_version="2.13.0",
            repetitions=3,
            status="running",
        )
        db.add(evaluation)
        db.flush()
        baseline = self._benchmark_metrics(db, candidate.tenant_id, "2.11.0")
        proposed = self._benchmark_metrics(db, candidate.tenant_id, "2.13.0")
        gates = self._promotion_gates(baseline, proposed)
        passed = all(bool(value) for value in gates.values())
        missing = [name for name, value in gates.items() if not value]
        evaluation.baseline_metrics_json = baseline
        evaluation.candidate_metrics_json = proposed
        evaluation.gate_results_json = {**gates, "failed": missing}
        evaluation.status = "passed" if passed else "blocked"
        evaluation.finished_at = utcnow()
        candidate.evaluation_json = {
            "evaluation_id": evaluation.id,
            "status": evaluation.status,
            "baseline": baseline,
            "candidate": proposed,
            "gate_results": evaluation.gate_results_json,
        }
        candidate.status = "evaluated" if passed else "evaluation_blocked"
        append_ledger_event(
            db,
            tenant_id=candidate.tenant_id,
            aggregate_type="learning_candidate",
            aggregate_id=candidate.id,
            event_type="learning.candidate_evaluated",
            actor_user_id=actor_user_id,
            payload={
                "summary": "Baseline and candidate benchmark medians were compared",
                "evaluation_id": evaluation.id,
                "status": evaluation.status,
                "failed_gates": missing,
            },
        )
        return evaluation

    def _refresh_evidence_counts(self, db: Session, candidate: LearningCandidate) -> None:
        fingerprint = str((candidate.evidence_json or {}).get("pattern_fingerprint") or "")
        rows = db.query(GlobalLearningEvidence).filter_by(pattern_fingerprint=fingerprint).all() if fingerprint else []
        candidate.evidence_run_count = len({row.run_fingerprint for row in rows})
        candidate.evidence_tenant_count = len({row.tenant_pseudonym for row in rows})
        candidate.evidence_json = {
            **(candidate.evidence_json or {}),
            "corroborated_run_count": candidate.evidence_run_count,
            "corroborated_tenant_count": candidate.evidence_tenant_count,
            "contains_tenant_identifiers": False,
        }

    @staticmethod
    def _pseudonym(value: str) -> str:
        settings = get_settings()
        secret = settings.encryption_key
        if not secret and settings.runtime_profile.lower() == "test":
            secret = "asf-test-learning-evidence"
        if not secret:
            raise LearningOptimizationError(
                503,
                "LEARNING_PSEUDONYM_KEY_REQUIRED",
                "ASF_ENCRYPTION_KEY is required to create cross-tenant learning evidence",
            )
        return hmac.new(secret.encode(), str(value).encode(), hashlib.sha256).hexdigest()

    def decide_candidate(
        self,
        db: Session,
        *,
        candidate: LearningCandidate,
        decision: str,
        comment: str,
        actor_user_id: str,
    ) -> LearningCandidate:
        if decision not in {"approve", "reject"}:
            raise LearningOptimizationError(422, "INVALID_DECISION", "Decision must be approve or reject")
        if not comment.strip():
            raise LearningOptimizationError(422, "COMMENT_REQUIRED", "A decision comment is required")
        if candidate.status in {"approved", "rejected"}:
            raise LearningOptimizationError(409, "CANDIDATE_ALREADY_DECIDED", "Candidate already has a final decision")
        if decision == "approve":
            evaluation = (
                db.query(LearningEvaluation)
                .filter_by(tenant_id=candidate.tenant_id, candidate_id=candidate.id, status="passed")
                .order_by(LearningEvaluation.finished_at.desc())
                .first()
            )
            self._refresh_evidence_counts(db, candidate)
            enough_evidence = candidate.evidence_run_count >= 3 and candidate.evidence_tenant_count >= 2
            if candidate.candidate_type != "critical_security" and not enough_evidence:
                raise LearningOptimizationError(
                    409,
                    "INSUFFICIENT_INDEPENDENT_EVIDENCE",
                    "Global promotion requires at least three independent runs across two tenants",
                )
            if not evaluation:
                raise LearningOptimizationError(409, "EVALUATION_NOT_PASSED", "A passing three-run evaluation is required")
            self._create_shadow_policy(db, candidate, actor_user_id)
            candidate.status = "approved"
        else:
            candidate.status = "rejected"
        candidate.decision_comment = comment.strip()
        candidate.decided_by_user_id = actor_user_id
        candidate.decided_at = utcnow()
        append_ledger_event(
            db,
            tenant_id=candidate.tenant_id,
            aggregate_type="learning_candidate",
            aggregate_id=candidate.id,
            event_type=f"learning.candidate_{candidate.status}",
            actor_user_id=actor_user_id,
            payload={"summary": f"Learning candidate {candidate.status} by a human", "comment": comment.strip()},
        )
        return candidate

    def advance_rollout(
        self,
        db: Session,
        *,
        policy: LearningPolicy,
        actor_user_id: str,
        comment: str,
    ) -> LearningPolicy:
        transitions = {"shadow": "internal", "internal": "canary", "canary": "active"}
        target = transitions.get(policy.status)
        if not target:
            raise LearningOptimizationError(409, "ROLLOUT_STAGE_FINAL", "Policy cannot advance from its current stage")
        if not comment.strip():
            raise LearningOptimizationError(422, "COMMENT_REQUIRED", "A rollout comment is required")
        if policy.status in {"internal", "canary"} and not self._stage_has_passing_run(db, policy, policy.status):
            raise LearningOptimizationError(
                409,
                "ROLLOUT_EVIDENCE_REQUIRED",
                f"A passing real {policy.status} mission linked to this policy is required",
            )
        if target == "active":
            previous = (
                db.query(LearningPolicy)
                .filter_by(tenant_id=policy.tenant_id, policy_type=policy.policy_type, status="active")
                .filter(LearningPolicy.id != policy.id)
                .order_by(LearningPolicy.activated_at.desc())
                .first()
            )
            if previous:
                previous.status = "retired"
                previous.retired_at = utcnow()
                policy.previous_policy_id = previous.id
            policy.activated_at = utcnow()
        history = list((policy.configuration_json or {}).get("rollout_history") or [])
        history.append({"from": policy.status, "to": target, "at": utcnow().isoformat(), "comment": comment.strip()})
        policy.configuration_json = {**(policy.configuration_json or {}), "rollout_stage": target, "rollout_history": history}
        policy.status = target
        append_ledger_event(
            db,
            tenant_id=policy.tenant_id,
            aggregate_type="learning_policy",
            aggregate_id=policy.id,
            event_type="learning.policy_rollout_advanced",
            actor_user_id=actor_user_id,
            payload={"summary": "Human advanced the learning policy rollout", "stage": target, "comment": comment.strip()},
        )
        return policy

    def rollback_policy(
        self,
        db: Session,
        *,
        policy: LearningPolicy,
        actor_user_id: str,
        comment: str,
    ) -> LearningPolicy:
        if policy.status != "active":
            raise LearningOptimizationError(409, "POLICY_NOT_ACTIVE", "Only an active policy can be rolled back")
        if not comment.strip():
            raise LearningOptimizationError(422, "COMMENT_REQUIRED", "A rollback comment is required")
        previous = db.get(LearningPolicy, policy.previous_policy_id) if policy.previous_policy_id else None
        if not previous or previous.tenant_id != policy.tenant_id:
            raise LearningOptimizationError(409, "NO_ROLLBACK_TARGET", "No immutable previous policy is available")
        policy.status = "rolled_back"
        policy.retired_at = utcnow()
        previous.status = "active"
        previous.activated_at = utcnow()
        append_ledger_event(
            db,
            tenant_id=policy.tenant_id,
            aggregate_type="learning_policy",
            aggregate_id=policy.id,
            event_type="learning.policy_rolled_back",
            actor_user_id=actor_user_id,
            payload={"summary": "Learning policy pointer restored", "restored_policy_id": previous.id, "comment": comment.strip()},
        )
        return previous

    @staticmethod
    def _create_shadow_policy(db: Session, candidate: LearningCandidate, actor_user_id: str) -> LearningPolicy:
        policy_type = candidate.candidate_type
        previous = (
            db.query(LearningPolicy)
            .filter_by(tenant_id=candidate.tenant_id, policy_type=policy_type, status="active")
            .order_by(LearningPolicy.activated_at.desc())
            .first()
        )
        policy = LearningPolicy(
            id=str(uuid.uuid4()),
            tenant_id=candidate.tenant_id,
            candidate_id=candidate.id,
            policy_type=policy_type,
            version=f"2.13.{uuid.uuid4().hex[:8]}",
            status="shadow",
            configuration_json={
                "abstract_pattern": candidate.abstract_pattern,
                "target_agents": candidate.target_agents_json,
                "scope": candidate.scope,
                "rollout_stage": "shadow",
                "rollout_history": [],
                "benchmark_id": (candidate.evidence_json or {}).get("benchmark_id"),
                "workflow_version": (candidate.evidence_json or {}).get("workflow_version"),
            },
            previous_policy_id=previous.id if previous else None,
            created_by_user_id=actor_user_id,
            activated_at=None,
        )
        db.add(policy)
        return policy

    @staticmethod
    def _stage_has_passing_run(db: Session, policy: LearningPolicy, stage: str) -> bool:
        runs = db.query(WorkflowRun).filter_by(
            tenant_id=policy.tenant_id,
            workflow_id="software_factory_ai_native_v2",
        ).all()
        for run in runs:
            marker = (run.context_manifest_json or {}).get("learning_rollout") or {}
            if marker.get("policy_id") != policy.id or marker.get("stage") != stage:
                continue
            calls = db.query(ModelCall).filter_by(tenant_id=policy.tenant_id, run_id=run.id).all()
            tests = db.query(TestReport).filter_by(tenant_id=policy.tenant_id, run_id=run.id).all()
            gates = db.query(QualityGate).filter_by(tenant_id=policy.tenant_id, run_id=run.id).all()
            if (
                calls
                and all(call.status == "success" for call in calls)
                and tests
                and all(report.status == "passed" for report in tests)
                and len(gates) == 17
                and all(gate.status in {"passed", "pass", "approved"} for gate in gates)
                and int(marker.get("cross_tenant_exposures") or 0) == 0
            ):
                return True
        return False

    @staticmethod
    def _benchmark_metrics(db: Session, tenant_id: str, version: str) -> dict[str, Any]:
        runs = db.query(WorkflowRun).filter_by(tenant_id=tenant_id, workflow_id="software_factory_ai_native_v2").all()
        matching = []
        for run in runs:
            benchmark = (run.context_manifest_json or {}).get("optimization_benchmark") or {}
            if str(benchmark.get("policy_version") or "") == version:
                matching.append((run, benchmark))
        per_run: list[dict[str, Any]] = []
        for run, benchmark in matching:
            calls = db.query(ModelCall).filter_by(tenant_id=tenant_id, run_id=run.id).all()
            steps = db.query(AgentStepExecution).filter_by(tenant_id=tenant_id, run_id=run.id).all()
            tests = db.query(TestReport).filter_by(tenant_id=tenant_id, run_id=run.id).all()
            gates = db.query(QualityGate).filter_by(tenant_id=tenant_id, run_id=run.id).all()
            requirements = db.query(Requirement).filter_by(tenant_id=tenant_id, run_id=run.id, priority="P0").all()
            traces = db.query(RequirementTrace).filter_by(tenant_id=tenant_id, run_id=run.id, status="pass").all()
            traced_requirements = {trace.requirement_id for trace in traces}
            requirement_coverage = (
                len([item for item in requirements if item.requirement_id in traced_requirements]) / len(requirements)
                if requirements else 0.0
            )
            citations = [
                citation
                for step in steps
                for citation in ((step.output_manifest_json or {}).get("citations") or [])
            ]
            supplied = {
                str(reference.get("ref_id"))
                for step in steps
                for reference in ((step.input_manifest_json or {}).get("references") or [])
            }
            citation_precision = (
                sum(1 for citation in citations if citation in supplied) / len(citations)
                if citations else 0.0
            )
            required_commands = {
                "python -m pytest generated_app/backend/tests",
                'python -c "from generated_app.backend.app.main import app; assert app"',
                "npm --prefix generated_app/frontend run test",
                "npm --prefix generated_app/frontend run build",
                "npm --prefix generated_app/frontend run test:visual",
                "npm --prefix generated_app/frontend run test:a11y",
                "bandit -q -r generated_app/backend -f json",
            }
            commands = {report.command for report in tests if report.status == "passed" and report.sandbox_execution_id}
            per_run.append(
                {
                    "run_hash": hashlib.sha256(run.id.encode()).hexdigest(),
                    "mission": str(benchmark.get("mission") or ""),
                    "tokens": sum(call.prompt_tokens + call.completion_tokens for call in calls),
                    "cost_usd": sum(call.estimated_cost_usd for call in calls),
                    "latency_seconds": sum(call.duration_seconds for call in calls),
                    "retries": sum(1 for step in steps if step.attempt > 1),
                    "rework": int(benchmark.get("rework_cycles") or 0),
                    "schemas_valid": bool(steps) and all(step.status == "completed" for step in steps),
                    "model_calls_valid": bool(calls) and all(call.status == "success" for call in calls),
                    "usage_real": bool(calls) and all(
                        call.prompt_tokens > 0 and call.completion_tokens > 0 and call.estimated_cost_usd > 0
                        for call in calls
                    ),
                    "tests_passed": required_commands.issubset(commands),
                    "gate_count": len(gates),
                    "gates_passed": len(gates) == 17 and all(gate.status in {"passed", "pass", "approved"} for gate in gates),
                    "hrs": float(run.homologation_readiness_score or 0),
                    "cross_tenant_exposures": int(benchmark.get("cross_tenant_exposures", -1)),
                    "requirement_coverage": requirement_coverage,
                    "citation_precision": citation_precision,
                    "blinded_deliverable_quality": (
                        float(benchmark["blinded_deliverable_quality_score"])
                        if benchmark.get("blinded_deliverable_quality_score") is not None
                        else None
                    ),
                }
            )
        missions = Counter(row["mission"] for row in per_run)
        journey_invocations = db.query(AIInvocation).filter_by(tenant_id=tenant_id, policy_version=version).all()
        journey_scopes = sorted(
            {
                invocation.scope_type
                for invocation in journey_invocations
                if invocation.status == "success" and invocation.scope_type != "factory_run"
            }
        )

        def median(key: str) -> Optional[float]:
            values = [float(row[key]) for row in per_run if row.get(key) is not None]
            return statistics.median(values) if values else None

        def dispersion(key: str) -> Optional[float]:
            values = [float(row[key]) for row in per_run if row.get(key) is not None]
            return statistics.pstdev(values) if len(values) > 1 else (0.0 if values else None)

        return {
            "policy_version": version,
            "run_count": len(per_run),
            "missions": dict(missions),
            "medians": {key: median(key) for key in ["tokens", "cost_usd", "latency_seconds", "retries", "rework", "hrs", "requirement_coverage", "citation_precision", "blinded_deliverable_quality"]},
            "dispersion": {key: dispersion(key) for key in ["tokens", "cost_usd", "latency_seconds", "retries", "rework", "hrs"]},
            "all_schemas_valid": bool(per_run) and all(row["schemas_valid"] and row["model_calls_valid"] for row in per_run),
            "all_usage_real": bool(per_run) and all(row["usage_real"] for row in per_run),
            "all_tests_passed": bool(per_run) and all(row["tests_passed"] for row in per_run),
            "all_gates_passed": bool(per_run) and all(row["gates_passed"] for row in per_run),
            "zero_cross_tenant_exposure": bool(per_run) and all(row["cross_tenant_exposures"] == 0 for row in per_run),
            "runs": per_run,
            "model_aliases": sorted({f"{call.model_role}:{call.model_name}" for run, _ in matching for call in db.query(ModelCall).filter_by(tenant_id=tenant_id, run_id=run.id).all()}),
            "journey_scopes": journey_scopes,
            "journey_cost_usd": round(sum(invocation.actual_cost_usd for invocation in journey_invocations), 8),
        }

    @staticmethod
    def _promotion_gates(baseline: dict[str, Any], proposed: dict[str, Any]) -> dict[str, bool]:
        base = baseline.get("medians") or {}
        candidate = proposed.get("medians") or {}

        def reduction(key: str) -> bool:
            before = base.get(key)
            after = candidate.get(key)
            return before is not None and after is not None and before > 0 and after <= before * 0.60

        missions = proposed.get("missions") or {}
        baseline_missions = baseline.get("missions") or {}
        return {
            "baseline_three_repetitions_per_mission": baseline_missions.get("ContractFlow", 0) >= 3 and baseline_missions.get("ServiceDesk", 0) >= 3,
            "candidate_three_repetitions_per_mission": missions.get("ContractFlow", 0) >= 3 and missions.get("ServiceDesk", 0) >= 3,
            "tokens_reduced_40_percent": reduction("tokens"),
            "cost_reduced_40_percent": reduction("cost_usd"),
            "schemas_100_percent_valid": bool(proposed.get("all_schemas_valid")),
            "provider_usage_is_real": bool(proposed.get("all_usage_real")),
            "same_model_aliases": bool(baseline.get("model_aliases")) and baseline.get("model_aliases") == proposed.get("model_aliases"),
            "zero_cross_tenant_exposure": bool(proposed.get("zero_cross_tenant_exposure")),
            "same_17_gates": bool(proposed.get("all_gates_passed")),
            "tests_build_axe_security_passed": bool(proposed.get("all_tests_passed")),
            "hrs_not_lower": base.get("hrs") is not None and candidate.get("hrs") is not None and candidate["hrs"] >= base["hrs"],
            "requirement_coverage_not_lower": base.get("requirement_coverage") is not None and candidate.get("requirement_coverage") is not None and candidate["requirement_coverage"] >= base["requirement_coverage"],
            "citation_precision_not_lower": base.get("citation_precision") is not None and candidate.get("citation_precision") is not None and candidate["citation_precision"] >= base["citation_precision"],
            "blinded_deliverable_quality_not_lower": base.get("blinded_deliverable_quality") is not None and candidate.get("blinded_deliverable_quality") is not None and candidate["blinded_deliverable_quality"] >= base["blinded_deliverable_quality"],
            "retries_not_higher": base.get("retries") is not None and candidate.get("retries") is not None and candidate["retries"] <= base["retries"],
            "rework_not_higher": base.get("rework") is not None and candidate.get("rework") is not None and candidate["rework"] <= base["rework"],
            "full_journey_attributed": {"engagement_plan", "service_deliverable", "rag_answer", "agent_candidate", "agent_evaluation"}.issubset(set(proposed.get("journey_scopes") or [])),
        }
