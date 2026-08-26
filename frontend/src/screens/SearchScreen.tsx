import { FormEvent, useState } from "react";
import { getQueue } from "../api/fraudgraph";
import { BANDS } from "../api/types";
import type { RiskBand } from "../api/types";
import { useAsyncData } from "../hooks/useAsyncData";
import { useRoute } from "../hooks/useRoute";
import { BandBadge } from "../components/BandBadge";
import { ErrorState } from "../components/ErrorState";
import { EmptyState, Loading } from "../components/ui";

/** Screen 1 — transaction entry + flagged queue.
 *  The queue is served by GET /transactions (API contract): ranked,
 *  real scores from risk_predictions. Nothing here is fabricated. */
export function SearchScreen() {
  const [, navigate] = useRoute();
  const [query, setQuery] = useState("");
  const [bandFilter, setBandFilter] = useState<RiskBand | "">("");
  const [evidenceOnly, setEvidenceOnly] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const queue = useAsyncData(
    () =>
      getQueue({
        band: bandFilter || undefined,
        hasEvidence: evidenceOnly ? true : undefined,
        limit: 25,
      }),
    [bandFilter, evidenceOnly],
  );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSearchError(null);
    const trimmed = query.trim();
    if (!/^\d+$/.test(trimmed)) {
      setSearchError("Enter a numeric IEEE-CIS TransactionID (e.g. 2987004).");
      return;
    }
    navigate(`/tx/${trimmed}`);
  };

  return (
    <div className="screen">
      <section className="card">
        <h2>Investigate a transaction</h2>
        <p className="muted">
          Enter an IEEE-CIS TransactionID to open the investigation view:
          model score → explanation → relational graph → deterministic evidence
          → case decision.
        </p>
        <form className="search-row" onSubmit={submit}>
          <input
            className="search-input mono"
            placeholder="TransactionID…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="transaction id"
            inputMode="numeric"
          />
          <button type="submit" className="primary">
            Investigate
          </button>
        </form>
        {searchError && <p className="note note-warn">{searchError}</p>}
        <p className="muted small">
          Coverage note: IEEE-CIS identity data exists for ~24% of transactions;
          IDs outside production coverage return <code>422</code> and unknown IDs{" "}
          <code>404</code>. Both are reported honestly.
        </p>
      </section>

      <section className="card">
        <div className="card-head row">
          <h2>Flagged queue</h2>
          <div className="filter-row">
            <button
              className={`chip ${bandFilter === "" ? "chip-active" : ""}`}
              onClick={() => setBandFilter("")}
            >
              all bands
            </button>
            {[...BANDS].reverse().map((b) => (
              <button
                key={b}
                className={`chip ${bandFilter === b ? "chip-active" : ""}`}
                onClick={() => setBandFilter(b)}
              >
                {b}
              </button>
            ))}
            <label className="chip chip-toggle">
              <input
                type="checkbox"
                checked={evidenceOnly}
                onChange={(e) => setEvidenceOnly(e.target.checked)}
              />{" "}
              has evidence
            </label>
          </div>
        </div>

        {queue.loading && <Loading label="Loading scored transactions" />}
        {queue.error && <ErrorState error={queue.error} />}
        {!queue.loading && !queue.error && queue.data && queue.data.count === 0 && (
          <EmptyState
            title="No scored transactions match."
            hint="The store contains no risk_predictions rows for this filter yet. Run scripts/bootstrap_db.py, or clear filters."
          />
        )}
        {!queue.loading && !queue.error && queue.data && queue.data.count > 0 && (
          <table className="table" data-testid="queue-table">
            <thead>
              <tr>
                <th>Txn ID</th>
                <th>Score</th>
                <th>Band</th>
                <th>Model</th>
                <th>Evidence</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {queue.data.transactions.map((t) => (
                <tr key={t.transaction_id}>
                  <td className="mono">{t.transaction_id}</td>
                  <td className="mono">{Number(t.risk_score).toFixed(4)}</td>
                  <td>
                    <BandBadge band={t.risk_band} />
                  </td>
                  <td className="mono muted small">{t.model_version ?? "—"}</td>
                  <td>{t.has_evidence ? "available" : <span className="muted">none generated</span>}</td>
                  <td>
                    <button
                      className="linklike"
                      onClick={() => navigate(`/tx/${t.transaction_id}`)}
                    >
                      investigate →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">
          Scores come from XGBoost v1 over validated features. Bands are
          heuristic thresholds (LOW &lt;0.3 · MEDIUM &lt;0.6 · HIGH &lt;0.85 ·
          CRITICAL ≥0.85) — not calibrated probabilities.
        </p>
      </section>
    </div>
  );
}
