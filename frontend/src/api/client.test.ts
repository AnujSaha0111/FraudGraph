import { describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "../api/client";

describe("api client", () => {
  it("parses JSON on 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
      ),
    );
    await expect(apiGet("/health")).resolves.toEqual({ ok: true });
  });

  it("normalizes FastAPI string detail (404)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "transaction not found" }), {
          status: 404,
        }),
      ),
    );
    const err = await apiGet("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).detail).toBe("transaction not found");
  });

  it("joins FastAPI validation arrays (422)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            detail: [{ loc: ["query", "band"], msg: "invalid band" }],
          }),
          { status: 422 },
        ),
      ),
    );
    const err = await apiGet("/x").catch((e) => e) as ApiError;
    expect(err.status).toBe(422);
    expect(err.detail).toContain("invalid band");
  });

  it("falls back to HTTP status text when body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("storage exploded", { status: 503 })),
    );
    const err = await apiGet("/x").catch((e) => e) as ApiError;
    expect(err.status).toBe(503);
    expect(err.detail).toBe("HTTP 503");
  });

  it("maps fetch rejection to a network ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("connection refused");
      }),
    );
    const err = await apiGet("/x").catch((e) => e) as ApiError;
    expect(err.kind).toBe("network");
    expect(err.status).toBe(0);
    expect(err.detail).toContain("API unreachable");
  });

  it("parses int64 ids losslessly as strings (no JS precision rounding)", async () => {
    // Raw wire bytes exactly as FastAPI emits them (full-precision digits);
    // building this via JSON.stringify would lose precision before the
    // client ever sees it — which is precisely the bug being regression-tested.
    const wire =
      '{"case_id": 3683860570081635303, ' +
      '"decision_id": 3960357353040133516, ' +
      '"label_id": 2245482363254998431, ' +
      '"transaction_id": 3011051}';
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(wire, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const body = (await apiGet("/cases/x")) as Record<string, unknown>;
    expect(body.case_id).toBe("3683860570081635303");
    expect(body.decision_id).toBe("3960357353040133516");
    expect(body.label_id).toBe("2245482363254998431");
    expect(body.transaction_id).toBe(3011051); // small ints stay numbers
  });
});
