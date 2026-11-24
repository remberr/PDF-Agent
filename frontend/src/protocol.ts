import type { AskResponse, Execution, LLMUsage, NodeOutcome, SessionDetail, UploadResponse, WorkflowProgress } from './types';

export const object = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const string = (v: unknown): v is string => typeof v === 'string';
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(string);
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const integer = (v: unknown) => number(v) && Number.isSafeInteger(v);
const timings = (v: unknown) => object(v) && Object.values(v).every(number);
const nodeStatuses = ['running', 'succeeded', 'degraded', 'failed', 'cancelled', 'skipped'];
const terminal = ['succeeded', 'degraded', 'failed', 'cancelled'];
const steps = (v: unknown) => strings(v) && v.length <= 5 && new Set(v).size === v.length && v.every(s => ['qa','source','summary','keyword','compare'].includes(s));
const optional = (v: unknown, check: (value: unknown) => boolean) => v === undefined || check(v);
const reason = (v: unknown) => v === null || (string(v) && v.length <= 128);

function nodes(v: unknown): v is Record<string, NodeOutcome> {
  return object(v) && Object.keys(v).length <= 20 && Object.values(v).every(n =>
    object(n) && string(n.status) && nodeStatuses.includes(n.status) && reason(n.reason));
}
function execution(v: unknown): v is Execution {
  if (!object(v) || !string(v.status) || !terminal.includes(v.status) ||
      !string(v.generation_status) || !terminal.includes(v.generation_status) ||
      !reason(v.reason) || !nodes(v.node_statuses) || !string(v.persistence) ||
      !['saved','failed','not_attempted'].includes(v.persistence)) return false;
  if (v.persistence === 'failed') return v.status === 'failed';
  if (v.status !== v.generation_status) return false;
  return v.status === 'cancelled' ? v.persistence === 'not_attempted' : v.persistence === 'saved';
}
function bucket(v: unknown): boolean {
  return object(v) && ['llm_calls','input_tokens','output_tokens','total_tokens','cache_hit_tokens','cache_miss_tokens'].every(k => integer(v[k])) &&
    number(v.estimated_cost_usd) && optional(v.estimated_cost_cny, x => x === null || number(x)) &&
    optional(v.cost_estimate_available, x => typeof x === 'boolean') &&
    optional(v.cost_estimate_cny_available, x => typeof x === 'boolean') &&
    optional(v.cache_usage_available, x => typeof x === 'boolean') &&
    optional(v.cache_unavailable_calls, integer) &&
    optional(v.cache_status, x => string(x) && ['available','unavailable','no_calls'].includes(x)) &&
    optional(v.cache_hit_rate, x => number(x) && x <= 1);
}
function usage(v: unknown): v is LLMUsage {
  return object(v) && bucket(v) && number(v.cache_hit_rate) && v.cache_hit_rate <= 1 &&
    typeof v.cost_estimate_available === 'boolean' && string(v.currency) && strings(v.pricing_tiers) &&
    object(v.by_model) && Object.values(v.by_model).every(bucket) &&
    object(v.by_operation) && Object.values(v.by_operation).every(bucket);
}
function notes(v: unknown) {
  return object(v) && ['agent','status','answer'].every(k => optional(v[k], string)) &&
    ['issues','missing_information','recommendations','next_steps'].every(k => optional(v[k], strings)) &&
    optional(v.needs_revision, x => typeof x === 'boolean');
}
function isResult(v: unknown): v is AskResponse {
  return object(v) && string(v.answer) && steps(v.steps) && Array.isArray(v.sources) && v.sources.every(s =>
    object(s) && string(s.citation_id) && string(s.source) && integer(s.page) && Number(s.page) >= 1 && string(s.excerpt)) &&
    notes(v.collaboration_notes) && integer(v.revision_count) && Number(v.revision_count) <= 1 &&
    timings(v.timings) && usage(v.usage) && optional(v.execution, x => x === null || execution(x));
}
export function parseAskResponse(v: unknown): AskResponse {
  if (!isResult(v)) throw new Error('Invalid workflow result.');
  return v;
}
export function parseProgress(v: unknown): WorkflowProgress {
  function valid(v: unknown): v is WorkflowProgress {
    return object(v) && string(v.node) && ['running','completed','failed'].includes(String(v.status)) &&
      strings(v.completed_nodes) && steps(v.steps) && integer(v.revision_count) && Number(v.revision_count) <= 1 &&
      timings(v.timings) && optional(v.elapsed_ms, number) && usage(v.usage) && optional(v.node_statuses, nodes);
  }
  if (!valid(v)) throw new Error('Invalid workflow progress.');
  return v;
}
export function parseSession(v: unknown): SessionDetail {
  function valid(v: unknown): v is SessionDetail {
    return object(v) && string(v.session_id) && strings(v.loaded_pdfs) && integer(v.message_count) &&
      typeof v.has_vectorstore === 'boolean' && integer(v.total_documents);
  }
  if (!valid(v)) throw new Error('Invalid session response.');
  return v;
}
export function parseUpload(v: unknown): UploadResponse {
  function valid(v: unknown): v is UploadResponse {
    return object(v) && string(v.session_id) && strings(v.loaded_pdfs) && strings(v.uploaded_files) && integer(v.total_documents);
  }
  if (!valid(v)) throw new Error('Invalid upload response.');
  return v;
}
