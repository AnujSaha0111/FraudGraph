import { listCases } from "../api/fraudgraph";
import { useAsyncData } from "../hooks/useAsyncData";
import { useRoute } from "../hooks/useRoute";
import { BandBadge } from "../components/BandBadge";
import { ErrorState } from "../components/ErrorState";
import { EmptyState, Loading, SectionCard } from "../components/ui";

/** Reviewer queue across all cases (GET /cases). */
export function CasesScreen() {
  const [, navigate] = useRoute();
  const { data, error, loading } = useAsyncData(() => listCases(), []);

  return (
    <div className="screen">
      <SectionCard
        title="Case review queue"
        subtitle="Every case with its current state — full audit trail behind each row."
      >
        {loading && <Loading label="Loading cases" />}
        {error && <ErrorState error={error} />}
        {data && data.count === 0 && (
          <EmptyState
            title="No cases exist yet."
            hint="Open a transaction and create a case to start the review workflow."
          />
        )}
        {data && data.count > 0 && (
          <table className="table" data-testid="cases-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Status</th>
                <th>Title</th>
                <th>Txn</th>
                <th>Score</th>
                <th>Evidence</th>
                <th>Opened</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.cases.map((c) => (
                <tr key={c.case_id}>
                  <td className="mono">{c.case_id}</td>
                  <td>
                    <span className={`badge status-${c.status}`}>{c.status}</span>
                  </td>
                  <td>{c.title}</td>
                  <td className="mono">{c.transaction_id}</td>
                  <td>
                    {c.model_risk ? (
                      <>
                        <span className="mono small">{Number(c.model_risk.risk_score).toFixed(3)}</span>{" "}
                        <BandBadge band={c.model_risk.risk_band} />
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{c.evidence_count}</td>
                  <td className="mono small muted">{fmtTs(c.created_at)}</td>
                  <td>
                    <button className="linklike" onClick={() => navigate(`/case/${c.case_id}`)}>
                      review →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
    </div>
  );
}

function fmtTs(ts: string | null): string {
  return ts ? ts.replace("T", " ").slice(0, 16) : "—";
}
