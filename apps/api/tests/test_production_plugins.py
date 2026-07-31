import uuid
from pathlib import Path

import yaml
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.agents.ai_native_executor import AINativeWorkflowExecutor
from app.api.routes_runs import _validation_manifest
from app.auth.dependencies import ensure_tenant
from app.models import (
    AcceptanceCriterion,
    AgentEvent,
    Base,
    ExecutionUnit,
    FileChange,
    PluginInvocation,
    Project,
    Requirement,
    RequirementTrace,
    TestReport as ReportModel,
    WorkflowRun,
)
from app.plugins.cavekit import CAVEKIT_SOURCE_REVISION, CAVEKIT_VERSION, CavekitPolicy
from app.plugins.ponytail import PONYTAIL_SOURCE_REVISION, PONYTAIL_VERSION, PonytailPolicy
from app.plugins.runtime import FactoryPluginRuntime
from app.quality.ai_native_quality import AINativeQualityEvaluator
from app.workflow.cost_policy_compiler import compile_cost_policy_workflow


def _workflow_file(name: str) -> Path:
    """Resolve repository workflows both on the host and in the API image."""
    for directory in (
        Path(__file__).resolve().parents[1] / "workflows",
        Path(__file__).resolve().parents[3] / "workflows"
        if len(Path(__file__).resolve().parents) > 3
        else Path("/__missing_repository_root__"),
    ):
        path = directory / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"Workflow fixture is unavailable: {name}")


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _run(db, *, tenant_id: str = "client-a", run_id: str = "run-plugins") -> WorkflowRun:
    ensure_tenant(db, tenant_id, tenant_id)
    project = Project(id=f"project-{run_id}", tenant_id=tenant_id, name=f"Project {run_id}")
    run = WorkflowRun(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project.id,
        workflow_id="software_factory_ai_native_v2",
        generation_mode="ai_native_v2",
        executor_protocol_version="segmented-output-v1",
        trace_id=f"trace-{run_id}",
        demand="Build only the approved tenant product.",
        status="running",
        current_node="Engineer",
        current_phase="implementation",
        ai_budget_usd=15,
        context_manifest_json={"workflow_version": "2.13.2"},
    )
    db.add_all([project, run])
    db.commit()
    return run


def test_pinned_manifests_and_ponytail_safety_boundary_are_stable():
    ponytail = PonytailPolicy.manifest()
    cavekit = CavekitPolicy.manifest()
    assert (ponytail["version"], ponytail["source_revision"]) == (
        PONYTAIL_VERSION,
        PONYTAIL_SOURCE_REVISION,
    )
    assert (cavekit["version"], cavekit["source_revision"]) == (
        CAVEKIT_VERSION,
        CAVEKIT_SOURCE_REVISION,
    )
    assert ponytail["automatic_updates"] is False
    assert ponytail["version"] == "4.8.4"
    assert ponytail["source_revision"] == "16f29800fd2681bdf24f3eb4ccffe38be3baec6b"
    assert ponytail["manifest_sha256"] == "143f43998b59790e7c1cfc21600bb16cbafe81b37ae238db1fe2a0f7ef75613e"
    assert ponytail["source_url"] == "https://github.com/DietrichGebert/ponytail"
    assert ponytail["codex_plugin_selector"] == "ponytail@ponytail"
    assert ponytail["codex_default_mode"] == "full"
    assert PonytailPolicy.mode_for_node({"id": "Security Engineer"}) == "full"
    assert cavekit["automatic_updates"] is False
    assert cavekit["manifest_sha256"] == "ff7cdabb1881492647ca9da90dbaa7488dcada0bcac579306b0250ad92f58d89"
    assert "backprop" not in CavekitPolicy.stages_for_action(
        {"cavekit_stages": ["check", "backprop", "caveman"]}, "execute:1"
    )
    assert "backprop" in CavekitPolicy.stages_for_action(
        {"cavekit_stages": ["check", "backprop", "caveman"]}, "observe:2"
    )
    assert "deepen" not in CavekitPolicy.stages_for_action(
        {"cavekit_stages": ["check", "deepen", "caveman"]}, "execute:1"
    )
    assert CavekitPolicy.stages_for_action({"cavekit_stages": ["deepen"]}, "deepen") == ["deepen"]
    instructions = PonytailPolicy.instructions("full")
    for protected in ("tenant isolation", "accessibility", "HRS", "human approval"):
        assert protected in instructions
    assert "arbitrary shell" not in instructions.casefold()


