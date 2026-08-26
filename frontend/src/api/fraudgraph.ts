/** FraudGraph API endpoints (typed wrappers over client.ts). */
import { apiGet, apiSend } from "./client";
import type {
  CaseDetail,
  CaseQueueResponse,
  CreateCaseInput,
  DecisionInput,
  EntityRisk,
  EntityType,
  EvidenceResponse,
  Explanation,
  GraphEntityType,
  GraphResponse,
  Health,
  QueueResponse,
  RiskRecord,
} from "./types";

export const getHealth = () => apiGet<Health>("/health");

export const getQueue = (opts?: {
  minScore?: number;
  band?: string;
  hasEvidence?: boolean;
  limit?: number;
}) => {
  const q = new URLSearchParams();
  if (opts?.minScore !== undefined) q.set("min_score", String(opts.minScore));
  if (opts?.band) q.set("band", opts.band);
  if (opts?.hasEvidence !== undefined) q.set("has_evidence", String(opts.hasEvidence));
  if (opts?.limit !== undefined) q.set("limit", String(opts.limit));
  const qs = q.toString();
  return apiGet<QueueResponse>(`/transactions${qs ? `?${qs}` : ""}`);
};

export const getRisk = (txnId: number | string) =>
  apiGet<RiskRecord>(`/transactions/${txnId}/risk`);

export const getExplanation = (txnId: number | string, k = 5) =>
  apiGet<Explanation>(`/transactions/${txnId}/risk/explanation?k=${k}`);

export const getEvidence = (txnId: number | string) =>
  apiGet<EvidenceResponse>(`/transactions/${txnId}/evidence`);

export const getGraph = (txnId: number | string) =>
  apiGet<GraphResponse>(`/transactions/${txnId}/graph`);

/** Point-in-time delayed-label context. asOfTs is on the dataset clock
 *  (TransactionDT seconds). */
export const getEntityRisk = (
  entityType: GraphEntityType | EntityType,
  entityKey: string,
  asOfTs: number,
) => {
  const key = encodeURIComponent(entityKey);
  return apiGet<EntityRisk>(
    `/entities/${entityType}/${key}/risk?as_of_ts=${asOfTs}`,
  );
};

export const createCase = (input: CreateCaseInput) =>
  apiSend<{ case_id: string; status: string; request_id: string | null }>(
    "/cases",
    "POST",
    input,
  );

export const listCases = () => apiGet<CaseQueueResponse>("/cases");

export const getCase = (caseId: string | number) => apiGet<CaseDetail>(`/cases/${caseId}`);

export interface PatchCaseInput {
  actor: string;
  status?: string;
  note?: string;
}

export const patchCase = (caseId: string | number, input: PatchCaseInput) =>
  apiSend<{ case_id: string; status: string }>(
    `/cases/${caseId}`,
    "PATCH",
    input,
  );

export const postDecision = (caseId: string | number, input: DecisionInput) =>
  apiSend<{
    decision_id: string;
    case_id: string;
    decision: string;
    status: string;
    label_id: string;
    decided_at: string;
  }>(`/cases/${caseId}/decision`, "POST", input);
