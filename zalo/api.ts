/**
 * Client gọi backend HomeValue AI với timeout + retry.
 */
import { config } from "./config.ts";

export interface ChatResult {
  answer: string;
  context: Record<string, unknown> | null;
  intent?: string;
  missingFields?: string[];
}

export type ChatStatus = "ok" | "timeout" | "error";

export interface ChatResponse {
  status: ChatStatus;
  result?: ChatResult;
}

async function fetchWithTimeout(url: string, body: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function callChat(
  message: string,
  context: Record<string, unknown> | null,
): Promise<ChatResponse> {
  const url = `${config.apiBase}${config.chatPath}`;
  const body = JSON.stringify({ message, context, style: "advisor" });

  for (let attempt = 0; attempt <= config.apiRetries; attempt++) {
    try {
      const resp = await fetchWithTimeout(url, body, config.apiTimeoutMs);
      if (!resp.ok) {
        // 5xx có thể thử lại; 4xx thì trả lỗi luôn
        if (resp.status >= 500 && attempt < config.apiRetries) continue;
        return { status: "error" };
      }
      const data = (await resp.json()) as {
        answer?: string;
        context?: Record<string, unknown> | null;
        intent?: string;
        missing_fields?: string[];
      };
      return {
        status: "ok",
        result: {
          answer: data.answer || "",
          context: data.context ?? null,
          intent: data.intent,
          missingFields: data.missing_fields,
        },
      };
    } catch (err) {
      const aborted = err instanceof Error && err.name === "AbortError";
      if (attempt < config.apiRetries) continue;
      return { status: aborted ? "timeout" : "error" };
    }
  }
  return { status: "error" };
}

export async function healthCheck(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(`${config.apiBase}/health`, { signal: controller.signal });
    clearTimeout(timer);
    return resp.ok;
  } catch {
    return false;
  }
}
