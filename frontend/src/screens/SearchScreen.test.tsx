import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SearchScreen } from "../screens/SearchScreen";
import { stubFetch } from "../test/helpers";
import { queue } from "../test/fixtures";

describe("Screen 1 — search / queue", () => {
  it("renders real queue rows with score, band badge and model version", async () => {
    stubFetch([{ pattern: /^\/api\/transactions\??.*$/, body: queue }]);
    render(<SearchScreen />);
    expect(await screen.findByTestId("queue-table")).toBeInTheDocument();
    expect(screen.getByText("2987004")).toBeInTheDocument();
    expect(screen.getByText("0.9700")).toBeInTheDocument();
    expect(screen.getAllByTestId("band-badge")[0]).toHaveTextContent("CRITICAL");
    expect(screen.getAllByText("fraud_xgb_v1-9e2978c").length).toBeGreaterThan(0);
    expect(screen.getByText("available")).toBeInTheDocument();
  });

  it("shows an honest empty state", async () => {
    stubFetch([
      { pattern: /^\/api\/transactions\??.*$/, body: { transactions: [], count: 0 } },
    ]);
    render(<SearchScreen />);
    expect(await screen.findByText("No scored transactions match.")).toBeInTheDocument();
  });

  it("surfaces a 503 with the backend detail", async () => {
    stubFetch([
      {
        pattern: /^\/api\/transactions\??.*$/,
        status: 503,
        body: { detail: "transaction storage unavailable (uninitialized)" },
      },
    ]);
    render(<SearchScreen />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    expect(screen.getByTestId("error-detail")).toHaveTextContent(
      "transaction storage unavailable",
    );
  });
});
