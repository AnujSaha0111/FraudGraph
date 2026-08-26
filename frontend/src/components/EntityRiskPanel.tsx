import { useState } from "react";
import { getEntityRisk } from "../api/fraudgraph";
import type { GraphEntityType } from "../api/types";
import { useAsyncData } from "../hooks/useAsyncData";
import { ErrorState } from "./ErrorState";
import { Loading, KV } from "./ui";

/** Screen 4 — delayed-label entity risk, embedded where an investigator
 *  needs it (transaction detail). Point-in-time by construction: the query
 *  re-runs per as_of_ts and the eligible boundary is displayed. This is
 *  CONTEXT ONLY — never a prediction feature. */
export function EntityRiskPanel(props: {
  entities: { entity_type: GraphEntityType; entity_key: string }[];
  asOfTs: number;
}) {
  const [selected, setSelected] = useState<{
    entityType: GraphEntityType;
    key: string;
  } | null>(null);

  if (props.entities.length === 0) {
    return (
      <p className="muted">
        No CARD/DEVICE/ADDRESS entities are linked to this transaction in the
        graph layer, so no delayed-risk context can be queried.
      </p>
    );
  }

  const active = selected ?? {
    entityType: props.entities[0].entity_type,
    key: props.entities[0].entity_key,
  };

  return (
    <div className="entityrisk">
      <div className="chip-row" role="tablist" aria-label="linked entities">
        {props.entities.map((e) => {
          const isActive =
            active.entityType === e.entity_type && active.key === e.entity_key;
          return (
            <button
              key={`${e.entity_type}:${e.entity_key}`}
              role="tab"
              aria-selected={isActive}
              className={`chip ${isActive ? "chip-active" : ""}`}
              onClick={() =>
                setSelected({ entityType: e.entity_type, key: e.entity_key })
              }
            >
              {e.entity_type}:{String(e.entity_key).slice(0, 12)}
            </button>
          );
        })}
      </div>
      <EntityRiskResult
        key={`${active.entityType}:${active.key}`}
        entityType={active.entityType}
        entityKey={active.key}
        asOfTs={props.asOfTs}
      />
    </div>
  );
}

function fmtBoundary(iso: string | null): string {
  if (!iso) return "—";
  return `${iso.replace("T", " ").slice(0, 19)} UTC`;
}

export function EntityRiskResult(props: {
  entityType: GraphEntityType;
  entityKey: string;
  asOfTs: number;
}) {
  const { data, error, loading } = useAsyncData(
    () => getEntityRisk(props.entityType, props.entityKey, props.asOfTs),
    [props.entityType, props.entityKey, props.asOfTs],
  );

  if (loading) return <Loading label="Querying delayed label history" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  const insufficient = data.entity_total_labeled_count < 1 || data.fraud_rate === null;

  return (
    <div className="entityrisk-result" data-testid="entityrisk-result">
      <div className="kv-grid">
        <KV k="entity" v={`${data.entity_type}:${data.entity_key}`} mono />
        <KV k="as_of_ts" v={data.as_of_ts.toLocaleString()} mono />
        <KV k="min_label_lag" v={`${data.min_label_lag_days} days`} />
        <KV
          k="labels eligible if arrived ≤"
          v={fmtBoundary(data.eligible_boundary)}
          mono
        />
        <KV k="labeled outcomes counted" v={data.entity_total_labeled_count} />
        <KV k="confirmed fraud among them" v={data.entity_fraud_count} />
        <KV
          k="fraud rate"
          v={
            data.fraud_rate === null ? (
              "—"
            ) : (
              <>
                {(data.fraud_rate * 100).toFixed(1)}%
                <span className="muted small"> ({data.fraud_rate.toFixed(4)})</span>
              </>
            )
          }
        />
      </div>
      {insufficient && (
        <p className="note note-warn" data-testid="insufficient-evidence-note">
          Insufficient historical evidence: no labels for this entity were
          eligible at this point in time. An empty result is reported honestly,
          never estimated.
        </p>
      )}
      <p className="note">
        Delayed-label context only: counts include a human decision outcome once{" "}
        <code>MIN_LABEL_LAG</code> has passed. This is <strong>not</strong> a
        model feature and does not influence any score.
      </p>
    </div>
  );
}