def test_v2132_compiler_activates_every_pinned_capability_without_touching_v2131():
    policy_path = _workflow_file("software_factory_ai_native_v2_13_2_policy.yaml")
    candidate = yaml.safe_load(compile_cost_policy_workflow(policy_path=policy_path))["graph"]
    assert candidate["version"] == "2.13.2"
    assert candidate["execution"]["plugins"]["mandatory"] is True
    agents = [node for node in candidate["nodes"] if node["type"] == "agent"]
    assert agents and all(node["ponytail_enabled"] is True for node in agents)
    assert {node["ponytail_mode"] for node in agents} == {"full"}
    ponytail_commands = {command for node in agents for command in node.get("ponytail_commands", [])}
    cavekit_stages = {stage for node in agents for stage in node.get("cavekit_stages", [])}
    assert ponytail_commands == {"activate", "instructions", "review", "audit", "debt", "gain", "help"}
    assert cavekit_stages == {"grill", "spec", "research", "review", "build", "check", "backprop", "deepen", "caveman"}


def test_v214_compiler_preserves_plugins_and_binds_code_ownership_and_evaluation():
    policy_path = _workflow_file("software_factory_ai_native_v2_14_policy.yaml")
    candidate = yaml.safe_load(compile_cost_policy_workflow(policy_path=policy_path))["graph"]
    assert candidate["version"] == "2.14.0"
    assert candidate["execution"]["plugins"]["mandatory"] is True
    assert candidate["execution"]["candidate_evaluation"] == {
        "baseline_workflow_version": "2.13.2",
        "dataset": "homologation/cases/portfolio-v2/realistic-agentic-journeys.json",
        "repetitions": 3,
        "promotion": "human_only",
        "max_cost_token_regression_ratio": 1.2,
    }
    agents = {node["id"]: node for node in candidate["nodes"] if node["type"] == "agent"}
    assert len(agents) == 18
    assert {node["ponytail_mode"] for node in agents.values()} == {"full"}
    expected_owners = {
        "Architect",
        "Data Architect",
        "API Contract Engineer",
        "Engineer",
        "QA Engineer",
        "Security Engineer",
        "DevOps Engineer",
    }
    assert {
        node_id for node_id, node in agents.items()
        if "write_workspace" in node.get("allowed_tools", [])
    } == expected_owners
    assert agents["Code Reviewer"].get("workspace_ownership", []) == []
    assert agents["Visual QA Agent"].get("workspace_ownership", []) == []
    assert agents["Accessibility QA Agent"].get("workspace_ownership", []) == []
    edges = {
        (edge["from"], edge["to"], edge["condition"]): edge
        for edge in candidate["edges"]
    }
    assert edges[("QA Engineer", "QA Engineer", "tests_invalid")]["max_iterations"] == 1
    for observer in ("Visual QA Agent", "Accessibility QA Agent", "Security Engineer"):
        assert edges[(observer, "Engineer", "blocked")]["max_iterations"] == 2


def test_plugin_runtime_is_idempotent_audited_and_terminally_complete():
    engine, db = _session()
    try:
        run = _run(db)
        runtime = FactoryPluginRuntime()
        node = {
            "id": "Engineer",
            "phase": "implementation",
            "ponytail_enabled": True,
            "ponytail_mode": "full",
            "ponytail_commands": ["activate", "instructions", "debt"],
            "cavekit_stages": ["build", "caveman"],
        }
        first = runtime.prompt_for_node(db, run=run, node=node, iteration=1, action="plan")
        second = runtime.prompt_for_node(db, run=run, node=node, iteration=1, action="plan")
        assert first == second
        assert db.query(PluginInvocation).filter_by(tenant_id=run.tenant_id, run_id=run.id).count() == 5
        pending_cavekit = db.query(PluginInvocation).filter_by(
            tenant_id=run.tenant_id,
            run_id=run.id,
            plugin_name="cavekit",
        ).all()
        assert {row.command for row in pending_cavekit} == {"build", "caveman"}
        assert {row.status for row in pending_cavekit} == {"registered"}
        assert _validation_manifest(db, run)["invariants"]["cavekit_stage_evidence_complete"] is False
        runtime.finish_cavekit_stages(
            db,
            run=run,
            node=node,
            iteration=1,
            action="plan",
            status="completed",
            evidence={
                "evidence_type": "validated_test_plan",
                "step_execution_id": "step-plan",
                "model_call_id": "call-plan",
                "output_hash": "plan-hash",
            },
        )
        terminal_events = db.query(AgentEvent).filter_by(
            tenant_id=run.tenant_id,
            run_id=run.id,
            event_type="plugin.cavekit.build",
        ).count()
        runtime.finish_cavekit_stages(
            db,
            run=run,
            node=node,
            iteration=1,
            action="plan",
            status="completed",
            evidence={"evidence_type": "ignored-replay", "step_execution_id": "step-plan"},
        )
        assert db.query(AgentEvent).filter_by(
            tenant_id=run.tenant_id,
            run_id=run.id,
            event_type="plugin.cavekit.build",
        ).count() == terminal_events
        runtime.record_result(
            db,
            run=run,
            plugin_name="ponytail",
            command="debt",
            node_id="Engineer",
            iteration=1,
            status="completed",
            output={"artifact_id": "artifact-debt", "marker_count": 0},
        )
        runtime.ensure_mission_coverage(db, run=run)
        db.commit()
        rows = db.query(PluginInvocation).filter_by(tenant_id=run.tenant_id, run_id=run.id).all()
        required = {
            "ponytail": {"activate", "instructions", "review", "audit", "debt", "gain", "help"},
            "cavekit": {"grill", "spec", "research", "review", "build", "check", "backprop", "deepen", "caveman"},
        }
        for plugin, commands in required.items():
            terminal = {
                row.command
                for row in rows
                if row.plugin_name == plugin and row.status in {"completed", "not_applicable"}
            }
            assert terminal == commands
        assert all(row.invocation_key and row.input_hash and row.output_hash for row in rows)
        assert all(
            (row.metadata_json or {}).get("evidence_type")
            for row in rows
            if row.plugin_name == "cavekit" and row.status == "completed"
        )
        assert _validation_manifest(db, run)["invariants"]["cavekit_stage_evidence_complete"] is True
    finally:
        db.close()
        engine.dispose()


