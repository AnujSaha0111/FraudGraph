// API response types — mirror the FastAPI contracts exactly. Sources: app/routers/{risk,evidence,graph,cases,transactions,health}.py

export type RiskBand = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export const BANDS: RiskBand[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

export interface Health {
  status: string;
  service: string;
  version: string;
  env: string;
  storage: "ok" | "degraded" | "uninitialized" | "unavailable";
}

export interface QueueItem {
  transaction_id: number;
  model_version: string | null;
  risk_score: number;
  risk_band: RiskBand;
  has_evidence: boolean;
}

export interface QueueResponse {
  transactions: QueueItem[];
  count: number;
}

export interface RiskRecord {
  transaction_id: number;
  risk_score: number;
  risk_band: RiskBand;
  model_version: string;
}

export interface TopFeature {
  feature: string;
  value: number | null;
  contribution: number;
  direction: "positive" | "negative" | "neutral";
  abs_rank: number | null;
}

export interface Explanation extends RiskRecord {
  top_features: TopFeature[];
}

export type EvidenceType =
  | "NEW_PAIRING"
  | "AMOUNT_DEVIATION"
  | "UNUSUAL_HOUR"
  | "VELOCITY_BURST"
  | "SHARED_DEVICE_LINK"
  | "COMMUNITY_STATS"
  | "CONNECTED_HIGH_RISK"
  | "NO_RELATIONAL_EVIDENCE";

export interface Provenance {
  source_table: string;
  source_row_ids: number[];
  code_version: string;
}

export interface EvidenceRecord {
  evidence_id: string;
  transaction_id: number;
  evidence_type: EvidenceType;
  title: string;
  description: string;
  details: Record<string, unknown>;
  severity: string;
  provenance?: Provenance;
  evidence_hash: string;
  generated_at: string | null;
}

export interface EvidenceResponse {
  transaction_id: number;
  model_risk: {
    risk_score: number | null;
    risk_band: string | null;
    model_version: string | null;
  };
  evidence: EvidenceRecord[];
  evidence_engine_version: string;
  graph_version: string | null;
  params_hash: string | null;
}

export type EntityType = "CARD" | "DEVICE" | "ADDRESS" | "TRANSACTION";

/** Entity types carried by graph_links / EntityRisk (excludes the
 *  ephemeral TRANSACTION node type). */
export type GraphEntityType = Exclude<EntityType, "TRANSACTION">;

export interface GraphTxnNode {
  id: string; // "txn:{id}"
  type: "TRANSACTION";
  transaction_id: number;
  ts: number;
  is_seed: boolean;
  risk_score: number | null;
}

export interface GraphEntityNode {
  id: string; // "{TYPE}:{key}"
  type: GraphEntityType;
  entity_key: string;
  in_seed_component: boolean;
}

export type GraphNode = GraphTxnNode | GraphEntityNode;

export interface GraphEdge {
  source: string;
  target: string;
  relationship_type: string;
  transaction_id: number;
  ts: number;
}

export interface CommunitySummary {
  transaction_count: number;
  entity_count: number;
  entity_type_counts: Record<string, number>;
  time_span_hours: number;
  hub_pruned_count: number;
  max_risk_score: number;
  seed_component_id: number;
  n_components_total: number;
}

export interface GraphParams {
  back_s: number;
  fwd_s: number;
  hub_degree_max: number;
  neighbor_cap: number;
  depth: number;
  graph_version: string;
}

export interface PruningInfo {
  entity_type: EntityType;
  entity_key: string;
  degree: number;
  pruned: boolean;
  original_neighbors_in_window?: number;
  retained_neighbors?: number;
  cap_applied?: boolean;
}

export interface GraphResponse {
  transaction_id: number;
  graph_version: string;
  params_hash: string;
  parameters: GraphParams;
  seed: { transaction_id: number; ts: number; risk_score: number | null; model_version: string | null };
  entities: { entity_type: EntityType; entity_key: string }[];
  transactions: { transaction_id: number; ts: number }[];
  edges: GraphEdge[];
  nodes: GraphNode[];
  community: {
    members: number[];
    member_count: number;
    entity_members: { entity_type: EntityType; entity_key: string }[];
    summary: CommunitySummary;
    all_components: number;
  };
  pruning: PruningInfo[];
  temporal_window: { start: number; end: number; back_s: number; fwd_s: number };
  model_risk: { risk_score: number | null; note: string };
  graph_context: {
    connected_transactions: number;
    connected_entities: number;
    community: CommunitySummary;
  };
}

export type CaseStatus =
  | "NEW"
  | "INVESTIGATING"
  | "ESCALATED"
  | "CONFIRMED_FRAUD"
  | "FALSE_POSITIVE"
  | "CLOSED";

export interface CaseSummary {
  case_id: string;
  transaction_id: number;
  status: CaseStatus;
  title: string;
  actor: string | null;
  created_at: string | null;
  updated_at: string | null;
  model_risk: { risk_score: number; risk_band: string; model_version: string } | null;
  evidence_count: number;
  latest_decision:
    | { decision_id: string; decision: string; decided_at: string | null }
    | null;
}

export interface CaseQueueResponse {
  cases: CaseSummary[];
  count: number;
}

export interface CaseDetail {
  case_id: string;
  transaction_id: number;
  status: CaseStatus;
  title: string;
  actor: string | null;
  created_at: string | null;
  updated_at: string | null;
  model_risk: { risk_score: number; risk_band: string; model_version: string } | null;
  /** details_json arrives as a JSON-encoded string from the storage layer */
  evidence: {
    evidence_id: string;
    transaction_id: number;
    evidence_type: EvidenceType;
    details_json: string;
    evidence_hash: string;
    generated_at: string | null;
  }[];
  notes: { actor: string; note: string; created_at: string | null }[];
  history: {
    history_id: number;
    actor: string;
    action: string;
    prev_status: string | null;
    new_status: string | null;
    details: Record<string, unknown>;
    created_at: string | null;
  }[];
  decisions: {
    decision_id: string;
    reviewer: string;
    decision: string;
    decided_at: string | null;
    notes: string | null;
    evidence_ids: string[];
    request_id: string | null;
  }[];
  label: {
    label_id: string;
    value: number;
    arrival_at: string | null;
    effective_at: string | null;
    source: string | null;
  } | null;
}

export interface CreateCaseInput {
  transaction_id: number;
  title: string;
  actor: string;
  evidence_ids: string[];
}

export interface DecisionInput {
  decision: "CONFIRMED_FRAUD" | "FALSE_POSITIVE";
  actor: string;
  notes?: string | null;
  evidence_ids: string[];
}

export interface EntityRisk {
  entity_type: EntityType;
  entity_key: string;
  as_of_ts: number;
  min_label_lag_days: number;
  eligible_boundary: string | null;
  entity_fraud_count: number;
  entity_total_labeled_count: number;
  fraud_rate: number | null;
  computed_at: string | null;
  note: string;
}
