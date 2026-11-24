import type { AskResponse, HealthResponse, SessionDetail, UploadResponse, WorkflowProgress } from './types';
import { object, parseAskResponse, parseSession, parseUpload } from './protocol';
import { readWorkflowStream } from './sse';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}
function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => object(item) && typeof item.msg === 'string' ? item.msg : 'Invalid request.').join(' ');
  return 'The request could not be completed.';
}
async function responseError(response: Response): Promise<ApiError> {
  let detail: unknown;
  try { const payload: unknown = await response.json(); detail = object(payload) ? payload.detail : undefined; } catch { /* no JSON */ }
  return new ApiError(detailMessage(detail), response.status);
}
async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  const headers = new Headers(init?.headers);
  if (path === '/sessions' || path.startsWith('/sessions/')) {
    headers.set('X-PDF-Agent-Client', 'browser');
  }
  try { response = await fetch(path, {...init, headers, credentials: 'same-origin', redirect: 'error'}); }
  catch (error) {
    if (init?.signal?.aborted || (error instanceof Error && error.name === 'AbortError')) throw new DOMException('Request cancelled.', 'AbortError');
    throw new ApiError('Cannot reach the PDF Agent API.', 0);
  }
  if (!response.ok) throw await responseError(response);
  return response;
}
async function apiRequest<T>(path: string, parse: (value: unknown) => T, init?: RequestInit): Promise<T> {
  const response = await request(path, init);
  const payload: unknown = await response.json();
  return parse(payload);
}
export function checkHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest('/health', value => {
    if (!object(value) || typeof value.status !== 'string' || typeof value.service !== 'string') throw new Error('Invalid health response.');
    return {status: value.status, service: value.service};
  }, {signal});
}
export function createSession(signal?: AbortSignal): Promise<{session_id: string}> {
  return apiRequest('/sessions', value => {
    if (!object(value) || typeof value.session_id !== 'string' || !/^[a-f0-9]{32}$/.test(value.session_id)) {
      throw new Error('Invalid session response.');
    }
    return {session_id: value.session_id};
  }, {method: 'POST', signal});
}
export function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionDetail> {
  return apiRequest(`/sessions/${encodeURIComponent(sessionId)}`, value => {
    const session = parseSession(value);
    if (session.session_id !== sessionId) throw new Error('Invalid session response.');
    return session;
  }, {signal});
}
export async function deleteSession(sessionId: string, signal?: AbortSignal): Promise<void> {
  await request(`/sessions/${encodeURIComponent(sessionId)}`, {method: 'DELETE', signal});
}
export function uploadPdfs(sessionId: string, files: File[], signal?: AbortSignal): Promise<UploadResponse> {
  const data = new FormData(); files.forEach(file => data.append('files', file));
  return apiRequest(`/sessions/${encodeURIComponent(sessionId)}/pdfs`, parseUpload, {method: 'POST', body: data, signal});
}
export function askQuestion(sessionId: string, question: string, signal?: AbortSignal): Promise<AskResponse> {
  return apiRequest(`/sessions/${encodeURIComponent(sessionId)}/ask`, parseAskResponse, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question}), signal,
  });
}
export async function askQuestionStream(sessionId: string, question: string,
  onProgress: (progress: WorkflowProgress) => void, signal?: AbortSignal): Promise<AskResponse> {
  const response = await request(`/sessions/${encodeURIComponent(sessionId)}/ask/stream`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question}), signal,
  });
  if (!response.body) throw new Error('The streaming response is unavailable.');
  return readWorkflowStream(response.body, onProgress, signal);
}
