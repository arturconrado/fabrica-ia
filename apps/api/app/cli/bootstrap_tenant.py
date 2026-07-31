import argparse
import uuid

from sqlalchemy import text

from app.auth.dependencies import ensure_tenant, ensure_user_membership, tenant_runtime_configuration
from app.core.config import get_settings
from app.db.session import SessionLocal, set_tenant_context
from app.models import ComponentDefinition, ComponentInstance, Contract, Entitlement, Program, Project, Tenant
from app.service_delivery.service import ensure_component_definitions
from app.service_delivery.ledger import append_ledger_event


RELEASE_CAPABILITIES = [
    "briefing.intake",
    "idea.validate",
    "mvp.scope",
    "mvp.generate",
    "mvp.review",
    "proposal.generate",
    "package.export",
    "component.start",
    "component.view",
    "asf.run.create",
    "homologation.package",
    "delivery.approve",
]


def _release_event(db, *, tenant_id: str, actor_user_id: str, aggregate_type: str,
                   aggregate_id: str, event_type: str, summary: str) -> None:
    append_ledger_event(
        db,
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        payload={"summary": summary, "environment": "homologation", "synthetic_customer": True},
        idempotency_key=f"release-seed:{tenant_id}:{aggregate_type}:{aggregate_id}:{event_type}",
    )


