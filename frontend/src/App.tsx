import { getHealth } from "./api/fraudgraph";
import { useAsyncData } from "./hooks/useAsyncData";
import { useRoute } from "./hooks/useRoute";
import { CasesScreen } from "./screens/CasesScreen";
import { CaseScreen } from "./screens/CaseScreen";
import { SearchScreen } from "./screens/SearchScreen";
import { TransactionScreen } from "./screens/TransactionScreen";

function BackendStatus() {
  const { data, error, loading } = useAsyncData(() => getHealth(), []);
  if (loading) return <span className="pill">checking backend…</span>;
  if (error || !data)
    return (
      <span className="pill pill-error">
        backend unreachable — uvicorn app.main:app --reload
      </span>
    );
  return (
    <span className={`pill ${data.storage === "ok" ? "pill-ok" : "pill-error"}`}>
      v{data.version} · env {data.env} · storage {data.storage}
    </span>
  );
}

export default function App() {
  const [route] = useRoute();
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <h1>
            Fraud<span>Graph</span>
          </h1>
          <span className="tagline">
            score → explain → investigate → decide · humans decide, system advises
          </span>
        </div>
        <BackendStatus />
      </header>

      <nav className="mainnav" aria-label="primary">
        <a href="#/" className={route.name === "home" ? "active" : ""}>
          Investigate
        </a>
        <a href="#/cases" className={route.name === "cases" ? "active" : ""}>
          Cases
        </a>
      </nav>

      <main>
        {route.name === "home" && <SearchScreen />}
        {route.name === "cases" && <CasesScreen />}
        {route.name === "tx" && <TransactionScreen key={route.id} id={route.id} />}
        {route.name === "case" && <CaseScreen key={route.id} id={route.id} />}
      </main>

      <footer className="muted small">
        IEEE-CIS benchmark demo · model scores are heuristic, evidence is
        deterministic, decisions are human and immutable. No GNN, no graph DB,
        no LLM in the truth path.
      </footer>
    </div>
  );
}
