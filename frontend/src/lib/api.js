import axios from "axios";
import { waitForReadRetry } from "./readRetry";

// Resolve API base URL safely:
// - If REACT_APP_BACKEND_URL is set AND its origin matches the page origin, use it.
// - Otherwise fall back to current page origin (the K8s ingress always serves /api on the same host).
// This makes the bundle resilient to custom domains (e.g. daleel.hrm-sa.com) where the
// baked-in env URL differs from the user-facing host.
function resolveApiBase() {
  const envUrl = (process.env.REACT_APP_BACKEND_URL || "").trim();
  if (typeof window === "undefined") {
    return envUrl ? `${envUrl}/api` : "/api";
  }
  if (envUrl) {
    try {
      const envOrigin = new URL(envUrl).origin;
      if (envOrigin === window.location.origin) {
        return `${envUrl}/api`;
      }
    } catch (_) {
      // fall through to same-origin
    }
  }
  return `${window.location.origin}/api`;
}

export const API_BASE = resolveApiBase();

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("daleel_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const config = err.config;
    if (config && (config.method || "get").toLowerCase() === "get"
        && err.response?.status === 503 && err.response?.data?.detail?.code === "price_query_timeout"
        && !config._readRetryAttempt && !config.signal?.aborted) {
      const session = localStorage.getItem("daleel_token");
      config._readRetryAttempt = true;
      await waitForReadRetry(config.signal);
      if (localStorage.getItem("daleel_token") !== session) return Promise.reject(err);
      return api.request(config);
    }
    if (err.response?.status === 401) {
      localStorage.removeItem("daleel_token");
      localStorage.removeItem("daleel_user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);

export default api;
