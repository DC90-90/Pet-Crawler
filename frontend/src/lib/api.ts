// Thin fetch wrapper: cookie auth, CSRF double-submit, JSON, error normalization.

const BASE = import.meta.env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  status: number;
  detail: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  errors?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  constructor(status: number, detail: string, errors?: any) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.errors = errors;
  }
}

function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(name + "="))
    ?.split("=")[1];
}

interface Opts {
  method?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body?: any;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  raw?: boolean; // for FormData / non-JSON bodies
}

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  const isMutation = !["GET", "HEAD", "OPTIONS"].includes(method);

  let body: BodyInit | undefined;
  if (opts.raw) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers["Content-Type"] = "application/json";
  }

  if (isMutation) {
    const csrf = readCookie("csrf_token");
    if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);
  }

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body,
    credentials: "include",
    signal: opts.signal,
  });

  if (res.status === 204) return undefined as T;

  const ct = res.headers.get("content-type") ?? "";
  const payload = ct.includes("application/json")
    ? await res.json().catch(() => null)
    : await res.text();

  if (!res.ok) {
    const detail =
      (payload && typeof payload === "object" && payload.detail) ||
      (typeof payload === "string" && payload) ||
      `Request failed (${res.status})`;
    throw new ApiError(res.status, detail, payload?.errors);
  }
  return payload as T;
}

export const apiBase = BASE;
