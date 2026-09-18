/**
 * Backend API client.
 *
 * Every call goes through `request()` so failures surface as a single Error
 * shape the UI can render, and the base URL is resolved once from the
 * environment (REACT_APP_BACKEND_URL) with a localhost fallback.
 */
const BASE_URL = (process.env.REACT_APP_BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const API = `${BASE_URL}/api`;

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(`${API}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(
      "Cannot reach the ECR Assistant backend. Is it running on " + BASE_URL + "?",
      0,
      error.message
    );
  }
  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = isJson ? payload?.detail : payload;
    throw new ApiError(
      typeof detail === "string" ? detail : `Request failed (${response.status})`,
      response.status,
      detail
    );
  }
  return payload;
}

const id = (ecrId) => encodeURIComponent(ecrId);

export const api = {
  baseUrl: BASE_URL,

  health: () => request("/health"),
  dashboardStats: () => request("/dashboard/stats"),

  listEcrs: (search) => request(`/ecr${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  getEcr: (ecrId) => request(`/ecr/${id(ecrId)}`),
  createEcr: (payload) => request("/ecr", { method: "POST", body: payload }),

  analyze: (ecrId, options = {}) => request(`/ecr/${id(ecrId)}/analyze`, { method: "POST", body: options }),
  analysis: (ecrId) => request(`/ecr/${id(ecrId)}/analysis`),
  approve: (ecrId, decision) => request(`/ecr/${id(ecrId)}/approve`, { method: "POST", body: decision }),
  reportUrl: (ecrId, format) => `${API}/ecr/${id(ecrId)}/report?format=${format}`,

  ask: (ecrId, question) => request(`/ecr/${id(ecrId)}/ask`, { method: "POST", body: { question } }),
  feedback: (payload) => request("/feedback", { method: "POST", body: payload }),

  /**
   * Subscribe to the live agent event stream for a workflow.
   * Returns an unsubscribe function.
   */
  streamWorkflow(workflowId, { onAgent, onDone, onError } = {}) {
    const source = new EventSource(`${API}/workflows/${workflowId}/stream`);
    source.addEventListener("agent", (event) => onAgent?.(JSON.parse(event.data)));
    source.addEventListener("done", (event) => {
      onDone?.(JSON.parse(event.data));
      source.close();
    });
    source.onerror = () => {
      onError?.(new ApiError("Lost the live connection to the workflow", 0));
      source.close();
    };
    return () => source.close();
  },
};

export default api;
