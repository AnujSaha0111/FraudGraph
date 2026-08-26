import { vi } from "vitest";

export interface MockRoute {
  pattern: RegExp;
  body: unknown;
  status?: number;
  method?: "GET" | "POST" | "PATCH";
}

export function stubFetch(routes: MockRoute[]): ReturnType<typeof vi.fn> {
  const mock = vi.fn(async (input: string | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const method = (init?.method ??
      (typeof input !== "string" ? input.method : undefined) ??
      "GET") as string;
    for (const r of routes) {
      if (r.method && r.method !== method) continue;
      if (r.pattern.test(path)) {
        return new Response(JSON.stringify(r.body), {
          status: r.status ?? 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ detail: "not mocked: " + path }), {
      status: 500,
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
