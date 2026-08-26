import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CaseScreen } from "../screens/CaseScreen";
import { stubFetch } from "../test/helpers";
import { caseDetail } from "../test/fixtures";

const API = "/api";
const CASE_URL = new RegExp(`^${API}/cases/42$`);

describe("Screen 3 — case review", () => {
  it("renders state, model risk, evidence ids, notes and history", async () => {
    stubFetch([{ pattern: CASE_URL, body: caseDetail }]);
    render(<CaseScreen id={42} />);
    expect(await screen.findByTestId("case-status")).toHaveTextContent(
      "INVESTIGATING",
    );
    expect(screen.getByText(/0.9123/)).toBeInTheDocument();
    expect(screen.getByText(/11111111-2222-3333-4444-555555555555/)).toBeInTheDocument();
    expect(screen.getByText("amount looks anomalous")).toBeInTheDocument();
    const rows = screen.getByTestId("history-table");
    expect(rows).toHaveTextContent("CREATED");
    expect(rows).toHaveTextContent("NEW → INVESTIGATING");
  });

  it("offers exactly the legal PATCH transitions for INVESTIGATING", async () => {
    stubFetch([{ pattern: CASE_URL, body: caseDetail }]);
    render(<CaseScreen id={42} />);
    const strip = await screen.findByTestId("transitions");
    expect(strip).toHaveTextContent("ESCALATED");
    // decision states are NOT offered as plain transitions — they are driven
    // exclusively by the immutable-decision form
    expect(strip.textContent).not.toContain("CONFIRMED_FRAUD");
    expect(strip.textContent).not.toContain("FALSE_POSITIVE");
    expect(strip.textContent).not.toContain("CLOSED");
  });

  it("displays a backend 409 state-machine conflict verbatim", async () => {
    stubFetch([
      {
        pattern: CASE_URL,
        method: "PATCH",
        status: 409,
        body: { detail: "illegal transition INVESTIGATING -> CLOSED" },
      },
      { pattern: CASE_URL, body: caseDetail },
    ]);
    render(<CaseScreen id={42} />);
    await screen.findByTestId("transitions");
    await userEvent.type(
      screen.getByPlaceholderText(/analyst-yourname/),
      "analyst-1",
    );
    await userEvent.click(screen.getByRole("button", { name: "ESCALATED" }));
    const banner = await screen.findByTestId("action-error");
    expect(banner).toHaveTextContent(
      "Rejected: illegal transition INVESTIGATING -> CLOSED",
    );
  });

  it("decision form requires evidence + acknowledgement; posts when ready", async () => {
    const captured: Record<string, unknown>[] = [];
    const mock = vi.fn(async (input: string | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/decision") && init?.body) {
        captured.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({ decision_id: "7" }), { status: 201 });
      }
      return new Response(JSON.stringify(caseDetail), { status: 200 });
    });
    vi.stubGlobal("fetch", mock);

    render(<CaseScreen id={42} />);
    const submit = await screen.findByRole("button", {
      name: /Submit CONFIRMED_FRAUD/,
    });
    expect(submit).toBeDisabled();

    // tick evidence checkbox
    screen.getAllByRole("checkbox")[0].click();

    // tick immutable acknowledgement (label.ack input)
    (document.querySelector("label.ack input") as HTMLInputElement).click();

    await userEvent.type(
      screen.getByPlaceholderText(/analyst-yourname/),
      "lead-1",
    );

    const ready = screen.getByRole("button", { name: /Submit CONFIRMED_FRAUD/ });
    await waitFor(() => expect(ready).not.toBeDisabled());
    await userEvent.click(ready);

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    expect(captured[0]).toMatchObject({
      decision: "CONFIRMED_FRAUD",
      actor: "lead-1",
      evidence_ids: ["11111111-2222-3333-4444-555555555555"],
    });
  });

  it("shows terminal read-only notice and label when decided", async () => {
    stubFetch([
      {
        pattern: CASE_URL,
        body: {
          ...caseDetail,
          status: "CONFIRMED_FRAUD",
          decisions: [
            {
              decision_id: "7",
              reviewer: "lead-1",
              decision: "CONFIRMED_FRAUD",
              decided_at: "2026-08-23T10:00:00",
              notes: "confirmed",
              evidence_ids: ["11111111"],
              request_id: "req-1",
            },
          ],
          label: {
            label_id: "99",
            value: 1,
            arrival_at: "2026-08-23T10:00:00",
            effective_at: "2026-08-23T10:00:00",
            source: "reviewer",
          },
        },
      },
    ]);
    render(<CaseScreen id={42} />);
    expect(await screen.findByTestId("case-status")).toHaveTextContent(
      "CONFIRMED_FRAUD",
    );
    expect(await screen.findByTestId("decision-record")).toBeInTheDocument();
    expect(screen.getByTestId("label-record")).toHaveTextContent("1 (fraud)");
    expect(screen.getByText(/permanent|immutable/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Submit/ })).toBeNull();
  });
});
