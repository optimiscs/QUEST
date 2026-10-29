/** Byte-limited LRU. Entries are keyed by run, trace ID and content revision. */
export class TraceCache<T> {
  private entries = new Map<string, { value: T; bytes: number }>();
  private bytes = 0;
  constructor(private maxBytes = 32 * 1024 * 1024) {}
  get(key: string): T | undefined {
    const item = this.entries.get(key);
    if (!item) return undefined;
    this.entries.delete(key);
    this.entries.set(key, item);
    return item.value;
  }
  set(key: string, value: T): void {
    const bytes = new TextEncoder().encode(JSON.stringify(value)).byteLength;
    const previous = this.entries.get(key);
    if (previous) { this.bytes -= previous.bytes; this.entries.delete(key); }
    if (bytes > this.maxBytes) return;
    this.entries.set(key, { value, bytes });
    this.bytes += bytes;
    while (this.bytes > this.maxBytes) {
      const oldest = this.entries.keys().next().value!;
      this.bytes -= this.entries.get(oldest)!.bytes;
      this.entries.delete(oldest);
    }
  }
  clear(): void { this.entries.clear(); this.bytes = 0; }
}
