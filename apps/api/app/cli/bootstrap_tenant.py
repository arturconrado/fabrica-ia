import argparse

from sqlalchemy import text

from app.auth.dependencies import ensure_tenant, ensure_user_membership
from app.core.config import get_settings
from app.db.session import SessionLocal, set_tenant_context
from app.models import Tenant
from app.service_delivery.ledger import append_ledger_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap an assisted-pilot tenant and its operator")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--subject", required=True, help="Exact OIDC subject for the initial owner")
    parser.add_argument("--email", default="")
    parser.add_argument("--name", default="Initial Owner")
    parser.add_argument(
        "--enable-rag-generation",
        action="store_true",
        help="Allow this tenant's retrieved excerpts to be sent to the configured LLM provider",
    )
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != "bootstrap assisted pilot tenant":
        raise SystemExit("Invalid confirmation phrase")

    settings = get_settings()
    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('asf-pilot-tenant-onboarding', 3))"))
        existing = db.query(Tenant).filter_by(id=args.tenant_id).execution_options(include_all_tenants=True).first()
        active_tenants = (
            db.query(Tenant)
            .filter(Tenant.status != "deleted")
            .execution_options(include_all_tenants=True)
            .count()
        )
        if not existing and active_tenants >= settings.pilot_max_tenants:
            raise SystemExit(f"Pilot tenant limit reached ({settings.pilot_max_tenants})")
        tenant = ensure_tenant(db, args.tenant_id, args.tenant_name)
        set_tenant_context(db, tenant.id)
        user, membership = ensure_user_membership(
            db,
            tenant_id=tenant.id,
            subject=args.subject,
            email=args.email,
            name=args.name,
            role="owner",
        )
        tenant.status = "active"
        tenant.runtime_configuration_json = {
            "onboarding_status": "accepted",
            "build_mode": "ai_native" if settings.generative_build_enabled else "prebuild_only",
            "llm_real": "enabled" if args.enable_rag_generation else "opt_in",
            "rag_generation": "enabled" if args.enable_rag_generation else "extractive_only",
            "generative_build": settings.generative_build_enabled,
            "regulated_data": False,
            "storage_prefix": f"tenants/{tenant.id}/",
            "knowledge_storage_prefix": f"tenants/{tenant.id}/knowledge/",
            "limits": {
                "users": settings.pilot_max_users_per_tenant,
                "concurrent_workflows": settings.pilot_max_concurrent_workflows_per_tenant,
                "knowledge_bases": settings.knowledge_max_bases_per_tenant,
                "knowledge_documents": settings.knowledge_max_documents_per_tenant,
                "knowledge_total_chars": settings.knowledge_max_total_chars_per_tenant,
            },
        }
        tenant.retention_policy_json = {"backups_days": 7, "rpo_hours": 24, "rto_target_hours": 4}
        append_ledger_event(
            db,
            tenant_id=tenant.id,
            aggregate_type="tenant",
            aggregate_id=tenant.id,
            event_type="tenant.bootstrapped",
            actor_user_id=user.id,
            payload={
                "summary": "Assisted-pilot tenant and operator bootstrapped",
                "membership_id": membership.id,
                "rag_generation": tenant.runtime_configuration_json["rag_generation"],
            },
            idempotency_key=f"tenant-bootstrap:{tenant.id}:{user.subject}",
        )
        db.commit()
        print(f"tenant_id={tenant.id} owner_user_id={user.id} membership_id={membership.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
