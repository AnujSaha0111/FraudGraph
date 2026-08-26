import { useState } from "react";
import type { EvidenceRecord } from "../api/types";

const TYPE_LABEL: Record<string, string> = {
  NEW_PAIRING: "New pairing",
  AMOUNT_DEVIATION: "Amount deviation",
  UNUSUAL_HOUR: "Unusual hour",
  VELOCITY_BURST: "Velocity burst",
  SHARED_DEVICE_LINK: "Shared device",
  COMMUNITY_STATS: "Community stats",
  CONNECTED_HIGH_RISK: "Connected high-risk",
  NO_RELATIONAL_EVIDENCE: "No relational evidence",
};

function severityClass(s: string): string {
  return `sev-${s.toLowerCase()}`;
}

function EvidenceCard({ rec }: { rec: EvidenceRecord }) {
  const [showAudit, setShowAudit] = useState(false);
  return (
    <article
      className={`evidence-card ${
        rec.evidence_type === "NO_RELATIONAL_EVIDENCE" ? "evidence-none" : ""
      }`}
      data-testid="evidence-card"
    >
      <header className="evidence-head">
        <span className={`badge type-badge`}>{TYPE_LABEL[rec.evidence_type] ?? rec.evidence_type}</span>
        <span className={`badge ${severityClass(rec.severity)}`}>{rec.severity}</span>
        <span className="evidence-id mono" title={rec.evidence_id}>
          {rec.evidence_id.slice(0, 8)}…
        </span>
      </header>
      <h4>{rec.title}</h4>
      <p>{rec.description}</p>

      {Object.keys(rec.details).length > 0 && (
        <details className="evidence-details">
          <summary>structured details</summary>
          <table className="detail-table">
            <tbody>
              {Object.entries(rec.details).map(([k, v]) => (
                <tr key={k}>
                  <td className="k">{k}</td>
                  <td className="v mono">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <button className="linklike" onClick={() => setShowAudit((s) => !s)}>
        {showAudit ? "hide audit trail" : "audit trail (hash, provenance)"}
      </button>
      {showAudit && (
        <div className="audit-block mono small" data-testid="audit-block">
          <div>evidence_hash: {rec.evidence_hash}</div>
          <div>
            provenance:{" "}
            {rec.provenance
              ? `${rec.provenance.source_table} rows [${rec.provenance.source_row_ids.join(", ")}] engine ${rec.provenance.code_version}`
              : "—"}
          </div>
          <div>generated_at: {rec.generated_at ?? "—"} (runtime only; excluded from hash)</div>
        </div>
      )}
    </article>
  );
}

export function EvidenceList({ records }: { records: EvidenceRecord[] }) {
  const noRelational =
    records.length === 1 && records[0].evidence_type === "NO_RELATIONAL_EVIDENCE";

  if (noRelational) {
    return (
      <div className="no-relational" data-testid="no-relational-evidence">
        <h4>No relational evidence fired for this transaction.</h4>
        <p className="muted">
          The evidence engine checked all configured rules and honestly reports
          that no relational story was found. This is an explicit outcome — the
          system does not fabricate evidence to fill the page. The model score
          above stands on its own.
        </p>
        <details>
          <summary>view the record</summary>
          <EvidenceCard rec={records[0]} />
        </details>
      </div>
    );
  }

  return (
    <div className="evidence-list">
      <p className="muted small">
        {records.length} deterministic record{records.length === 1 ? "" : "s"} ·
        same inputs + same code ⇒ identical content (verified via evidence_hash)
      </p>
      {records.map((rec) => (
        <EvidenceCard key={rec.evidence_id} rec={rec} />
      ))}
    </div>
  );
}
