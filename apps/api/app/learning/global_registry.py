"""Human-governed promotion and tenant deployment of sanitized global learning."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy.orm import Session

from app.learning.optimization_service import LearningOptimizationError, anonymize_abstract_pattern
from app.models import (
    GlobalLearningDeployment,
    GlobalLearningPolicy,
    LearningCandidate,
    LearningEvaluation,
    LearningPolicy,
    utcnow,
)
from app.service_delivery.ledger import append_ledger_event


class GlobalLearningRegistryService:
    def promote(
        self,
        db: Session,
        *,
        candidate: LearningCandidate,
        actor_user_id: str,
        comment: str,
        idempotency_key: str,
    ) -> GlobalLearningPolicy:
        if not idempotency_key.strip():
            raise LearningOptimizationError(422, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
        if not comment.strip():
            raise LearningOptimizationError(422, "COMMENT_REQUIRED", "An administrative promotion comment is required")
        if candidate.scope != "global" or candidate.status != "approved":
            raise LearningOptimizationError(409, "CANDIDATE_NOT_APPROVED", "Candidate requires prior human approval")
        if candidate.evidence_run_count < 3 or candidate.evidence_tenant_count < 2:
            raise LearningOptimizationError(409, "INSUFFICIENT_EVIDENCE", "Promotion requires three runs across two tenants")
        evaluation = (
            db.query(LearningEvaluation)
            .filter_by(tenant_id=candidate.tenant_id, candidate_id=candidate.id, status="passed")
            .order_by(LearningEvaluation.finished_at.desc())
            .first()
        )
        if not evaluation:
            raise LearningOptimizationError(409, "BENCHMARK_REQUIRED", "A passing benchmark evaluation is required")
        sanitized, evidence = anonymize_abstract_pattern(candidate.abstract_pattern)
        if sanitized != candidate.abstract_pattern.strip() or any(evidence["redaction_counts"].values()):
            raise LearningOptimizationError(422, "GLOBAL_PATTERN_NOT_SANITIZED", "Global registry rejected client-specific material")
        anonymization = dict(candidate.anonymization_json or {})
        if anonymization.get("contains_raw_source") is not False or anonymization.get("contains_client_facts") is not False:
            raise LearningOptimizationError(422, "SANITIZATION_EVIDENCE_REQUIRED", "Deterministic sanitization evidence is required")
        fingerprint = hashlib.sha256(sanitized.casefold().encode()).hexdigest()
        existing = db.query(GlobalLearningPolicy).filter_by(pattern_fingerprint=fingerprint).first()
        if existing:
            return existing
        policy = GlobalLearningPolicy(
            id=str(uuid.uuid4()),
            policy_type=candidate.candidate_type,
            version=f"global-{utcnow().strftime('%Y%m%d')}-{fingerprint[:10]}",
            title=candidate.title,
            abstract_pattern=sanitized,
            pattern_fingerprint=fingerprint,
            target_agents_json=list(candidate.target_agents_json or []),
            configuration_json={
                "precedence": "after_platform_before_tenant_private",
                "immutable": True,
                "source_scope": "sanitized_global",
            },
            sanitization_evidence_json={**anonymization, **evidence, "administrative_comment_hash": hashlib.sha256(comment.strip().encode()).hexdigest()},
            benchmark_evidence_json={
                "evaluation_id_hash": hashlib.sha256(evaluation.id.encode()).hexdigest(),
                "gate_results": evaluation.gate_results_json,
            },
            evidence_run_count=candidate.evidence_run_count,
            evidence_tenant_count=candidate.evidence_tenant_count,
            status="approved",
            source_candidate_fingerprint=hashlib.sha256(candidate.id.encode()).hexdigest(),
            approved_by_user_id=actor_user_id,
            approved_at=utcnow(),
        )
        db.add(policy)
        db.flush()
        append_ledger_event(
            db,
            tenant_id=candidate.tenant_id,
            aggregate_type="global_learning_policy",
            aggregate_id=policy.id,
            event_type="learning.global_policy_promoted",
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            payload={
                "summary": "Sanitized global learning policy promoted by an administrator",
                "policy_id": policy.id,
                "version": policy.version,
                "pattern_fingerprint": fingerprint,
                "comment": comment.strip(),
            },
        )
        return policy

    def deploy(
        self,
        db: Session,
        *,
        tenant_id: str,
        policy: GlobalLearningPolicy,
        rollout_stage: str,
        actor_user_id: str,
        comment: str,
        idempotency_key: str,
        expected_version: int,
    ) -> GlobalLearningDeployment:
        if rollout_stage not in {"shadow", "internal", "canary", "active"}:
            raise LearningOptimizationError(422, "INVALID_ROLLOUT_STAGE", "Invalid global policy rollout stage")
        if policy.status != "approved":
            raise LearningOptimizationError(409, "GLOBAL_POLICY_NOT_APPROVED", "Only approved immutable policies can deploy")
        previous = (
            db.query(GlobalLearningDeployment)
            .filter_by(tenant_id=tenant_id, policy_type=policy.policy_type, status="active")
            .order_by(GlobalLearningDeployment.deployment_version.desc())
            .first()
        )
        current_version = int(previous.record_version if previous else 0)
        if expected_version != current_version:
            raise LearningOptimizationError(409, "VERSION_CONFLICT", f"Expected version {expected_version}, current is {current_version}")
        if previous and previous.policy_id == policy.id and previous.rollout_stage == rollout_stage:
            return previous
        version = int(
            max(
                [row.deployment_version for row in db.query(GlobalLearningDeployment).filter_by(tenant_id=tenant_id, policy_id=policy.id).all()],
                default=0,
            )
            + 1
        )
        if previous:
            previous.status = "superseded"
            previous.record_version += 1
        deployment = GlobalLearningDeployment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            policy_id=policy.id,
            policy_type=policy.policy_type,
            deployment_version=version,
            rollout_stage=rollout_stage,
            status="active",
            previous_deployment_id=previous.id if previous else None,
            record_version=current_version + 1,
            deployed_by_user_id=actor_user_id,
            decision_comment=comment.strip(),
        )
        db.add(deployment)
        db.flush()
        append_ledger_event(
            db,
            tenant_id=tenant_id,
            aggregate_type="global_learning_deployment",
            aggregate_id=deployment.id,
            event_type="learning.global_policy_deployed",
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            payload={
                "summary": "Global policy deployment pointer changed by a human",
                "policy_id": policy.id,
                "rollout_stage": rollout_stage,
                "record_version": deployment.record_version,
                "comment": comment.strip(),
            },
        )
        return deployment

    def rollback(
        self,
        db: Session,
        *,
        tenant_id: str,
        deployment: GlobalLearningDeployment,
        actor_user_id: str,
        comment: str,
        idempotency_key: str,
        expected_version: int,
    ) -> GlobalLearningDeployment:
        if deployment.status != "active" or deployment.record_version != expected_version:
            raise LearningOptimizationError(409, "VERSION_CONFLICT", "Deployment is not the expected active version")
        previous = db.get(GlobalLearningDeployment, deployment.previous_deployment_id) if deployment.previous_deployment_id else None
        if not previous or previous.tenant_id != tenant_id:
            raise LearningOptimizationError(409, "NO_ROLLBACK_TARGET", "No previous tenant deployment is available")
        deployment.status = "rolled_back"
        deployment.record_version += 1
        deployment.rolled_back_at = utcnow()
        previous.status = "active"
        previous.record_version = deployment.record_version
        append_ledger_event(
            db,
            tenant_id=tenant_id,
            aggregate_type="global_learning_deployment",
            aggregate_id=deployment.id,
            event_type="learning.global_policy_rolled_back",
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            payload={
                "summary": "Global policy deployment pointer rolled back by a human",
                "restored_deployment_id": previous.id,
                "record_version": previous.record_version,
                "comment": comment.strip(),
            },
        )
        return previous

    @staticmethod
    def effective_policy(db: Session, *, tenant_id: str) -> dict:
        deployments = (
            db.query(GlobalLearningDeployment)
            .filter_by(tenant_id=tenant_id, status="active", rollout_stage="active")
            .order_by(GlobalLearningDeployment.deployed_at.asc())
            .all()
        )
        globals_ = [db.get(GlobalLearningPolicy, deployment.policy_id) for deployment in deployments]
        private = (
            db.query(LearningPolicy)
            .filter(LearningPolicy.tenant_id == tenant_id, LearningPolicy.status.in_(["active", "approved"]))
            .order_by(LearningPolicy.created_at.asc())
            .all()
        )
        return {
            "precedence": ["platform_controls", "approved_global", "approved_tenant_private", "task_context"],
            "platform_controls": {
                "immutable": ["quality_gates", "hrs", "security", "budget", "permissions", "tenant_isolation"],
            },
            "global": [
                {
                    "policy_id": policy.id,
                    "type": policy.policy_type,
                    "version": policy.version,
                    "pattern": policy.abstract_pattern,
                    "target_agents": policy.target_agents_json,
                }
                for policy in globals_
                if policy and policy.status == "approved"
            ],
            "tenant_private": [
                {
                    "policy_id": policy.id,
                    "type": policy.policy_type,
                    "version": policy.version,
                    "configuration": policy.configuration_json,
                }
                for policy in private
            ],
        }
