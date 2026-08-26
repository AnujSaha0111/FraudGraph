import { FormEvent, useMemo, useState } from "react";
import { getCase, patchCase, postDecision } from "../api/fraudgraph";
import type { CaseDetail, CaseStatus } from "../api/types";
import { useAsyncData } from "../hooks/useAsyncData";
import { useRoute } from "../hooks/useRoute";
import { BandBadge } from "../components/BandBadge";
import { ErrorState } from "../components/ErrorState";
import { Loading, SectionCard, KV } from "../components/ui";

/** Mirror of app/cases/state_machine.py — restricted to statuses the PATCH
 *  endpoint actually accepts (decision states are reachable ONLY through the
 *  immutable-decision form below; CLOSED only from a decided state).
 *  The backend remains the single authority: any 409 is shown verbatim. */
const NEXT_STATUS: Record<CaseStatus, CaseStatus[]> = {
  NEW: ["INVESTIGATING", "ESCALATED"],
  INVESTIGATING: ["ESCALATED"],
  ESCALATED: ["INVESTIGATING"],
  CONFIRMED_FRAUD: ["CLOSED"],
  FALSE_POSITIVE: ["CLOSED"],
  CLOSED: [],
};

const STATUS_ORDER: CaseStatus[] = [
  "NEW",
  "INVESTIGATING",
  "ESCALATED",
  "CONFIRMED_FRAUD",
  "FALSE_POSITIVE",
  "CLOSED",
];

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge status-${status}`} data-testid="case-status">
      {status}
    </span>
  );
}

function fmtTs(ts: string | null | undefined): string {
  return ts ? ts.replace("T", " ").slice(0, 19) : "—";
}

export function CaseScreen({ id }: { id: number | string }) {
  const [, navigate] = useRoute();
  const { data, error, loading, reload } = useAsyncData(() => getCase(id), [id]);

  if (loading) return <Loading label={`Loading case ${id}`} />;
  if (error) {
    return (
      <div className="screen">
        <ErrorState error={error} />
      </div>
    );
  }
  if (!data) return null;
  return <CaseDetail_ data={data} navigate={navigate} reload={reload} />;
}

function CaseDetail_({
  data,
  navigate,
  reload,
}: {
  data: CaseDetail;
  navigate: (to: string) => void;
  reload: () => void;
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // transition / note form state
  const [actor, setActor] = useState("");
  const [noteText, setNoteText] = useState("");

  // decision form state
  const [decision, setDecision] = useState<"CONFIRMED_FRAUD" | "FALSE_POSITIVE">(
    "CONFIRMED_FRAUD",
  );
  const [decisionNotes, setDecisionNotes] = useState("");
  const [decEvidence, setDecEvidence] = useState<Record<string, boolean>>({});
  const [immutableAck, setImmutableAck] = useState(false);

  const terminal = data.status === "CONFIRMED_FRAUD" || data.status === "FALSE_POSITIVE";
  const decidable = data.status === "INVESTIGATING" || data.status === "ESCALATED";
  const selectedEv = useMemo(
    () => Object.entries(decEvidence).filter(([, v]) => v).map(([k]) => k),
    [decEvidence],
  );

  const run = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    if (!actor.trim()) {
      setActionError("Reviewer identity (actor) is required for every mutation.");
      return;
    }
    setBusy(true);
    try {
      await fn();
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const doTransition = (status: CaseStatus) =>
    run(() =>
      patchCase(data.case_id, { actor: actor.trim(), status }),
    );

  const addNote = (e: FormEvent) => {
    e.preventDefault();
    if (!noteText.trim()) return;
    run(async () => {
      await patchCase(data.case_id, { actor: actor.trim(), note: noteText.trim() });
      setNoteText("");
    });
  };

  const submitDecision = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const res = await postDecision(data.case_id, {
        decision,
        actor: actor.trim(),
        notes: decisionNotes.trim() || null,
        evidence_ids: selectedEv,
      });
      void res;
    });
  };

  const decisionReady =
    immutableAck && selectedEv.length > 0 && actor.trim().length > 0;

  return (
    <div className="screen">
      <SectionCard
        title={
          <>
            Case {data.case_id}{" "}
            <StatusBadge status={data.status} />
          </>
        }
        subtitle={`${data.title} · transaction `}
        tone={terminal || data.status === "CLOSED" ? "context" : "default"}
      >
        <div className="kv-grid">
          <KV k="transaction" v={
            <button className="linklike" onClick={() => navigate(`/tx/${data.transaction_id}`)}>
              {data.transaction_id}
            </button>
          } mono />
          <KV k="opened by" v={data.actor ?? "—"} />
          <KV k="opened at" v={fmtTs(data.created_at)} mono />
          <KV k="last update" v={fmtTs(data.updated_at)} mono />
          <KV
            k="model risk"
            v={
              data.model_risk ? (
                <>
                  <span className="mono">{Number(data.model_risk.risk_score).toFixed(4)}</span>{" "}
                  <BandBadge band={data.model_risk.risk_band} />
                </>
              ) : (
                "—"
              )
            }
          />
        </div>

        {/* workflow strip */}
        <ol className="workflow-strip" aria-label="case lifecycle">
          {STATUS_ORDER.map((s) => (
            <li
              key={s}
              className={s === data.status ? "current" : ""}
              data-state={s}
            >
              {s}
            </li>
          ))}
        </ol>
        {(terminal || data.status === "CLOSED") && (
          <p className="note note-warn">
            This case is in terminal state <strong>{data.status}</strong>. The
            recorded decision is immutable — it cannot be edited or overwritten.
            {data.status !== "CLOSED" && " It can still be CLOSED."}
          </p>
        )}
      </SectionCard>

      {actionError && (
        <div className="conflict-banner" role="alert" data-testid="action-error">
          <strong>Rejected:</strong> {actionError}
        </div>
      )}

      {/* actions */}
      <SectionCard title="Actions">
        <label className="field">
          <span>Reviewer / actor *</span>
          <input
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            placeholder="analyst-yourname"
          />
        </label>

        {NEXT_STATUS[data.status].length > 0 && (
          <div className="transition-row" data-testid="transitions">
            <span className="muted small">Move status →</span>
            {NEXT_STATUS[data.status].map((s) => (
              <button
                key={s}
                disabled={busy}
                className="chip"
                onClick={() => doTransition(s)}
              >
                {s}
              </button>
            ))}
            {data.status === "NEW" && (
              <span className="muted small">
                (terminal decisions are made below after INVESTIGATING/ESCALATED)
              </span>
            )}
          </div>
        )}

        <form onSubmit={addNote} className="note-form">
          <label className="field grow">
            <span>Add note (append-only history)</span>
            <input
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="what did you check?"
            />
          </label>
          <button type="submit" disabled={busy || !noteText.trim()}>
            Add note
          </button>
        </form>

        {decidable && (
          <form onSubmit={submitDecision} className="decision-form" data-testid="decision-form">
            <h3 className="subhead danger">Terminal decision — irreversible</h3>
            <p className="muted small">
              Writes an immutable decision record, moves the case to the matching
              terminal state, and creates exactly one label referencing the
              decision. Decisions can never be edited or overwritten afterwards.
            </p>
            <div className="radio-row">
              <label className="check-row">
                <input
                  type="radio"
                  name="decision"
                  checked={decision === "CONFIRMED_FRAUD"}
                  onChange={() => setDecision("CONFIRMED_FRAUD")}
                />
                CONFIRMED_FRAUD <span className="muted small">→ creates fraud label</span>
              </label>
              <label className="check-row">
                <input
                  type="radio"
                  name="decision"
                  checked={decision === "FALSE_POSITIVE"}
                  onChange={() => setDecision("FALSE_POSITIVE")}
                />
                FALSE_POSITIVE <span className="muted small">→ non-fraud label</span>
              </label>
            </div>

            <fieldset className="field">
              <legend>Acknowledge evidence * (≥1 record must be cited)</legend>
              {data.evidence.length === 0 && (
                <p className="note note-warn">
                  This case has no attached evidence records. A decision requires
                  acknowledging at least one — create the case with evidence or
                  investigate further first.
                </p>
              )}
              {data.evidence.map((ev) => {
                let parsed: Record<string, unknown> = {};
                try {
                  parsed = JSON.parse(ev.details_json || "{}");
                } catch {
                  /* keep empty */
                }
                return (
                  <label key={ev.evidence_id} className="check-row">
                    <input
                      type="checkbox"
                      checked={!!decEvidence[ev.evidence_id]}
                      onChange={(e) =>
                        setDecEvidence((m) => ({ ...m, [ev.evidence_id]: e.target.checked }))
                      }
                    />
                    <span className="badge type-badge">{ev.evidence_type}</span>
                    <span className="mono small">{ev.evidence_id.slice(0, 13)}…</span>
                    {Object.keys(parsed).length > 0 && (
                      <span className="muted small ellipsis">{JSON.stringify(parsed).slice(0, 80)}</span>
                    )}
                  </label>
                );
              })}
            </fieldset>

            <label className="field">
              <span>Decision notes</span>
              <input
                value={decisionNotes}
                onChange={(e) => setDecisionNotes(e.target.value)}
                placeholder="rationale (stored with the decision)"
              />
            </label>

            <label className="check-row ack">
              <input
                type="checkbox"
                checked={immutableAck}
                onChange={(e) => setImmutableAck(e.target.checked)}
              />
              I understand this decision is <strong>permanent</strong>, will be
              stored immutably with my identity, and will create a training label.
            </label>

            <button type="submit" className="danger-btn" disabled={!decisionReady || busy}>
              Submit {decision}
            </button>
            {!decisionReady && (
              <span className="muted small"> actor + ≥1 evidence + acknowledgement required</span>
            )}
          </form>
        )}
      </SectionCard>

      {/* evidence */}
      <SectionCard
        title="Evidence on this case"
        subtitle="Frozen references to deterministic evidence records."
        tone="evidence"
      >
        {data.evidence.length === 0 ? (
          <p className="muted">No evidence was attached.</p>
        ) : (
          <ul className="plain-list" data-testid="case-evidence-list">
            {data.evidence.map((ev) => (
              <li key={ev.evidence_id} className="mono small">
                <span className="badge type-badge">{ev.evidence_type}</span>{" "}
                {ev.evidence_id}{" "}
                <span className="muted">hash {ev.evidence_hash.slice(0, 16)}…</span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {/* notes */}
      <SectionCard title="Investigator notes">
        {data.notes.length === 0 ? (
          <p className="muted">No notes yet.</p>
        ) : (
          <ul className="notes-list">
            {data.notes.map((n, i) => (
              <li key={i}>
                <strong>{n.actor}</strong>{" "}
                <span className="muted small">{fmtTs(n.created_at)}</span>
                <p>{n.note}</p>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {/* decisions + label */}
      {(data.decisions.length > 0 || data.label) && (
        <SectionCard title="Decision & label" tone="model">
          {data.decisions.map((d) => (
            <div key={d.decision_id} className="decision-record" data-testid="decision-record">
              <span className={`badge ${d.decision === "CONFIRMED_FRAUD" ? "band-critical" : "band-low"}`}>
                {d.decision}
              </span>
              <span className="mono small">decision_id {d.decision_id}</span>
              <span className="muted small">by {d.reviewer} at {fmtTs(d.decided_at)}</span>
              {d.notes && <p>“{d.notes}”</p>}
              <span className="muted small mono">
                cited evidence: [{d.evidence_ids.join(", ") || "none"}]
              </span>
            </div>
          ))}
          {data.label && (
            <div className="label-record" data-testid="label-record">
              <h3 className="subhead">Label created</h3>
              <div className="kv-grid">
                <KV k="label_id" v={data.label.label_id} mono />
                <KV k="value" v={data.label.value === 1 ? "1 (fraud)" : "0 (non-fraud)"} mono />
                <KV k="source" v={data.label.source ?? "reviewer"} />
                <KV k="arrival_at" v={fmtTs(data.label.arrival_at)} mono />
                <KV k="effective_at" v={fmtTs(data.label.effective_at)} mono />
              </div>
              <p className="muted small">
                Becomes eligible for delayed EntityRisk once MIN_LABEL_LAG (7 days)
                has passed after arrival.
              </p>
            </div>
          )}
        </SectionCard>
      )}

      {/* history */}
      <SectionCard
        title="Audit history"
        subtitle="Append-only: what happened, who did it, when."
      >
        <table className="table narrow" data-testid="history-table">
          <thead>
            <tr>
              <th>#</th>
              <th>action</th>
              <th>prev → new</th>
              <th>actor</th>
              <th>at (UTC)</th>
            </tr>
          </thead>
          <tbody>
            {data.history.map((h) => (
              <tr key={h.history_id}>
                <td>{h.history_id}</td>
                <td>{h.action}</td>
                <td className="mono small">
                  {h.prev_status ?? "—"} → {h.new_status ?? "—"}
                </td>
                <td>{h.actor}</td>
                <td className="mono small">{fmtTs(h.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>
    </div>
  );
}
