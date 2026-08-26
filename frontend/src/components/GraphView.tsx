import { memo } from "react";
import type { GraphEntityNode, GraphEntityType, GraphNode, GraphResponse } from "../api/types";

/** Investigation graph renderer.
 *  - Every drawn node/edge comes verbatim from GET /transactions/{id}/graph (`nodes` / `edges`). Nothing is synthesized.
 *  - Hub-pruned entities are NOT drawn as nodes (the backend deliberately excludes them from expansion); they are listed as pruning metadata.
 *  - Deterministic layout (stable sorts, fixed radii) so the same payload always renders identically — reproducible demo screenshots.
 */

const W = 940;
const H = 600;
const CX = W / 2;
const CY = H / 2;

const ENTITY_FILL: Record<string, string> = {
  CARD: "#1d4ed8",
  DEVICE: "#7c3aed",
  ADDRESS: "#047857",
};

function polar(cx: number, cy: number, r: number, angle: number): [number, number] {
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
}

interface Positioned {
  node: GraphNode;
  x: number;
  y: number;
}

function layout(graph: GraphResponse): {
  positions: Map<string, Positioned>;
  entityAngles: Map<string, number>;
} {
  const positions = new Map<string, Positioned>();
  const entityAngles = new Map<string, number>();

  const entityNodes = graph.nodes.filter(
    (n): n is GraphEntityNode => n.type !== "TRANSACTION",
  );
  const txnNodes = graph.nodes.filter((n) => n.type === "TRANSACTION");

  // Seed dead center.
  positions.set(`txn:${graph.transaction_id}`, {
    node: txnNodes.find((n) => n.is_seed) ?? {
      id: `txn:${graph.transaction_id}`,
      type: "TRANSACTION",
      transaction_id: graph.transaction_id,
      ts: graph.seed.ts,
      is_seed: true,
      risk_score: graph.seed.risk_score,
    },
    x: CX,
    y: CY,
  });

  // Entities on an inner ring, stable order by id.
  const ents = [...entityNodes].sort((a, b) => a.id.localeCompare(b.id));
  ents.forEach((e, i) => {
    const angle = ents.length === 1 ? -Math.PI / 2 : -Math.PI / 2 + (2 * Math.PI * i) / ents.length;
    entityAngles.set(e.id, angle);
    const [x, y] = polar(CX, CY, 130, angle);
    positions.set(e.id, { node: e, x, y });
  });

  // Neighbor transactions on the outer ring, grouped by the entity that
  // pulled them in (first edge in stable order), fanned within ±22°.
  const neighbors = txnNodes.filter((n) => !n.is_seed);
  const byEntity = new Map<string, string[]>(); // entity id -> txn ids
  for (const e of [...graph.edges].sort(
    (a, b) => a.target.localeCompare(b.target) || a.source.localeCompare(b.source),
  )) {
    if (e.source === `txn:${graph.transaction_id}`) continue;
    const list = byEntity.get(e.target) ?? [];
    list.push(e.source);
    byEntity.set(e.target, list);
  }
  const placed = new Set<string>();
  for (const [entId, txnIds] of [...byEntity.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    const base = entityAngles.get(entId) ?? -Math.PI / 2;
    const uniq = [...new Set(txnIds)].filter((id) => !placed.has(id));
    uniq.forEach((id, i) => {
      placed.add(id);
      const spread =
        uniq.length === 1 ? 0 : (i - (uniq.length - 1) / 2) * (44 / Math.max(uniq.length, 12));
      const [x, y] = polar(CX, CY, 235, base + spread * (Math.PI / 180));
      const node = neighbors.find((n) => n.id === id);
      if (node) positions.set(id, { node, x, y });
    });
  }
  // Any neighbor not reached through edges (defensive): park bottom-left.
  let spare = 0;
  for (const n of neighbors) {
    if (!positions.has(n.id)) {
      positions.set(n.id, { node: n, x: 24 + (spare % 6) * 14, y: H - 30 - Math.floor(spare / 6) * 18 });
      spare += 1;
    }
  }
  return { positions, entityAngles };
}

function GraphViewInner({
  graph,
  onSelectEntity,
}: {
  graph: GraphResponse;
  onSelectEntity?: (entityType: GraphEntityType, key: string) => void;
}) {
  const { positions } = layout(graph);
  const memberSet = new Set(graph.community.members.map((id) => `txn:${id}`));

  return (
    <div className="graph-wrap">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="graph-svg"
        role="img"
        aria-label={`Investigation graph for transaction ${graph.transaction_id}`}
        data-testid="graph-svg"
      >
        {/* temporal window ring */}
        <circle cx={CX} cy={CY} r={235} className="graph-window-ring" />
        <circle cx={CX} cy={CY} r={130} className="graph-window-ring faint" />

        {[...graph.edges].map((e) => {
          const a = positions.get(e.source);
          const b = positions.get(e.target);
          if (!a || !b) return null;
          return (
            <line
              key={`${e.source}->${e.target}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className="graph-edge"
            />
          );
        })}

        {[...positions.values()].map(({ node, x, y }) => {
          if (node.type === "TRANSACTION") {
            const seed = node.is_seed;
            const inCommunity = memberSet.has(node.id);
            return (
              <g key={node.id} transform={`translate(${x},${y})`} className="graph-node">
                <title>
                  {`transaction ${node.transaction_id}\nts: ${node.ts}` +
                    (node.risk_score != null ? `\nrisk: ${Number(node.risk_score).toFixed(4)}` : "")}
                </title>
                <circle
                  r={seed ? 13 : 6}
                  className={
                    seed ? "node-seed" : inCommunity ? "node-txn in-community" : "node-txn"
                  }
                />
                {seed && (
                  <text className="node-label seed-label" y={-20}>
                    SEED {node.transaction_id}
                  </text>
                )}
              </g>
            );
          }
          const fill = ENTITY_FILL[node.type] ?? "#475569";
          const label = `${node.type}:${String(node.entity_key).slice(0, 14)}`;
          return (
            <g
              key={node.id}
              transform={`translate(${x},${y})`}
              className="graph-node entity-node"
              onClick={() => onSelectEntity?.(node.type, node.entity_key)}
              role="button"
              tabIndex={0}
              aria-label={`entity ${label}, open delayed risk context`}
            >
              <title>{`${node.type} ${node.entity_key}${
                node.in_seed_component ? "\nin seed community" : ""
              }\nclick → delayed EntityRisk`}</title>
              <rect
                x={-46}
                y={-11}
                width={92}
                height={22}
                rx={6}
                fill={fill}
                opacity={node.in_seed_component ? 1 : 0.55}
              />
              <text className="node-label" y={4}>
                {label}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="graph-legend muted small">
        <span><i className="dot dot-seed" /> seed transaction</span>
        <span><i className="dot dot-member" /> community member</span>
        <span><i className="dot dot-other" /> window neighbor</span>
        <span><i className="dot dot-card" /> CARD</span>
        <span><i className="dot dot-device" /> DEVICE</span>
        <span><i className="dot dot-address" /> ADDRESS</span>
        <span>click an entity chip → delayed risk context</span>
      </div>
    </div>
  );
}

export const GraphView = memo(GraphViewInner);