def seed_release_assets(db, *, tenant_id: str, actor_user_id: str) -> dict[str, str]:
    """Create only the contract surface needed to prove entitlement enforcement.

    The release tenant intentionally receives Rapid MVP Factory and nothing
    else, so the browser journey can prove both the contracted happy path and
    rejection of an uncontracted component without touching customer data.
    """
    ensure_component_definitions(db)
    contract = db.query(Contract).filter_by(
        tenant_id=tenant_id,
        contract_number="ASF-RELEASE-HOMOLOGATION-2.1",
    ).first()
    if not contract:
        contract = Contract(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            contract_number="ASF-RELEASE-HOMOLOGATION-2.1",
            status="active",
            scope_summary="Isolated release validation for Portfolio 2.1 and workflow 2.14.0.",
            commercial_metadata_json={
                "environment": "homologation",
                "validation": True,
                "customer_data": False,
                "portfolio_version": "2.1",
                "workflow_version": "2.14.0",
            },
        )
        db.add(contract)
        db.flush()
        _release_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            aggregate_type="contract", aggregate_id=contract.id,
            event_type="release_contract.seeded", summary="Release validation contract seeded",
        )
    elif contract.status != "active":
        contract.status = "active"
        _release_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            aggregate_type="contract", aggregate_id=contract.id,
            event_type="release_contract.activated", summary="Release validation contract activated",
        )

    definition = db.query(ComponentDefinition).filter_by(code="rapid_mvp_factory", version="1.0").one()
    entitlement = db.query(Entitlement).filter_by(
        tenant_id=tenant_id,
        contract_id=contract.id,
        component_code=definition.code,
    ).first()
    if not entitlement:
        entitlement = Entitlement(
            id=str(uuid.uuid4()), tenant_id=tenant_id, contract_id=contract.id,
            component_definition_id=definition.id, component_code=definition.code,
            status="granted", limits_json={"mvp_runs": 100, "users": 20, "concurrent_workflows": 2},
            capabilities_json=RELEASE_CAPABILITIES,
            terms_json={
                "environment": "homologation", "validation": True,
                "build_mode": "ai_native", "generative_build": True,
                "regulated_data": False, "customer_data": False,
            },
        )
        db.add(entitlement)
        db.flush()
        _release_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            aggregate_type="entitlement", aggregate_id=entitlement.id,
            event_type="release_entitlement.seeded", summary="Release-only Rapid MVP entitlement seeded",
        )

    program = db.query(Program).filter_by(tenant_id=tenant_id, name="Release Homologation 2.1").first()
    if not program:
        program = Program(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="Release Homologation 2.1",
            description="Synthetic-data release validation; never a customer engagement.",
            sponsor="Internal release authority", status="active",
        )
        db.add(program)
        db.flush()
        _release_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            aggregate_type="program", aggregate_id=program.id,
            event_type="release_program.seeded", summary="Release homologation program seeded",
        )

    project = db.query(Project).filter_by(tenant_id=tenant_id, name="Release Evidence Workspace").first()
    if not project:
        project = Project(
            id=str(uuid.uuid4()), tenant_id=tenant_id, program_id=program.id,
            name="Release Evidence Workspace",
            description="Isolated synthetic workspace for contracted release probes.",
            scope="Portfolio 2.1 release evidence", owner_user_id=actor_user_id, status="active",
        )
        db.add(project)
        db.flush()
        _release_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            aggregate_type="project", aggregate_id=project.id,
            event_type="release_project.seeded", summary="Release evidence project seeded",
        )

    component = db.query(ComponentInstance).filter_by(
        tenant_id=tenant_id, project_id=project.id, component_code=definition.code,
    ).first()
    if not component:
        component = ComponentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, project_id=project.id,
            component_definition_id=definition.id, entitlement_id=entitlement.id,
            component_code=definition.code, component_version=definition.version,
            blueprint_ref=definition.default_blueprint_ref, status="ready",
            progress=0.0, health=100.0, current_phase="release_validation",
            limits_consumed_json={}, milestones_json=[], tasks_json=[],
        )
        db.add(component)
        db.flush()
        _release_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            aggregate_type="component_instance", aggregate_id=component.id,
            event_type="release_component.seeded", summary="Contracted release component seeded",
        )
    return {
        "contract_id": contract.id,
        "entitlement_id": entitlement.id,
        "program_id": program.id,
        "project_id": project.id,
        "component_id": component.id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap an assisted-pilot tenant membership")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--subject", required=True, help="Exact OIDC subject for the member")
    parser.add_argument("--email", default="")
    parser.add_argument("--name", default="Initial Member")
    parser.add_argument(
        "--role",
        choices=("owner", "engagement_manager", "operator", "release_validator"),
        default="owner",
    )
    parser.add_argument(
        "--tenant-purpose",
        choices=("assisted_pilot", "release_homologation"),
        default="assisted_pilot",
    )
    parser.add_argument(
        "--seed-release-assets",
        action="store_true",
        help="Seed the release-only contract, entitlement, program, project and contracted component",
    )
    parser.add_argument(
        "--enable-rag-generation",
        action="store_true",
        help="Allow this tenant's retrieved excerpts to be sent to the configured LLM provider",
    )
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    expected_confirmation = (
        "bootstrap release homologation tenant"
        if args.tenant_purpose == "release_homologation"
        else "bootstrap assisted pilot tenant"
    )
    if args.confirm != expected_confirmation:
        raise SystemExit("Invalid confirmation phrase")

    settings = get_settings()
    if args.tenant_purpose == "release_homologation":
        normalized_id = args.tenant_id.casefold()
        if not normalized_id.startswith(("release-", "homologation-")):
            raise SystemExit("Release tenant id must start with release- or homologation-")
        if args.tenant_id == settings.default_tenant_id:
            raise SystemExit("Release tenant must be distinct from the default/customer tenant")
        if args.enable_rag_generation:
            raise SystemExit("Release homologation cannot enable customer RAG generation")
    elif args.seed_release_assets or args.role in {"operator", "release_validator"}:
        raise SystemExit("Release assets and service-account roles are restricted to release_homologation tenants")
    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('asf-pilot-tenant-onboarding', 3))"))
        existing = db.query(Tenant).filter_by(id=args.tenant_id).execution_options(include_all_tenants=True).first()
        active_tenants = (
            db.query(Tenant)
            .filter(Tenant.status != "deleted")
            .filter(~Tenant.id.like("release-%"), ~Tenant.id.like("homologation-%"))
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
            role=args.role,
        )
        membership.role = args.role
        tenant.status = "active"
        tenant.runtime_configuration_json = tenant_runtime_configuration(
            settings,
            tenant.id,
            onboarding_status="accepted",
            rag_generation_enabled=args.enable_rag_generation,
        )
        if args.tenant_purpose == "release_homologation":
            tenant.runtime_configuration_json.update({
                "tenant_purpose": "release_homologation",
                "environment": "homologation",
                "customer_data_allowed": False,
                "synthetic_data_only": True,
            })
        tenant.retention_policy_json = {"backups_days": 7, "rpo_hours": 24, "rto_target_hours": 4}
        event_payload = {
            "summary": (
                "Release homologation tenant membership bootstrapped"
                if args.tenant_purpose == "release_homologation"
                else "Assisted-pilot tenant and operator bootstrapped"
            ),
            "membership_id": membership.id,
            "role": membership.role,
            "tenant_purpose": args.tenant_purpose,
            "rag_generation": tenant.runtime_configuration_json["rag_generation"],
        }
        if membership.role != "owner":
            event_payload = {
                "summary": (
                    "Release homologation tenant membership bootstrapped"
                    if args.tenant_purpose == "release_homologation"
                    else "Assisted-pilot tenant membership bootstrapped"
                ),
                "membership_id": membership.id,
                "role": membership.role,
                "tenant_purpose": args.tenant_purpose,
                "rag_generation": tenant.runtime_configuration_json["rag_generation"],
            }
        append_ledger_event(
            db,
            tenant_id=tenant.id,
            aggregate_type="tenant",
            aggregate_id=tenant.id,
            event_type=(
                "release_tenant.bootstrapped"
                if args.tenant_purpose == "release_homologation"
                else "tenant.bootstrapped"
            ),
            actor_user_id=user.id,
            payload=event_payload,
            idempotency_key=f"tenant-bootstrap:{tenant.id}:{user.subject}",
        )
        release_assets = {}
        if args.seed_release_assets:
            release_assets = seed_release_assets(
                db, tenant_id=tenant.id, actor_user_id=user.id,
            )
        db.commit()
        asset_summary = " ".join(f"{key}={value}" for key, value in sorted(release_assets.items()))
        print(
            f"tenant_id={tenant.id} user_id={user.id} membership_id={membership.id} "
            f"role={membership.role} purpose={args.tenant_purpose} {asset_summary}".rstrip()
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
