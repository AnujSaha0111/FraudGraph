import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EntityRiskPanel, EntityRiskResult } from "../components/EntityRiskPanel";
import { stubFetch } from "../test/helpers";
import type { EntityRisk } from "../api/types";

const base: EntityRisk = {
  entity_type: "ADDRESS",
  entity_key: "315",
  as_of_ts: 12876275,
  min_label_lag_days: 7,
  eligible_boundary: "2018-04-22T00:44:35",
  entity_fraud_count: 2,
  entity_total_labeled_count: 5,
  fraud_rate: 0.4,
  computed_at: "2026-08-23T10:00:00",
  note: "delayed investigation context; NOT a model feature",
};

describe("Screen 4 — delayed entity-risk context", () => {
  it("renders point-in-time fields and the context-only disclaimer", async () => {
    stubFetch([{ pattern: /^\/api\/entities\//, body: base }]);
    render(<EntityRiskResult entityType="ADDRESS" entityKey="315" asOfTs={12876275} />);
    expect(await screen.findByTestId("entityrisk-result")).toBeInTheDocument();
    expect(screen.getByText("ADDRESS:315")).toBeInTheDocument();
    expect(screen.getByText("7 days")).toBeInTheDocument();
    expect(screen.getByText("2018-04-22 00:44:35 UTC")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText(/40\.0%/)).toBeInTheDocument();
    const disclaimer = screen.getByText(/Delayed-label context only/i);
    expect(disclaimer).toHaveTextContent("not");
    expect(disclaimer).toHaveTextContent("does not influence any score");
  });

  it("reports insufficient historical evidence honestly", async () => {
    stubFetch([
      {
        pattern: /^\/api\/entities\//,
        body: { ...base, entity_total_labeled_count: 0, fraud_rate: null },
      },
    ]);
    render(<EntityRiskResult entityType="ADDRESS" entityKey="315" asOfTs={12876275} />);
    expect(await screen.findByTestId("insufficient-evidence-note")).toHaveTextContent(
      /Insufficient historical evidence/,
    );
  });

  it("shows an honest empty state when an entity has no linked transactions", () => {
    // panel-level: no entities at all
    render(<EntityRiskPanel entities={[]} asOfTs={1} />);
    expect(screen.getByText(/No CARD\/DEVICE\/ADDRESS entities/)).toBeInTheDocument();
  });

  it("surfaces backend errors (e.g. bad entity_type -> 422)", async () => {
    stubFetch([
      {
        pattern: /^\/api\/entities\//,
        status: 422,
        body: { detail: "entity_type must be CARD|DEVICE|ADDRESS" },
      },
    ]);
    render(<EntityRiskResult entityType="ADDRESS" entityKey="x" asOfTs={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Coverage limitation");
    expect(screen.getByTestId("error-detail")).toHaveTextContent(
      "entity_type must be CARD|DEVICE|ADDRESS",
    );
  });
});
