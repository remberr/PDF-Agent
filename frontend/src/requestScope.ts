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
export function purgeLegacySessionStorage(store?: Pick<Storage, 'length' | 'key' | 'removeItem'>): boolean {
  try {
    const storage = store ?? globalThis.localStorage;
    const obsolete = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key === 'pdf-agent-session' || key?.startsWith('pdf-agent-conversation-')) obsolete.push(key);
    }
    for (const key of obsolete) storage.removeItem(key);
    return true;
  } catch { return false; }
}
