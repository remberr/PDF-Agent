import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError, getSession, askQuestionStream } from '../src/api.ts';

test('HTTP 404, 500 and network errors preserve distinct status with exactly one attempt', async t => {
  const previous = globalThis.fetch;
  t.after(() => {globalThis.fetch = previous;});
  let calls = 0;
  for (const status of [404,500,0]) {
    globalThis.fetch = async () => {calls++; if (!status) throw Error('network'); return new Response('{}',{status});};
    await assert.rejects(getSession('a'), error => error instanceof ApiError && error.status === status);
  }
  assert.equal(calls,3);
});
test('stream transport abort is preserved without automatic retry', async t => {
  const previous = globalThis.fetch; t.after(() => {globalThis.fetch = previous;});
  let calls=0;
  globalThis.fetch = async () => {calls++; throw new DOMException('cancelled','AbortError');};
  await assert.rejects(askQuestionStream('a','q',()=>{}),{name:'AbortError'});
  assert.equal(calls,1);
});
test('session responses cannot switch to an unrelated session', async t => {
  const previous = globalThis.fetch; t.after(() => {globalThis.fetch = previous;});
  globalThis.fetch = async () => new Response(JSON.stringify({session_id:'b',loaded_pdfs:[],message_count:0,has_vectorstore:false,total_documents:0}));
  await assert.rejects(getSession('a'));
});
