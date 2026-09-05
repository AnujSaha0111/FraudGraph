# FraudGraph

**Problem:** payment fraud investigation fails when analysts see only a risk score - they need the network around a transaction, auditable evidence, and an immutable decision trail.

**What FraudGraph does:** a local-first transaction risk + coordinated-risk investigation system that combines a frozen XGBoost predictor over 438 leakage-gated features with an entity graph used as **investigation infrastructure**, deterministic hash-verified evidence and a human-controlled case workflow with immutable decisions.

> Detect the transaction. Expose the network. Explain the risk.

It is deliberately **not** a GNN fraud detector, has **no LLM** in the loop, and uses **no graph database** — every one of those exclusions was decided on measured evidence (see [Architectural decisions](#architectural-decisions)).

## How it works

```text
IEEE-CIS / derived data → Leakage-safe feature pipeline → Frozen XGBoost (438)
                               → Risk API → Investigator UI
                                  ├── Model explanation (top-k attribution only)
                                  ├── Entity graph (window −14d/+2d, params_hash)
                                  ├── Deterministic evidence (evidence_hash + provenance)
                                  ├── EntityRisk context (as-of, 7-day label lag)
                                  └── Case management
                                        ↓ Immutable decision → Label
```

The prediction path never receives graph/evidence/case data; the
investigation path is read-only with respect to truth.

**What evidence does NOT mean:** an evidence record (or the risk score, or a feature attribution) is never proof of fraud - only a human case decision, backed by acknowledged deterministic evidence and recorded immutably, establishes an outcome.

## The three layers

| Layer                          | What it gives the analyst                                                                                                                                                   | What it does NOT claim                                                            |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **Model risk** (`app/risk/`)   | Frozen XGBoost over 438 features; PR-AUC 0.7367 on a chronological test split; batch-scored queue                                                                           | The score is **not calibrated** fraud probability; bands are heuristic thresholds |
| **Explanation**                | Top-k per-transaction feature contributions (SHAP TreeExplainer, deterministic gain fallback)                                                                               | An attribution explains the _score_, it is **not evidence**                       |
| **Evidence** (`app/evidence/`) | 8 deterministic record types (amount deviation, unusual hour, velocity, shared device, community stats, connected high-risk, …) with canonical `evidence_hash` + provenance | Evidence structures the investigation; it never proves fraud by itself            |

### Graph investigation

Transactions connect to CARD / DEVICE / ADDRESS entities. A hybrid index (in-memory adjacency built once at startup + params-hash expansion cache) answers windowed neighborhood queries (−14d/+2d) deterministically, with hub pruning (>1000-degree entities ignored) and neighbor caps recorded per query. Connected components over the induced subgraph surface coordinated activity. Graph v1 parameters are pinned; every response carries a `params_hash`.

### Deterministic evidence

Each evidence record is generated from fixed thresholds over the transaction's graph community and entity history, canonicalized (`sorted-key JSON`), and hashed (SHA-256). Hashes exclude runtime timestamps, so identical inputs reproduce byte-identical hashes — verified by tests. When nothing qualifies, the engine says so honestly with `NO_RELATIONAL_EVIDENCE`. Evidence engine
version: `v1`.

### Case management

`NEW → INVESTIGATING ⇄ ESCALATED → CONFIRMED_FRAUD / FALSE_POSITIVE → CLOSED`. Decisions are append-only and immutable (a second terminal decision returns 409); each decision acknowledges specific evidence ids and creates exactly one label. Every action lands in an append-only history.

### EntityRisk context

`GET /entities/{type}/{key}/risk?as_of_ts=…` aggregates labels for an entity with a delayed-label rule: a label counts only if `arrival_at ≤ T - MIN_LABEL_LAG_DAYS` (7 days). It is point-in-time investigation context - **not a predictive model feature** and never wired into the scoring pipeline.

### Frontend

React 18 + Vite + TypeScript dashboard: risk queue → transaction detail (score, explanation, graph, evidence) → case review → immutable decision, plus a cases list. In dev mode Vite proxies `/api` to FastAPI; in demo mode FastAPI serves the built bundle at `/`.

## Data availability & licensing

**The IEEE-CIS Fraud Detection dataset is NOT included in this repository and is NOT redistributed by it.** The data was provided by Vesta Corporation via the Kaggle competition and is governed by its own [competition/distribution terms](https://www.kaggle.com/competitions/ieee-fraud-detection/rules), which every user must accept at the source. The repository's code license and the dataset's distribution terms are separate things.

What this means in practice:

- You can inspect, install, test (public suite), and develop FraudGraph without the dataset - see the Quickstart below.
- The **full real-data investigation flow** (scoring queue, graph,evidence, demo walkthrough) requires locally prepared artifacts that you generate after obtaining the dataset from an authorized source.
- `data/synthetic/` ships with the repository: those are fully synthetic, fixed-seed planted-ring fixtures generated by in-repo code(`src/data/synthetic_rings.py`) and never presented as real fraud data.

Run the setup checker at any time; it reports exactly what is present, what is regenerable, and what is missing:

```powershell
python scripts/setup_data.py            # status + guidance (never downloads anything)
python scripts/setup_data.py --build    # run existing generators where inputs are available
```

## Quickstart

Prerequisites: Python 3.13, Node ≥ 20 (frontend build).

```powershell
# A. Clone repository
git clone https://github.com/AnujSaha0111/FraudGraph && cd fraudgraph

# B. Install backend dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# C. Install frontend dependencies + build
npm --prefix frontend ci
npm --prefix frontend run build        # emits frontend/dist/

# D. Run public/data-free validation (no dataset needed)
ruff check app tests
python -m pytest tests -q              # 107 pass; real-data tests skip with reason

# E. Obtain IEEE-CIS data independently if legally permitted
# - Kaggle account -> accept competition rules -> download
# - train_transaction.csv + train_identity.csv ->
# - place them under  ./IEEE-CIS Fraud Detection/
# -  (or use your own Kaggle CLI credentials; nothing is auto-downloaded)

# F. Prepare local real-data artifacts
python scripts/setup_data.py --build   # runs existing generators; reports gaps
# -  NOTE: production_features.parquet has no committed generator yet
# -  scripts/setup_data.py reports this explicitly if it is missing.

# G. Run real-data bootstrap (schema + batch scores + demo evidence + links)
python scripts/bootstrap_db.py

# H. Start application
uvicorn app.main:app                   # http://127.0.0.1:8000/#/

# I. Investigation / demo flow
python scripts/run_demo.py --dry-run   # full environment validation (23 checks)
```

Configuration: copy `.env.example` → `.env`; every `FG_*` variable is
optional with working defaults. No secrets are ever committed.

## Testing

FraudGraph has two explicit validation modes; the mode is printed at the top
of every pytest run:

```powershell
# A. Public / data-free validation (default; no dataset needed)
ruff check app tests
python -m pytest tests -q                  # 107 pass; real-data tests SKIP
                                           # with an explicit reason

# B. Full real-data validation (after Quickstart steps E–G)
set FG_REAL_DATA=1                        # PowerShell: $env:FG_REAL_DATA = "1"
python -m pytest tests -q                  # complete suite: 143 tests
```

Real-data integration tests are marked `real_data` and run **only** when
`FG_REAL_DATA=1` is set AND the locally prepared artifacts exist — otherwise
they skip with a reason pointing at `scripts/setup_data.py`. Assertions are
identical in both modes; nothing is weakened or hidden.

```powershell
npm --prefix frontend run typecheck        # tsc clean
npm --prefix frontend test                 # vitest unit tests
npm --prefix frontend run build            # production bundle
```

CI (`.github/workflows/ci.yml`) runs mode A on every push (lint + public
pytest, no dataset required) plus the frontend job (typecheck/test/build).
Mode B remains available locally for full real-data validation.
CI never downloads competition data and contains no secrets.

Reproducibility check (model reload equivalence, max diff 0.0; needs only the
shipped frozen model):

```powershell
python scripts/reproducibility.py          # rewrites reports/reproducibility.json
```

## Architectural decisions

- **No GNN:** GraphSAGE lost to XGBoost (test PR-AUC 0.627 vs 0.731) even in a favorable transductive setup — rejected on evidence; zero GNN code in `app/`.
- **No LLM:** seven options were evaluated against resource/latency/grounding constraints; none passed; hallucination is not reliably containable; deterministic evidence is already concise — intentionally rejected, zero `app/llm` code (enforced by `tests/test_demo_runner.py`).
- **No graph database:** DuckDB file mode + Parquet caches benchmarked as sufficient; hybrid in-memory adjacency + params-hash caching.
- **No naive graph features:** cumulative-degree features looked helpful (+≈0.009 PR-AUC) until a row-shuffled control reproduced the same gain and diagnostics showed time/volume proxy behavior (ρ up to ~0.69) - banned; the shuffled-control discipline is permanent and enforced by tests. Only validated deviation/windowed families entered the frozen artifact (+0.0095, CI low > 0). The graph lives where it earns its keep:investigation.

## Limitations

- Risk score is not calibrated; bands are heuristic thresholds.
- Modest relational gains (+0.0095) — honest, CI-backed, not oversold.
- 75.6% of transactions lack identity fields; entity reasoning covers the joined subset (missing coverage returns HTTP 422, not a fake score).
- EntityRisk requires ≥7 days of label lag; early history shows an honest "insufficient historical evidence" state.
- Single-machine DuckDB store; batch-precomputed scores; no streaming.
- Explanation uses SHAP when installed; otherwise a documented deterministic gain-based fallback (`app/risk/explain.py`).
