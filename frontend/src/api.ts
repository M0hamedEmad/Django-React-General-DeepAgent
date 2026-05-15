import type { Options, ReasoningEffort } from "./types";

export function csrf(): string {
  return document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] ?? "";
}

/** JSON fetch against the Django API. A 401 sends the browser to the login page. */
export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), ...(init.headers ?? {}) },
  });
  if (response.status === 401) {
    location.href = `/accounts/login/?next=${encodeURIComponent(location.pathname)}`;
    throw new Error("login required");
  }
  if (!response.ok) {
    const text = await response.text();
    let message = `${response.status} ${text}`;
    try {
      const body = JSON.parse(text);
      if (typeof body.error === "string") message = body.error;
    } catch {
      // Non-JSON failures (for example nginx errors) keep the status and body.
    }
    throw new Error(message);
  }
  return response.status === 204 ? (null as T) : response.json();
}

export function newId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

const OPTIONS_KEY = "chat-options";

export const DEFAULT_OPTIONS: Options = { model: "", agent: "", tools: ["web_search"], thinking: "instant", plan: false };

const EFFORTS = new Set<ReasoningEffort>(["instant", "medium", "high", "max"]);

function reasoningEffort(value: unknown): ReasoningEffort {
  // Migrate choices saved by the old Instant/Thinking boolean control.
  if (value === true) return "high";
  if (value === false) return "instant";
  return typeof value === "string" && EFFORTS.has(value as ReasoningEffort) ? (value as ReasoningEffort) : "instant";
}

export function loadOptions(): Options {
  try {
    const stored = JSON.parse(localStorage.getItem(OPTIONS_KEY) ?? "{}");
    return normalizeOptions(stored);
  } catch {
    return DEFAULT_OPTIONS;
  }
}

/** Remove options retired by the server without breaking old browser or thread data. */
export function normalizeOptions(value: Partial<Options>): Options {
  const options = { ...DEFAULT_OPTIONS, ...value };
  const tools = Array.isArray(options.tools)
    ? options.tools
    : DEFAULT_OPTIONS.tools;
  return { ...options, tools, thinking: reasoningEffort(options.thinking) };
}

export function saveOptions(options: Options) {
  try {
    localStorage.setItem(OPTIONS_KEY, JSON.stringify(options));
  } catch {
    /* private mode: the choice just does not stick */
  }
}
