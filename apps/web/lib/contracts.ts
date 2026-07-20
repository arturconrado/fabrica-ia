import type { components } from "@/lib/api.generated";


type Schemas = components["schemas"];
export type Provenance = Schemas["MetricValue"]["provenance"];
export type MetricValue = Schemas["MetricValue"];
export type NextAction = Schemas["NextAction"];
export type TenantSummary = Schemas["TenantSummary"];
export type PortfolioResponse = Schemas["PortfolioResponse"];

export type LedgerEvent = {
  id: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  tenant_sequence: number;
  payload_json: { summary?: string; [key: string]: unknown };
  created_at: string;
};

export type OperatorOverview = Omit<Schemas["OverviewResponse"], "recent_events"> & { recent_events: LedgerEvent[] };

export type GamificationEvent = { id: string; event_type: string; points: number; reason: string; ledger_record_id: string; created_at: string };
export type GamificationProfile = Omit<Schemas["GamificationProfileResponse"], "recent_events"> & { recent_events: GamificationEvent[] };
export type ReviewInboxItem = Schemas["ReviewInboxItem"];
export type ReviewInbox = Schemas["ReviewInboxResponse"];
export type WorkflowTopology = Schemas["WorkflowTopologyResponse"];

export type ServiceOffering = {
  id: string;
  code: string;
  name: string;
  category: string;
  description: string;
  status: string;
  version_id: string;
  version: string;
  duration_label: string;
  cadence: string;
  checksum: string;
  definition: {
    component_codes?: string[];
    stages?: string[];
    deliverables?: string[];
    definition_of_done?: string[];
  };
};

export type ServicePortfolioClient = {
  tenant_id: string;
  tenant_name: string;
  role: string;
  active_engagements: number;
  contracted_offerings: number;
  deliverables_due: number;
  deliverables_at_risk: number;
  deliverables_in_review: number;
  deliverables_completed: number;
  active_work_items: number;
  pending_approvals: number;
  active_runs: number;
  model_cost_usd: number | null;
  latest_hrs: number | null;
  next_commitment: { kind: string; title: string; resource_id: string; due_at: string; href: string } | null;
};

export type ServicePortfolio = { generated_at: string; clients: ServicePortfolioClient[] };

export type Engagement = {
  id: string;
  tenant_id: string;
  contract_id: string;
  offering_version_id: string;
  program_id: string | null;
  name: string;
  description: string;
  sponsor: string;
  status: string;
  start_date: string;
  target_end_date: string;
  health_score: number | null;
  record_version: number;
  created_at: string;
  offering?: ServiceOffering & { definition: ServiceOffering["definition"] };
  latest_plan?: EngagementPlan | null;
  counts?: { workstreams: number; deliverables: number; work_items: number; agent_assignments: number; deliverables_completed: number };
};

export type EngagementPlan = {
  id: string;
  version: number;
  status: string;
  plan_json: {
    summary?: string;
    objectives?: string[];
    stages?: string[];
    workstreams?: Array<{ key: string; name: string; objective: string }>;
    deliverables?: Array<{ template_key: string; title: string; description: string; workstream_key: string; due_offset_days: number }>;
    risks?: string[];
    next_actions?: string[];
  };
  model_call_id: string | null;
  approved_at: string | null;
  created_at: string;
};

export type WorkItem = {
  id: string;
  tenant_id?: string;
  tenant_name?: string;
  engagement_id: string;
  engagement_name?: string;
  deliverable_id?: string | null;
  title: string;
  description?: string;
  status: string;
  priority: string;
  due_at: string | null;
  blocked_reason: string;
  record_version: number;
  wip_override?: boolean;
};

export type ServiceDeliverable = {
  id: string;
  engagement_id: string;
  workstream_id: string | null;
  template_key: string;
  title: string;
  description: string;
  definition_of_done_json: string[];
  acceptance_criteria_json: string[];
  audience: string;
  status: string;
  due_at: string | null;
  current_revision: number;
  record_version: number;
  run_id: string | null;
  homologation_package_id: string | null;
  engagement?: { id: string; name: string } | null;
  offering?: { code: string; name: string } | null;
  latest_revision?: DeliverableRevision | null;
  approval?: { id: string; status: string; comments: string } | null;
  revisions?: DeliverableRevision[];
};

export type OutcomeMetric = {
  id: string;
  engagement_id: string;
  name: string;
  unit: string;
  baseline_value: number | null;
  target_value: number | null;
  current_value: number | null;
  provenance: "real" | "calculated" | "estimated";
  source_refs_json: string[];
  observed_at: string | null;
  record_version: number;
};

export type DeliverableRevision = {
  id: string;
  revision: number;
  status: string;
  content_json: { title?: string; executive_summary?: string; content_markdown?: string; evidence_claims?: string[]; risks?: string[]; next_actions?: string[] };
  artifact_refs_json: string[];
  evidence_refs_json: string[];
  model_call_id: string | null;
  created_at: string;
};

export type Capacity = {
  generated_at: string;
  global_limit: number;
  active_total: number;
  available_slots: number;
  over_capacity: boolean;
  per_tenant_limit: number;
  tenants: Array<{ tenant_id: string; tenant_name: string; active: number; queued: number; blocked: number; limit: number; over_capacity: boolean }>;
  conflicts: Array<{ type: string; tenant_name?: string; active: number; limit: number }>;
};

export type AgentCatalog = {
  definitions: Array<{ id: string; code: string; name: string; purpose: string; scope: string; status: string }>;
  versions: Array<{ id: string; agent_definition_id: string; version: string; status: string; model_role: string; allowed_tools_json: string[]; checksum: string }>;
  gaps: Array<{ id: string; engagement_id: string | null; title: string; capability: string; description: string; gap_type: string; status: string; created_at: string }>;
  candidates: Array<{ id: string; capability_gap_id: string; status: string; proposed_definition_json: { name?: string; purpose?: string; allowed_tools?: string[] }; model_call_id: string | null; created_at: string }>;
  evaluations: Array<{ id: string; candidate_id: string; status: string; repetitions: number; checks_json: { [key: string]: boolean }; metrics_json: { schema_valid_rate?: number } }>;
  assignments: Array<{ id: string; engagement_id: string; status: string; ai_budget_usd: number; agent?: { code: string; name: string; version: string } | null }>;
};