def test_cavekit_failure_requires_evidenced_recovery_for_validation():
    engine, db = _session()
    try:
        run = _run(db, run_id="run-cavekit-retry")
        runtime = FactoryPluginRuntime()
        node = {
            "id": "Architect",
            "phase": "architecture",
            "cavekit_stages": ["spec", "review", "caveman"],
        }
        runtime.prompt_for_node(db, run=run, node=node, iteration=1, action="plan:1")
        runtime.finish_cavekit_stages(
            db,
            run=run,
            node=node,
            iteration=1,
            action="plan:1",
            status="completed",
            evidence={"evidence_type": "validated_plan", "step_execution_id": "step-plan"},
        )
        runtime.prompt_for_node(db, run=run, node=node, iteration=1, action="execute:1")
        runtime.finish_cavekit_stages(
            db,
            run=run,
            node=node,
            iteration=1,
            action="execute:1",
            status="failed",
            evidence={"evidence_type": "agent_step_failure", "step_execution_id": "step-1"},
            error="schema validation failed",
        )
        runtime.ensure_mission_coverage(db, run=run)
        db.commit()
        assert _validation_manifest(db, run)["invariants"]["cavekit_stage_evidence_complete"] is False

        runtime.prompt_for_node(db, run=run, node=node, iteration=1, action="execute:2")
        runtime.finish_cavekit_stages(
            db,
            run=run,
            node=node,
            iteration=1,
            action="execute:2",
            status="completed",
            evidence={
                "evidence_type": "validated_agent_step",
                "step_execution_id": "step-2",
                "model_call_id": "call-2",
            },
        )
        db.commit()
        assert _validation_manifest(db, run)["invariants"]["cavekit_stage_evidence_complete"] is True
    finally:
        db.close()
        engine.dispose()


def test_plugin_runtime_rejects_unpinned_or_non_fail_closed_manifest():
    runtime = FactoryPluginRuntime()
    execution = {
        "plugins": {
            "mandatory": True,
            "fail_closed": True,
            "automatic_updates": False,
            "ponytail": {"version": PONYTAIL_VERSION, "source_revision": PONYTAIL_SOURCE_REVISION},
            "cavekit": {"version": CAVEKIT_VERSION, "source_revision": CAVEKIT_SOURCE_REVISION},
        }
    }
    runtime.validate_execution_manifest(execution)
    execution["plugins"]["ponytail"]["source_revision"] = "unreviewed"
    try:
        runtime.validate_execution_manifest(execution)
    except ValueError as exc:
        assert "revision" in str(exc)
    else:
        raise AssertionError("an unreviewed plugin revision must fail closed")


