import type {
  AskResponse,
  HealthResponse,
  SessionDetail,
  UploadResponse,
  WorkflowProgress,
} from "./types";

const DEFAULT_API_BASE_URL = import.meta.env.DEV
  ? "http://127.0.0.1:8000"
  : "";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/$/, "");

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          return String(item.msg);
        }
        return String(item);
      })
      .join(" ");
  }

  return "The request could not be completed.";
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new Error("Cannot reach the PDF Agent API.");
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = payload.detail;
    } catch {
      detail = undefined;
    }
    throw new Error(detailMessage(detail));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function responseError(response: Response): Promise<Error> {
  let detail: unknown;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    detail = payload.detail;
  } catch {
    detail = undefined;
  }
  return new Error(detailMessage(detail));
}

export function checkHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health");
}

export function createSession(): Promise<{ session_id: string }> {
  return apiRequest<{ session_id: string }>("/sessions", {
    method: "POST",
  });
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return apiRequest<SessionDetail>(`/sessions/${sessionId}`);
}

export function deleteSession(sessionId: string): Promise<void> {
  return apiRequest<void>(`/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export function uploadPdfs(
  sessionId: string,
  files: File[],
): Promise<UploadResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  return apiRequest<UploadResponse>(`/sessions/${sessionId}/pdfs`, {
    method: "POST",
    body: formData,
  });
}

export function askQuestion(
  sessionId: string,
  question: string,
): Promise<AskResponse> {
  return apiRequest<AskResponse>(`/sessions/${sessionId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export async function askQuestionStream(
  sessionId: string,
  question: string,
  onProgress: (progress: WorkflowProgress) => void,
): Promise<AskResponse> {
  let response: Response;

  try {
    response = await fetch(
      `${API_BASE_URL}/sessions/${sessionId}/ask/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      },
    );
  } catch {
    throw new Error("Cannot reach the PDF Agent API.");
  }

  if (!response.ok) {
    throw await responseError(response);
  }

  if (!response.body) {
    throw new Error("The streaming response is unavailable.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: AskResponse | undefined;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      let eventName = "message";
      const dataLines: string[] = [];

      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }

      if (dataLines.length > 0) {
        const payload = JSON.parse(dataLines.join("\n")) as unknown;

        if (eventName === "progress") {
          onProgress(payload as WorkflowProgress);
        } else if (eventName === "result") {
          result = payload as AskResponse;
        }
      }

      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      break;
    }
  }

  if (!result) {
    throw new Error("The workflow ended without a result.");
  }

  return result;
}
