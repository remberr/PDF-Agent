import type { ConversationTurn } from './types';
import { object, parseAskResponse } from './protocol';

interface Lease { signal: AbortSignal; sessionId: string; controller: AbortController }
export class RequestScope {
  private leases = new Map<string, Lease>();
  start(kind: string, sessionId = ''): Lease {
    this.leases.get(kind)?.controller.abort();
    const controller = new AbortController();
    const lease = {controller, signal: controller.signal, sessionId};
    this.leases.set(kind, lease);
    return lease;
  }
  isCurrent(lease: Lease): boolean { return !lease.signal.aborted && [...this.leases.values()].includes(lease); }
  has(kind: string): boolean { return this.leases.has(kind); }
  finish(lease: Lease): void { for (const [key, value] of this.leases) if (value === lease) this.leases.delete(key); }
  cancel(kind: string): void { const lease = this.leases.get(kind); lease?.controller.abort(); this.leases.delete(kind); }
  invalidate(): void { for (const lease of this.leases.values()) lease.controller.abort(); this.leases.clear(); }
}
type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export function safeStorage(action: 'get' | 'set' | 'remove', key: string, value?: string, store?: Store): string | null | boolean {
  try {
    const storage = store ?? globalThis.localStorage;
    if (action === 'get') return storage.getItem(key);
    if (action === 'set') storage.setItem(key, value ?? '');
    else storage.removeItem(key);
    return true;
  } catch { return action === 'get' ? null : false; }
}
export function readConversation(sessionId: string, store?: Store): ConversationTurn[] {
  try {
    const value = safeStorage('get', `pdf-agent-conversation-${sessionId}`, undefined, store);
    const parsed: unknown = typeof value === 'string' ? JSON.parse(value) : [];
    if (!Array.isArray(parsed)) return [];
    const turns: ConversationTurn[] = [];
    for (const turn of parsed) {
      if (!object(turn) || typeof turn.id !== 'string' || typeof turn.question !== 'string') continue;
      try {
        turns.push({id: turn.id, question: turn.question, pending: false,
          result: turn.result ? parseAskResponse(turn.result) : undefined,
          error: typeof turn.error === 'string' ? turn.error : undefined});
      } catch { /* Keep other valid turns; untrusted stored results cannot reach UI. */ }
    }
    return turns;
  } catch { return []; }
}
