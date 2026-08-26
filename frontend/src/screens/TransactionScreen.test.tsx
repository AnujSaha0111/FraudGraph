import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TransactionScreen } from "../screens/TransactionScreen";
import { stubFetch } from "../test/helpers";
import { evidence, explanation, graph, risk } from "../test/fixtures";

const API = "/api";

function stubAll(overrides: { pattern: RegExp; body: unknown; status?: number }[] = []) {
  const base = [
    { pattern: new RegExp(`^${API}/transactions/2987004/risk/explanation`), body: explanation },
    { pattern: new RegExp(`^${API}/transactions/2987004/risk$`), body: risk },
    { pattern: new RegExp(`^${API}/transactions/2987004/evidence$`), body: evidence },
    { pattern: new RegExp(`^${API}/transactions/2987004/graph$`), body: graph },
    { pattern: new RegExp(`^${API}/cases$`), body: { cases: [], count: 0 } },
  ];
  return stubFetch([...overrides, ...base]);
}

describe("Screen 2 — transaction detail", () => {
  it("renders risk summary and keeps MODEL EXPLANATION separate from evidence", async () => {
    stubAll();
    render(<TransactionScreen id={2987004} />);

    expect(await screen.findByTestId("risk-score")).toHaveTextContent("0.9123");
    expect(screen.getAllByTestId("band-badge")[0]).toHaveTextContent("CRITICAL");
    expect(screen.getByText(/model fraud_xgb_v1-9e2978c/)).toBeInTheDocument();
    expect(screen.getByText(/not a calibrated probability/i)).toBeInTheDocument();
    expect(await screen.findByTestId("explanation-table")).toBeInTheDocument();

    // explicit separation language
    expect(screen.getByText(/MODEL EXPLANATION/i)).toBeInTheDocument();
    expect(screen.getByText(/distinct from the model score above/i)).toBeInTheDocument();
  });

  it("renders deterministic evidence records with audit trail", async () => {
    stubAll();
    render(<TransactionScreen id={2987004} />);
    const cards = await screen.findAllByTestId("evidence-card");
    expect(cards.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Amount deviation for card")).toBeInTheDocument();
    expect(screen.getByText("+3.1σ above prior mean.")).toBeInTheDocument();
    expect(screen.getByText("high", { selector: ".sev-high" })).toBeInTheDocument();
  });

  it("renders NO_RELATIONAL_EVIDENCE honestly when it is the only record", async () => {
    stubAll([
      {
        pattern: /\/evidence$/,
        body: {
          ...evidence,
          evidence: [evidence.evidence[1]],
        },
      },
    ]);
    render(<TransactionScreen id={2987004} />);
    expect(await screen.findByTestId("no-relational-evidence")).toHaveTextContent(
      "No relational evidence fired",
    );
  });

  it("renders the graph from real backend nodes and shows pruning metadata", async () => {
    stubAll();
    render(<TransactionScreen id={2987004} />);
    const svg = await screen.findByTestId("graph-svg");
    // seed + neighbor + entity = 3 nodes drawn
    expect(svg.querySelectorAll(".graph-node").length).toBe(3);
    expect(svg.querySelectorAll(".graph-edge").length).toBe(2);
    expect(svg.querySelector(".node-seed")).toBeTruthy();
    expect(svg.textContent).toContain("ADDRESS:315");
    expect(await screen.findByTestId("graph-meta")).toHaveTextContent(
      /hub-pruned: CARD:999 \(deg 4200\)/,
    );
    expect(screen.getByTestId("graph-meta").textContent ?? "").toContain(
      "params_hash abcdef012345",
    );
  });
});
