"""RLS-safe aggregate technical metrics for the runtime role.

Revision ID: 0013_aggregate_technical_metrics
Revises: 0012_llmops_slo
Create Date: 2026-07-20 19:10:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013_aggregate_technical_metrics"
down_revision: Union[str, None] = "0012_llmops_slo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FUNCTION_NAME = "public.asf_aggregate_technical_metrics"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # The runtime role must not bypass RLS. This tightly scoped, owner-executed
    # function is the only cross-tenant read surface and returns aggregate
    # technical counters only: no tenant, run, prompt, artifact or file data.
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {FUNCTION_NAME}()
            RETURNS jsonb
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $function$
            SELECT jsonb_build_object(
                'workflow_runs_by_status', COALESCE((
                    SELECT jsonb_object_agg(status_key, row_count)
                    FROM (
                        SELECT COALESCE(status, 'unknown') AS status_key, COUNT(*) AS row_count
                        FROM public.workflow_runs
                        GROUP BY COALESCE(status, 'unknown')
                    ) AS grouped
                ), '{{}}'::jsonb),
                'execution_units_by_status', COALESCE((
                    SELECT jsonb_object_agg(status_key, row_count)
                    FROM (
                        SELECT COALESCE(status, 'unknown') AS status_key, COUNT(*) AS row_count
                        FROM public.execution_units
                        GROUP BY COALESCE(status, 'unknown')
                    ) AS grouped
                ), '{{}}'::jsonb),
                'model_calls_by_status', COALESCE((
                    SELECT jsonb_object_agg(status_key, row_count)
                    FROM (
                        SELECT COALESCE(status, 'unknown') AS status_key, COUNT(*) AS row_count
                        FROM public.model_calls
                        GROUP BY COALESCE(status, 'unknown')
                    ) AS grouped
                ), '{{}}'::jsonb),
                'quality_gates_by_status', COALESCE((
                    SELECT jsonb_object_agg(status_key, row_count)
                    FROM (
                        SELECT COALESCE(status, 'unknown') AS status_key, COUNT(*) AS row_count
                        FROM public.quality_gates
                        GROUP BY COALESCE(status, 'unknown')
                    ) AS grouped
                ), '{{}}'::jsonb),
                'cache_eligible_tokens', COALESCE((SELECT SUM(cache_eligible_tokens) FROM public.model_calls), 0),
                'cache_write_tokens', COALESCE((SELECT SUM(cache_write_tokens) FROM public.model_calls), 0),
                'cache_read_tokens', COALESCE((SELECT SUM(cache_read_tokens) FROM public.model_calls), 0),
                'cache_savings_usd', COALESCE((SELECT SUM(cache_savings_usd) FROM public.model_calls), 0),
                'prompt_tokens', COALESCE((SELECT SUM(prompt_tokens) FROM public.model_calls), 0),
                'completion_tokens', COALESCE((SELECT SUM(completion_tokens) FROM public.model_calls), 0),
                'model_cost_usd', COALESCE((SELECT SUM(estimated_cost_usd) FROM public.model_calls), 0),
                'model_call_errors', COALESCE((
                    SELECT COUNT(*) FROM public.model_calls WHERE status NOT IN ('success', 'completed')
                ), 0),
                'model_call_timeouts', COALESCE((
                    SELECT COUNT(*) FROM public.model_calls WHERE lower(COALESCE(error, '')) LIKE '%timeout%'
                ), 0),
                'schema_repairs', COALESCE((
                    SELECT COUNT(*) FROM public.model_calls WHERE retry_classification = 'schema_repair'
                ), 0),
                'provider_retries', COALESCE((
                    SELECT COUNT(*) FROM public.model_calls WHERE attempt_number > 1
                ), 0),
                'checkpoint_recoveries', COALESCE((
                    SELECT COUNT(*) FROM public.agent_events WHERE event_type = 'agent.checkpoint_recovered'
                ), 0),
                'rework_events', COALESCE((
                    SELECT COUNT(*) FROM public.agent_events WHERE lower(event_type) LIKE '%rework%'
                ), 0),
                'sandbox_timeouts', COALESCE((
                    SELECT COUNT(*) FROM public.sandbox_executions WHERE timed_out
                ), 0),
                'hrs_average', COALESCE((
                    SELECT AVG(homologation_readiness_score)
                    FROM public.workflow_runs
                    WHERE homologation_readiness_score > 0
                ), 0),
                'run_duration_p95_seconds', COALESCE((
                    SELECT percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at))
                    )
                    FROM public.workflow_runs
                    WHERE finished_at IS NOT NULL AND finished_at >= started_at
                ), 0),
                'node_duration_p95_seconds', COALESCE((
                    SELECT percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at))
                    )
                    FROM public.workflow_node_states
                    WHERE finished_at IS NOT NULL AND finished_at >= started_at
                ), 0),
                'unit_duration_p95_seconds', COALESCE((
                    SELECT percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at))
                    )
                    FROM public.execution_units
                    WHERE finished_at IS NOT NULL AND started_at IS NOT NULL AND finished_at >= started_at
                ), 0),
                'model_duration_p95_seconds', COALESCE((
                    SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_seconds)
                    FROM public.model_calls
                    WHERE duration_seconds >= 0
                ), 0)
            )
            $function$
            """
        )
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}() FROM PUBLIC")
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'factory_app') THEN "
            f"GRANT EXECUTE ON FUNCTION {FUNCTION_NAME}() TO factory_app; "
            "END IF; END $$;"
        )
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}()")
