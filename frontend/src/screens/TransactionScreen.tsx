import { FormEvent, useMemo, useState } from "react";
import {
  createCase,
  getEvidence,
  getExplanation,
  getGraph,
  getRisk,
  listCases,
} from "../api/fraudgraph";
import type { GraphEntityType } from "../api/types";
import { useAsyncData } from "../hooks/useAsyncData";
import { useRoute } from "../hooks/useRoute";
import { BandBadge } from "../components/BandBadge";
import { EntityRiskPanel } from "../components/EntityRiskPanel";
import { ErrorState } from "../components/ErrorState";
import { EvidenceList } from "../components/EvidenceList";
import { GraphView } from "../components/GraphView";
import { Loading, SectionCard } from "../components/ui";

function days(n: number): string {
  const d = n / 86400;
  return `${d % 1 === 0 ? d : d.toFixed(1)}d`;
}

export function TransactionScreen({ id }: { id: number | string }) {
  const [, navigate] = useRoute();
  const risk = useAsyncData(() => getRisk(id), [id]);
  const explanation = useAsyncData(() => getExplanation(id, 5), [id]);
  const evidence = useAsyncData(() => getEvidence(id), [id]);
  const graph = useAsyncData(() => getGraph(id), [id]);
  const myCases = useAsyncData(
    async () =>
      (await listCases()).cases.filter((c) => c.transaction_id === id),
    [id],
  );

  // ---- create-case state ----
  const [caseActor, setCaseActor] = useState("");
  const [caseTitle, setCaseTitle] = useState("");
  const [checkedEv, setCheckedEv] = useState<Record<string, boolean>>({});
  const [caseError, setCaseError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const evidenceRecords = evidence.data?.evidence ?? [];
  const attachable = useMemo(
    () => evidenceRecords.filter((r) => r.evidence_type !== "NO_RELATIONAL_EVIDENCE"),
    [evidenceRecords],
  );

  if (risk.loading) return <Loading label={`Loading transaction ${id}`} />;
  if (risk.error) {
    return (
      <div className="screen">
        <ErrorState error={risk.error} />
      </div>
    );
  }
  const riskData = risk.data;
  if (!riskData) return null;

  const seedEntities = (graph.data?.entities ?? []).filter(
    (e): e is { entity_type: GraphEntityType; entity_key: string } =>
      e.entity_type !== "TRANSACTION",
  );

  const submitCase = async (e: FormEvent) => {
    e.preventDefault();
    setCaseError(null);
    const selected = Object.entries(checkedEv)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (!caseActor.trim()) {
      setCaseError("Reviewer identity (actor) is required for audit.");
      return;
    }
    if (!caseTitle.trim()) {
      setCaseError("Give the case a short title.");
      return;
    }
    setCreating(true);
    try {
      const res = await createCase({
        transaction_id: Number(id), // route id is digits-only; txn ids are small
        title: caseTitle.trim(),
        actor: caseActor.trim(),
        evidence_ids: selected,
      });
      navigate(`/case/${res.case_id}`);
    } catch (err) {
      setCaseError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="screen">
      {/* A. model risk summary */}
      <SectionCard
        title={`Transaction ${id}`}
        subtitle="MODEL RISK — a heuristic XGBoost output, not a calibrated probability and not evidence."
        tone="model"
      >
        <div className="score-strip">
          <span className="score mono" data-testid="risk-score">
            {Number(riskData.risk_score).toFixed(4)}
          </span>
          <BandBadge band={riskData.risk_band} />
          <span className="mono muted">model {riskData.model_version}</span>
        </div>
        <p className="muted small">
          Score ∈ [0,1] from fraud_xgb_v1 (438 features). Bands LOW/MEDIUM/HIGH/
          CRITICAL are fixed thresholds used for triage only.
        </p>

        <h3 className="subhead">Top model contributors</h3>
        <p className="muted small">
          MODEL EXPLANATION — why the score is what it is. This is attribution,
          not investigative evidence.
        </p>
        {explanation.loading && <Loading label="Computing SHAP explanation" />}
        {explanation.error && <ErrorState error={explanation.error} />}
        {explanation.data && (
          <table className="table narrow" data-testid="explanation-table">
            <thead>
              <tr>
                <th>#</th>
                <th>feature</th>
                <th>value</th>
                <th>contribution (SHAP)</th>
                <th>direction</th>
              </tr>
            </thead>
            <tbody>
              {explanation.data.top_features.map((f, i) => (
                <tr key={f.feature}>
                  <td>{f.abs_rank ?? i + 1}</td>
                  <td className="mono">{f.feature}</td>
                  <td className="mono">{f.value === null ? "—" : f.value.toFixed(3)}</td>
                  <td className="mono">{f.contribution >= 0 ? "+" : ""}{f.contribution.toFixed(4)}</td>
                  <td className={f.direction}>{f.direction}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* B. evidence */}
      <SectionCard
        title="Investigative evidence"
        subtitle={
          evidence.data
            ? `Deterministic records · engine ${evidence.data.evidence_engine_version} · distinct from the model score above`
            : "Deterministic records, distinct from model risk"
        }
        tone="evidence"
      >
        {evidence.loading && <Loading label="Generating/loading evidence" />}
        {evidence.error && <ErrorState error={evidence.error} />}
        {evidence.data && <EvidenceList records={evidence.data.evidence} />}
      </SectionCard>

      {/* C. graph */}
      <SectionCard
        title="Relational context"
        subtitle="Temporal expansion around the seed (configured window, hub-guarded)."
      >
        {graph.loading && <Loading label="Expanding neighborhood" />}
        {graph.error && <ErrorState error={graph.error} />}
        {graph.data && (
          <>
            <GraphView graph={graph.data} />
            <div className="graph-meta mono small muted" data-testid="graph-meta">
              window −{days(graph.data.parameters.back_s)}/+{days(graph.data.parameters.fwd_s)} · depth{" "}
              {graph.data.parameters.depth} · hub cap {graph.data.parameters.hub_degree_max} · neighbor cap{" "}
              {graph.data.parameters.neighbor_cap} · params_hash{" "}
              {graph.data.params_hash.slice(0, 12)}
              {" · "}
              community {graph.data.community.summary.transaction_count} txns /{" "}
              {graph.data.community.summary.entity_count} entities · span{" "}
              {graph.data.community.summary.time_span_hours}h ·{" "}
              {graph.data.community.summary.n_components_total} component(s)
              {graph.data.pruning.some((p) => p.pruned) && (
                <>
                  {" · "}
                  <strong>
                    hub-pruned:{" "}
                    {graph.data.pruning
                      .filter((p) => p.pruned)
                      .map((p) => `${p.entity_type}:${String(p.entity_key).slice(0, 10)} (deg ${p.degree})`)
                      .join(", ")}
                  </strong>{" "}
                  — excluded from expansion by design
                </>
              )}
            </div>
          </>
        )}
      </SectionCard>

      {/* D. delayed-label entity context */}
      <SectionCard
        title="Delayed entity-risk context"
        subtitle="Point-in-time human-decision history per entity. Context only — never a feature."
        tone="context"
      >
        {graph.loading && <Loading label="Resolving entities" />}
        {!graph.loading && !graph.error && (
          <EntityRiskPanel entities={seedEntities} asOfTs={graph.data?.seed.ts ?? 0} />
        )}
      </SectionCard>

      {/* case creation + existing cases */}
      <SectionCard
        title="Human review"
        subtitle="Open a case to investigate and record an immutable decision."
      >
        {myCases.data && myCases.data.length > 0 && (
          <div className="existing-cases">
            <h3 className="subhead">Existing cases on this transaction</h3>
            {myCases.data.map((c) => (
              <button
                key={c.case_id}
                className="linklike block"
                onClick={() => navigate(`/case/${c.case_id}`)}
              >
                case {c.case_id} — “{c.title}” [{c.status}] →
              </button>
            ))}
          </div>
        )}
        <form onSubmit={submitCase} className="case-form">
          <h3 className="subhead">Create new case</h3>
          <label className="field">
            <span>Short title *</span>
            <input
              value={caseTitle}
              onChange={(e) => setCaseTitle(e.target.value)}
              placeholder={`Review high score on ${id}`}
            />
          </label>
          <label className="field">
            <span>Reviewer / actor * (recorded in the audit trail)</span>
            <input
              value={caseActor}
              onChange={(e) => setCaseActor(e.target.value)}
              placeholder="analyst-yourname"
            />
          </label>
          <fieldset className="field">
            <legend>Acknowledge evidence at case open (optional)</legend>
            {attachable.length === 0 && (
              <span className="muted small">
                No attachable evidence records exist yet.
              </span>
            )}
            {attachable.map((rec) => (
              <label key={rec.evidence_id} className="check-row">
                <input
                  type="checkbox"
                  checked={!!checkedEv[rec.evidence_id]}
                  onChange={(e) =>
                    setCheckedEv((m) => ({ ...m, [rec.evidence_id]: e.target.checked }))
                  }
                />
                <span className="mono small">{rec.evidence_type}</span>
                <span className="muted small">{rec.evidence_id.slice(0, 13)}…</span>
              </label>
            ))}
          </fieldset>
          {caseError && (
            <p className="note note-warn" role="alert">
              {caseError}
            </p>
          )}
          <button type="submit" className="primary" disabled={creating}>
            {creating ? "Creating…" : "Create case (status NEW)"}
          </button>
        </form>
      </SectionCard>
    </div>
  );
}
