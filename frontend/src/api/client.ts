/** Centralized fetch layer: base URL, error normalization, JSON parsing. No component may call fetch() directly. */

/** Normalized API failure. `detail` is the backend's human-readable message (FastAPI {"detail": ...}); displayed verbatim in the UI. */
export class ApiError extends Error {
  status: number;
  detail: string;
  kind: "http" | "network";

  constructor(status: number, detail: string, kind: "http" | "network" = "http") {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.kind = kind;
  }
}

/** Dev: Vite proxies /api -> FastAPI (prefix stripped). Demo/prod: the app is
 *  served BY FastAPI, so same-origin relative URLs are the API itself. */
export const API_BASE = import.meta.env.DEV ? "/api" : "";

/** Backend ids (case_id, decision_id, label_id) are int64 (uuid-derived,
 *  ~2^62). Numbers above 2^53 lose precision in JS JSON.parse — a rounded id
 *  then 404s on follow-up requests. Parse those fields as strings instead;
 *  the frontend treats them as opaque identifiers. */
const BIG_ID_KEYS = "case_id|decision_id|label_id";
const BIG_ID_RE = new RegExp(`"(${BIG_ID_KEYS})":\\s*(\\d{10,})`, "g");

function parseLossless(text: string): unknown {
  return JSON.parse(text.replace(BIG_ID_RE, '"$1":"$2"'));
}

function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    // FastAPI validation errors: [{loc,msg,...}]
    if (Array.isArray(d)) {
      return d
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .join("; ");
    }
    return String(d);
  }
  return fallback;
}

export async function apiGet<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
  } catch (err) {
    throw new ApiError(0, `API unreachable (${String(err)})`, "network");
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = parseLossless(await res.text());
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, extractDetail(body, `HTTP ${res.status}`));
  }
  return parseLossless(await res.text()) as T;
}

export async function apiSend<T>(
  path: string,
  method: "POST" | "PATCH",
  payload: unknown,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    throw new ApiError(0, `API unreachable (${String(err)})`, "network");
  }
  let body: unknown = null;
  try {
    body = parseLossless(await res.text());
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    throw new ApiError(res.status, extractDetail(body, `HTTP ${res.status}`));
  }
  return body as T;
}
