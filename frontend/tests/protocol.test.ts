import assert from 'node:assert/strict';
import test from 'node:test';
import { readWorkflowStream } from '../src/sse.ts';
import { parseAskResponse, parseProgress } from '../src/protocol.ts';
import { RequestScope, purgeLegacySessionStorage, safeStorage } from '../src/requestScope.ts';

export const result = {
  answer: 'Evidence 中文', steps: ['source'], sources: [], collaboration_notes: {}, revision_count: 0,
  timings: {}, usage: {llm_calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0,
    cache_hit_tokens: 0, cache_miss_tokens: 0, estimated_cost_usd: 0, cache_hit_rate: 0,
    currency: 'USD', cost_estimate_available: true, pricing_tiers: [], by_model: {}, by_operation: {}},
  execution: {status: 'succeeded', generation_status: 'succeeded', reason: null,
    persistence: 'saved', node_statuses: {reviewer: {status: 'succeeded', reason: null}}},
};

test('result validation rejects malformed and contradictory terminal metadata but accepts legacy', () => {
  assert.equal(parseAskResponse(result).execution?.status, 'succeeded');
  const legacy = {...result, execution: undefined};
  assert.equal(parseAskResponse(legacy).execution, undefined);
  for (const invalid of [null, {}, {...result, sources: [null]}, {...result, usage: {llm_calls: '0'}},
    {...result, execution: {...result.execution, persistence: 'failed'}},
    {...result, execution: {...result.execution, status: 'mystery'}}]) {
    assert.throws(() => parseAskResponse(invalid));
  }
});

test('SSE accepts every UTF8/CRLF byte boundary and releases reader', async () => {
  const bytes = new TextEncoder().encode(`: heartbeat\r\n\r\nevent: result\r\ndata: ${JSON.stringify(result)}\r\n\r\n`);
  const stream = new ReadableStream<Uint8Array>({start(controller) {
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  }});
  assert.equal((await readWorkflowStream(stream, () => {})).answer, result.answer);
  assert.equal(stream.locked, false);
});

test('empty, truncated, malformed and missing result streams reject instead of succeeding', async () => {
  for (const content of ['', 'event: result\ndata: {', 'event: result\ndata: {}\n\n', ': heartbeat\n\n']) {
    const stream = new ReadableStream<Uint8Array>({start(c) {c.enqueue(new TextEncoder().encode(content)); c.close();}});
    await assert.rejects(readWorkflowStream(stream, () => {}));
    assert.equal(stream.locked, false);
  }
});

test('abort cancels pending reader and does not wait for EOF', async () => {
  let cancelled = 0;
  const controller = new AbortController();
  const stream = new ReadableStream<Uint8Array>({cancel() {cancelled++;}});
  const pending = readWorkflowStream(stream, () => {}, controller.signal);
  controller.abort();
  await assert.rejects(pending, {name: 'AbortError'});
  assert.equal(cancelled, 1);
  assert.equal(stream.locked, false);
});

test('request scope blocks stale callbacks, duplicate requests and cross-session writes', () => {
  const scope = new RequestScope();
  const first = scope.start('ask', 'a');
  const replacement = scope.start('ask', 'a');
  assert.equal(first.signal.aborted, true);
  assert.equal(scope.isCurrent(first), false);
  assert.equal(scope.isCurrent(replacement), true);
  scope.invalidate();
  const other = scope.start('ask', 'b');
  assert.equal(scope.isCurrent(replacement), false);
  assert.equal(scope.isCurrent(other), true);
  scope.finish(replacement);
  assert.equal(scope.isCurrent(other), true);
  scope.finish(other);
  assert.equal(scope.has('ask'), false);
});

test('progress shape and existing status enum are checked at runtime', () => {
  const progress = {node:'planner',status:'running',completed_nodes:[],steps:[],revision_count:0,timings:{},usage:result.usage};
  assert.equal(parseProgress(progress).status,'running');
  for (const invalid of [{...progress,status:'degraded'}, {...progress,completed_nodes:'all'},
    {...progress,node_statuses:{planner:{status:'maybe',reason:null}}}]) assert.throws(()=>parseProgress(invalid));
});

test('complete result finishes and cancels transport even if server never closes', async () => {
  let cancelled=0;
  const stream = new ReadableStream<Uint8Array>({start(c) {
    c.enqueue(new TextEncoder().encode(`event: result\ndata: ${JSON.stringify(result)}\n\n`));
  }, cancel() {cancelled++;}});
  assert.equal((await readWorkflowStream(stream,()=>{})).execution?.status,'succeeded');
  assert.equal(cancelled,1);
  assert.equal(stream.locked,false);
});

test('storage denial is recoverable', () => {
  const denied = {getItem() {throw Error('denied');}, setItem() {throw Error('quota');}, removeItem() {throw Error('denied');}};
  assert.equal(safeStorage('get', 'key', undefined, denied), null);
  assert.equal(safeStorage('set', 'key', 'value', denied), false);
});

test('old transcript keys are removed without resetting unrelated storage', () => {
  const data = new Map([
    ['pdf-agent-session', 'legacy'],
    ['pdf-agent-conversation-a', 'private transcript A'],
    ['pdf-agent-conversation-b', 'private transcript B'],
    ['pdf-agent-session-v2', 'current'],
    ['pdf-agent-language', 'zh'],
    ['unrelated', 'keep'],
  ]);
  const store = {
    get length() { return data.size; },
    key(index: number) { return Array.from(data.keys())[index] ?? null; },
    removeItem(key: string) { data.delete(key); },
  };
  assert.equal(purgeLegacySessionStorage(store), true);
  assert.deepEqual(Array.from(data.keys()), ['pdf-agent-session-v2', 'pdf-agent-language', 'unrelated']);
  data.set('pdf-agent-session', 'legacy');
  const denied = {...store, removeItem() { throw Error('denied'); }};
  assert.equal(purgeLegacySessionStorage(denied), false);
});
