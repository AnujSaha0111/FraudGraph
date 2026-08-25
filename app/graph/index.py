# Graph index — hybrid caching strategy
# Architectural contract for the entity graph service:
# - link tables are persisted upstream (DuckDB/Parquet) by a rebuildable step;
# - an in-memory adjacency is built once at startup (~7 s / 37 MB at demo scale on the shipped 254,777-link table);
# - expansions are cached under a hash of (params + seed) so identical requests are deterministic and instant.
# No investigation business logic lives here

from bisect import bisect_left

import numpy as np

GRAPH_VERSION = "v1"

def _cache_key(*parts) -> str:
    import hashlib
    import json
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

def params_hash(back_s: int, fwd_s: int, hub_degree_max: int, neighbor_cap: int, depth: int = 1, graph_version: str = GRAPH_VERSION) -> str:
    import hashlib
    import json
    canonical = json.dumps({"back_s": int(back_s), "fwd_s": int(fwd_s), "hub_degree_max": int(hub_degree_max), "neighbor_cap": int(neighbor_cap), "depth": int(depth), "graph_version": str(graph_version)}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]

class GraphIndex:
    # In-memory adjacency over transaction-entity links.
    # Built from columnar link data (no pandas required at this layer). Deterministic: link order sorted by ts (mergesort stable), window queries use bisect_left for half-open [t-back, t+fwd), neighbor cap takes most recent within window (timestamp then txn_pos stable order).

    def __init__(self, entity_types, entity_keys, txn_positions, link_ts,
                 all_ts, hub_degree_max: int = 1000):
        self.all_ts = np.asarray(all_ts, dtype=np.int64)
        self.hub_degree_max = int(hub_degree_max)
        self.graph_version = GRAPH_VERSION
        self._ent: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
        self._txn_ents: dict[int, list[tuple[str, str]]] = {}
        self._cache: dict[str, frozenset[int]] = {}
        self._degrees: dict[tuple[str, str], int] = {}
        self._hub_pruned: set[tuple[str, str]] = set()

        degrees: dict[tuple[str, str], int] = {}
        for etype, key in zip(entity_types, entity_keys):
            k = (str(etype), str(key))
            degrees[k] = degrees.get(k, 0) + 1
        self._degrees = dict(degrees)
        kept = {k for k, d in degrees.items()
                if d <= self.hub_degree_max}
        self._hub_pruned = {k for k, d in degrees.items() if d > self.hub_degree_max}

        order = np.argsort(np.asarray(link_ts, dtype=np.int64),
                           kind="mergesort")
        for i in order:
            k = (str(entity_types[i]), str(entity_keys[i]))
            if k not in kept:
                continue
            pos = int(txn_positions[i])
            ts = int(link_ts[i])
            entry = self._ent.get(k)
            if entry is None:
                self._ent[k] = ([pos], [ts])
            else:
                entry[0].append(pos)
                entry[1].append(ts)
            self._txn_ents.setdefault(pos, []).append(k)

        self._ent = {
            k: (np.asarray(p, dtype=np.int64), np.asarray(t, dtype=np.int64))
            for k, (p, t) in self._ent.items()}

    @property
    def n_entities(self) -> int:
        return len(self._ent)

    def seed_entities(self, txn_pos: int) -> list[tuple[str, str]]:
        return list(self._txn_ents.get(int(txn_pos), []))

    def windowed_neighbors(self, entity_type: str, entity_key: str,
                           t: int, back_s: int, fwd_s: int) -> np.ndarray:
        entry = self._ent.get((str(entity_type), str(entity_key)))
        if entry is None:
            return np.empty(0, dtype=np.int64)
        pos, ts = entry
        lo = bisect_left(ts, int(t) - back_s)
        hi = bisect_left(ts, int(t) + fwd_s)
        return pos[lo:hi]

    def expand(self, seed_txn_pos: int, back_s: int, fwd_s: int,
                neighbor_cap: int = 200) -> frozenset[int]:
        """Depth-1 community expansion (prototype semantics).

        Cached under hash(seed, back_s, fwd_s, cap, build signature).
        """
        key = _cache_key("expand", int(seed_txn_pos), int(back_s),
                          int(fwd_s), int(neighbor_cap), len(self._ent))
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        chosen: set[int] = {int(seed_txn_pos)}
        t = int(self.all_ts[seed_txn_pos])
        for etype, ekey in self.seed_entities(seed_txn_pos):
            neighbors = self.windowed_neighbors(etype, ekey, t,
                                                 back_s, fwd_s)
            if len(neighbors) > neighbor_cap:
                neighbors = neighbors[-neighbor_cap:]
            for j in neighbors:
                if int(j) != int(seed_txn_pos):
                    chosen.add(int(j))
        result = frozenset(chosen)
        self._cache[key] = result
        return result

    def expand_detailed(self, seed_txn_pos: int, back_s: int, fwd_s: int,
                        neighbor_cap: int = 200, depth: int = 1) -> dict:
        """Rich expansion with hub pruning and cap metadata."""
        if depth != 1:
            raise ValueError("only depth=1 supported")
        t = int(self.all_ts[seed_txn_pos])
        # record seed entities and their hub status
        seed_ents = self.seed_entities(seed_txn_pos)
        pruning = []
        chosen: set[int] = {int(seed_txn_pos)}
        edge_list = []  # (txn_pos, entity)
        for etype, ekey in seed_ents:
            k = (str(etype), str(ekey))
            deg = self._degrees.get(k, 0)
            is_hub = k in self._hub_pruned
            if is_hub:
                pruning.append({"entity_type": etype, "entity_key": ekey, "degree": int(deg), "pruned": True, "retained": 0})
                continue
            neighbors = self.windowed_neighbors(etype, ekey, t, back_s, fwd_s)
            original = len(neighbors)
            # exclude seed itself for counting but keep window logic
            # neighbors includes seed if seed within window (it always is)
            # we cap after filtering? Take most recent within window then add seed separately
            # deterministic: neighbors already sorted by ts
            if len(neighbors) > neighbor_cap:
                neighbors = neighbors[-neighbor_cap:]
            retained = [int(x) for x in neighbors if int(x) != int(seed_txn_pos)]
            for j in retained:
                chosen.add(int(j))
                edge_list.append((int(j), {"entity_type": etype, "entity_key": ekey}))
            pruning.append({"entity_type": etype, "entity_key": ekey, "degree": int(deg), "pruned": False, "original_neighbors_in_window": int(original), "retained_neighbors": len(retained), "cap_applied": len(neighbors) == neighbor_cap and original > neighbor_cap})
        return {
            "seed_txn_pos": int(seed_txn_pos),
            "seed_ts": t,
            "window": {"start": int(t - back_s), "end": int(t + fwd_s), "back_s": int(back_s), "fwd_s": int(fwd_s)},
            "chosen_positions": sorted(chosen),
            "edges": edge_list,
            "pruning": pruning,
            "depth": int(depth),
            "hub_degree_max": int(self.hub_degree_max),
            "neighbor_cap": int(neighbor_cap),
        }

    def hub_info(self, entity_type: str, entity_key: str) -> dict | None:
        k = (str(entity_type), str(entity_key))
        deg = self._degrees.get(k)
        if deg is None:
            return None
        return {"entity_type": str(entity_type), "entity_key": str(entity_key), "degree": int(deg), "is_hub": k in self._hub_pruned}
