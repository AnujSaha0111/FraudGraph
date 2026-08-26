import type {
  CaseDetail,
  EntityRisk,
  EvidenceResponse,
  GraphResponse,
  QueueResponse,
  RiskRecord,
} from "../api/types";

export const queue: QueueResponse = {
  transactions: [
    { transaction_id: 2987004, model_version: "fraud_xgb_v1-9e2978c", risk_score: 0.97, risk_band: "CRITICAL", has_evidence: true },
    { transaction_id: 2987005, model_version: "fraud_xgb_v1-9e2978c", risk_score: 0.65, risk_band: "MEDIUM", has_evidence: false },
  ],
  count: 2,
};

export const risk: RiskRecord = {
  transaction_id: 2987004,
  risk_score: 0.9123,
  risk_band: "CRITICAL",
  model_version: "fraud_xgb_v1-9e2978c",
};

export const explanation = {
  ...risk,
  top_features: [
    { feature: "V12", value: 1.23, contribution: 0.31, direction: "positive" as const, abs_rank: 1 },
    { feature: "amt_z_card", value: 4.2, contribution: -0.05, direction: "negative" as const, abs_rank: 2 },
  ],
};

export const evidence: EvidenceResponse = {
  transaction_id: 2987004,
  model_risk: { risk_score: 0.9123, risk_band: "CRITICAL", model_version: "fraud_xgb_v1-9e2978c" },
  evidence_engine_version: "v1",
  graph_version: "v1",
  params_hash: "abcdef0123456789",
  evidence: [
    {
      evidence_id: "11111111-2222-3333-4444-555555555555",
      transaction_id: 2987004,
      evidence_type: "AMOUNT_DEVIATION",
      title: "Amount deviation for card",
      description: "+3.1σ above prior mean.",
      details: { reference_entity: "card:12345", z_score: 3.1, metric: "welford_z" },
      severity: "high",
      provenance: { source_table: "production_features", source_row_ids: [2987004], code_version: "v1" },
      evidence_hash: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
      generated_at: "2026-08-23T10:00:00",
    },
    {
      evidence_id: "66666666-7777-8888-9999-000000000000",
      transaction_id: 2987004,
      evidence_type: "NO_RELATIONAL_EVIDENCE",
      title: "No qualifying relational evidence",
      description: "No rule fired.",
      details: {},
      severity: "info",
      evidence_hash: "cafecafecafecafecafecafecafecafecafecafecafecafecafecafecafecafe",
      generated_at: "2026-08-23T10:00:00",
    },
  ],
};

export const graph: GraphResponse = {
  transaction_id: 2987004,
  graph_version: "v1",
  params_hash: "abcdef0123456789",
  parameters: { back_s: 1209600, fwd_s: 172800, hub_degree_max: 1000, neighbor_cap: 200, depth: 1, graph_version: "v1" },
  seed: { transaction_id: 2987004, ts: 12876275, risk_score: 0.9123, model_version: "fraud_xgb_v1-9e2978c" },
  entities: [
    { entity_type: "ADDRESS", entity_key: "315" },
  ],
  transactions: [
    { transaction_id: 2987004, ts: 12876275 },
    { transaction_id: 2987101, ts: 12880000 },
  ],
  edges: [
    { source: "txn:2987004", target: "ADDRESS:315", relationship_type: "HAS_ENTITY", transaction_id: 2987004, ts: 12876275 },
    { source: "txn:2987101", target: "ADDRESS:315", relationship_type: "HAS_ENTITY", transaction_id: 2987101, ts: 12880000 },
  ],
  nodes: [
    { id: "txn:2987004", type: "TRANSACTION", transaction_id: 2987004, ts: 12876275, is_seed: true, risk_score: 0.9123 },
    { id: "txn:2987101", type: "TRANSACTION", transaction_id: 2987101, ts: 12880000, is_seed: false, risk_score: null },
    { id: "ADDRESS:315", type: "ADDRESS", entity_key: "315", in_seed_component: true },
  ],
  community: {
    members: [2987004, 2987101],
    member_count: 2,
    entity_members: [{ entity_type: "ADDRESS", entity_key: "315" }],
    summary: {
      transaction_count: 2, entity_count: 1, entity_type_counts: { ADDRESS: 1 },
      time_span_hours: 1.03, hub_pruned_count: 1, max_risk_score: 0.9123,
      seed_component_id: 0, n_components_total: 2,
    },
    all_components: 2,
  },
  pruning: [
    { entity_type: "CARD", entity_key: "999", degree: 4200, pruned: true },
    { entity_type: "ADDRESS", entity_key: "315", degree: 12, pruned: false, original_neighbors_in_window: 3, retained_neighbors: 3, cap_applied: false },
  ],
  temporal_window: { start: 12766675, end: 13049075, back_s: 1209600, fwd_s: 172800 },
  model_risk: { risk_score: 0.9123, note: "model risk separate from graph context" },
  graph_context: {
    connected_transactions: 2, connected_entities: 1,
    community: {
      transaction_count: 2, entity_count: 1, entity_type_counts: { ADDRESS: 1 },
      time_span_hours: 1.03, hub_pruned_count: 1, max_risk_score: 0.9123,
      seed_component_id: 0, n_components_total: 2,
    },
  },
};

export const caseDetail: CaseDetail = {
  case_id: "42",
  transaction_id: 2987004,
  status: "INVESTIGATING",
  title: "Review high score on 2987004",
  actor: "analyst-1",
  created_at: "2026-08-23T09:00:00",
  updated_at: "2026-08-23T09:05:00",
  model_risk: { risk_score: 0.9123, risk_band: "CRITICAL", model_version: "fraud_xgb_v1-9e2978c" },
  evidence: [
    {
      evidence_id: "11111111-2222-3333-4444-555555555555",
      transaction_id: 2987004,
      evidence_type: "AMOUNT_DEVIATION",
      details_json: JSON.stringify({ z_score: 3.1 }),
      evidence_hash: "deadbeef",
      generated_at: "2026-08-23T10:00:00",
    },
  ],
  notes: [{ actor: "analyst-1", note: "amount looks anomalous", created_at: "2026-08-23T09:03:00" }],
  history: [
    { history_id: 1, actor: "analyst-1", action: "CREATED", prev_status: null, new_status: "NEW", details: {}, created_at: "2026-08-23T09:00:00" },
    { history_id: 2, actor: "analyst-1", action: "STATUS_CHANGED", prev_status: "NEW", new_status: "INVESTIGATING", details: {}, created_at: "2026-08-23T09:05:00" },
  ],
  decisions: [],
  label: null,
};

export const entityRiskEmpty: EntityRisk = {
  entity_type: "ADDRESS",
  entity_key: "315",
  as_of_ts: 12876275,
  min_label_lag_days: 7,
  eligible_boundary: "2018-04-22T00:44:35",
  entity_fraud_count: 0,
  entity_total_labeled_count: 0,
  fraud_rate: null,
  computed_at: "2026-08-23T10:00:00",
  note: "delayed investigation context; NOT a model feature",
};