def test_all_v2132_roles_finish_every_cavekit_stage_with_persisted_evidence():
    engine, db = _session()
    try:
        run = _run(db, run_id="run-cavekit-policy")
        policy_path = _workflow_file("software_factory_ai_native_v2_13_2_policy.yaml")
        graph = yaml.safe_load(compile_cost_policy_workflow(policy_path=policy_path))["graph"]
        runtime = FactoryPluginRuntime()
        agents = [node for node in graph["nodes"] if node["type"] == "agent"]
        for index, node in enumerate(agents, start=1):
            regular_stages = [stage for stage in node["cavekit_stages"] if stage not in {"backprop", "deepen"}]
            if regular_stages:
                action = "execute:1"
                runtime.prompt_for_node(db, run=run, node=node, iteration=1, action=action)
                runtime.finish_cavekit_stages(
                    db,
                    run=run,
                    node=node,
                    iteration=1,
                    action=action,
                    stages=regular_stages,
                    status="completed",
                    evidence={
                        "evidence_type": "validated_agent_step",
                        "step_execution_id": f"step-{index}",
                        "model_call_id": f"call-{index}",
                    },
                )
            if "backprop" in node["cavekit_stages"]:
                action = "observe:2"
                runtime.prompt_for_node(db, run=run, node=node, iteration=1, action=action)
                runtime.finish_cavekit_stages(
                    db,
                    run=run,
                    node=node,
                    iteration=1,
                    action=action,
                    stages=["backprop"],
                    status="not_applicable",
                    evidence={"reason": "sandbox suites passed", "test_report_ids": ["report-green"]},
                )
            if "deepen" in node["cavekit_stages"]:
                action = "deepen"
                deepen_node = {**node, "cavekit_stages": ["deepen"]}
                runtime.prompt_for_node(db, run=run, node=deepen_node, iteration=1, action=action)
                runtime.finish_cavekit_stages(
                    db,
                    run=run,
                    node=deepen_node,
                    iteration=1,
                    action=action,
                    status="completed",
                    evidence={
                        "evidence_type": "post_gate_deepening",
                        "quality_gate_ids": ["gate-green"],
                    },
                )
        runtime.ensure_mission_coverage(db, run=run)
        db.commit()
        cavekit_rows = db.query(PluginInvocation).filter_by(run_id=run.id, plugin_name="cavekit").all()
        assert {row.command for row in cavekit_rows} == {
            "grill", "spec", "research", "review", "build", "check", "backprop", "deepen", "caveman"
        }
        assert all(row.status in {"completed", "not_applicable"} for row in cavekit_rows)
        assert all(row.output_hash for row in cavekit_rows)
        assert _validation_manifest(db, run)["invariants"]["cavekit_stage_evidence_complete"] is True
    finally:
        db.close()
        engine.dispose()


def test_v2132_traceability_requires_exact_manifest_file_and_passing_suite():
    engine, db = _session()
    try:
        run = _run(db, run_id="run-trace")
        requirement = Requirement(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            requirement_id="REQ-001",
            title="Create contract",
            description="Persist a tenant contract.",
            priority="P0",
        )
        criterion = AcceptanceCriterion(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            criterion_id="AC-001",
            requirement_id="REQ-001",
            title="Contract accepted",
            gherkin="Given valid data When created Then return 201",
            priority="P0",
        )
        unit = ExecutionUnit(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Engineer",
            phase="implementation",
            iteration=1,
            unit_key="contract-api",
            unit_type="file_batch",
            strategy="segmented_workspace",
            action="execute",
            order_index=1,
            targets_json=["generated_app/backend/app/main.py"],
            status="completed",
            context_manifest_json={
                "requirement_refs": ["REQ-001"],
                "invariant_refs": ["INV-tenant-contract"],
                "verification_tests": ["test_create_contract_returns_201"],
            },
        )
        change = FileChange(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Engineer",
            file_path="generated_app/backend/app/main.py",
            change_type="created",
            after_content="def create_contract():\n    return 201\n",
        )
        report = ReportModel(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            run_id=run.id,
            sandbox_execution_id="sandbox-1",
            command="python -m pytest generated_app/backend/tests",
            status="passed",
            passed_count=1,
        )
        db.add_all([requirement, criterion, unit, change, report])
        db.commit()

        AINativeWorkflowExecutor()._build_traceability(db, run)
        db.commit()

        trace = db.query(RequirementTrace).filter_by(run_id=run.id).one()
        assert trace.provenance == "verified_contract"
        assert trace.test_report_id == report.id
        assert trace.criterion_ids_json == ["AC-001"]
        assert trace.invariant_ids_json == ["INV-tenant-contract"]
        assert {"REQ-001", "AC-001", "INV-tenant-contract", "test_create_contract_returns_201"}.issubset(
            set(change.spec_refs_json)
        )
        assert AINativeQualityEvaluator._verified_contract_traceability(db, run) is True
    finally:
        db.close()
        engine.dispose()


def test_ponytail_debt_is_deterministic_and_never_infers_unmarked_debt():
    items = PonytailPolicy.scan_debt(
        [
            ("generated_app/backend/app/main.py", "# ponytail: in-memory store; upgrade when records exceed 1000\n"),
            ("generated_app/frontend/app/page.tsx", "export default function Page() { return null; }\n"),
        ]
    )
    assert len(items) == 1
    assert items[0].path.endswith("main.py")
    assert items[0].has_trigger is True
    markdown = PonytailPolicy.debt_markdown(items)
    assert "Proveniência: varredura determinística" in markdown
    assert "1 marcadores; 0 sem gatilho" in markdown
