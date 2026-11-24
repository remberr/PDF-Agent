import type { AskResponse, WorkflowProgress } from './types';
import { parseAskResponse, parseProgress } from './protocol';

export async function readWorkflowStream(stream: ReadableStream<Uint8Array>, onProgress: (p: WorkflowProgress) => void,
  signal?: AbortSignal): Promise<AskResponse> {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf-8', {fatal: true});
  let buffer = '';
  let result: AskResponse | undefined;
  const abort = () => { void reader.cancel().catch(() => undefined); };
  const checkAbort = () => { if (signal?.aborted) throw new DOMException('Request cancelled.', 'AbortError'); };
  signal?.addEventListener('abort', abort, {once: true});
  try {
    checkAbort();
    while (true) {
      const {value, done} = await reader.read();
      checkAbort();
      // Normalize after concatenation so a CR/LF split across reads is intact.
      buffer = (buffer + decoder.decode(value, {stream: !done})).replace(/\r\n/g, '\n').replace(/\r(?!$)/g, '\n');
      if (buffer.length > 2_000_000) throw new Error('Streaming frame is too large.');
      let boundary: number;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        let name = 'message'; const data: string[] = [];
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) name = line.slice(6).trim();
          else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
        }
        if (!data.length || !['progress','result'].includes(name)) continue;
        if (result) throw new Error('Unexpected event after terminal result.');
        const payload: unknown = JSON.parse(data.join('\n'));
        if (name === 'progress') onProgress(parseProgress(payload));
        else result = parseAskResponse(payload);
      }
      if (result) return result;
      if (done) throw new Error('The workflow ended without a complete result.');
    }
  } finally {
    signal?.removeEventListener('abort', abort);
    try { await reader.cancel(); } catch { /* The transport may already be broken. */ }
    reader.releaseLock();
  }
}
