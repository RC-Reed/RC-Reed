/** Typed API client.

The token lives in localStorage: this is a self-hosted, single-operator app
served from the same origin as its API, so a cookie buys nothing extra and
costs a CSRF story. Any 401 clears it and bounces to the login screen. */

const TOKEN_KEY = "lifeos.token";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode — the session just won't persist across reloads */
  }
}

type Options = {
  method?: string;
  body?: unknown;
  formData?: FormData;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(`/api/v1${path}`, {
    method: options.method ?? (body ? "POST" : "GET"),
    headers,
    body,
  });

  if (response.status === 401) {
    setToken(null);
    if (!location.pathname.startsWith("/login")) location.assign("/login");
    throw new ApiError("Session expired", 401);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (Array.isArray(payload.detail)) {
        // FastAPI validation errors arrive as a list of field problems.
        detail = payload.detail
          .map((item: { loc?: string[]; msg?: string }) =>
            `${item.loc?.slice(1).join(".") ?? "field"}: ${item.msg ?? "invalid"}`,
          )
          .join("; ");
      }
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body });
export const del = (path: string) => api<void>(path, { method: "DELETE" });

export function upload<T>(path: string, file: File): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  return api<T>(path, { method: "POST", formData });
}
