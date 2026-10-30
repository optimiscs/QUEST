export class TraceSearch {
  private worker = new Worker(new URL('../workers/search.worker.ts', import.meta.url), { type: 'module' });
  private generation = 0;
  private request = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  constructor(private onMatches: (matches: Set<number>) => void) {
    this.worker.onmessage = ({ data }) => {
      if (data.generation === this.generation && data.request === this.request) this.onMatches(new Set(data.matches));
    };
  }
  index(steps: unknown): void {
    this.generation++;
    clearTimeout(this.timer);
    this.worker.postMessage({ type: 'index', steps, generation: this.generation, request: ++this.request });
  }
  search(query: string): void {
    clearTimeout(this.timer);
    const request = ++this.request;
    this.timer = setTimeout(() => this.worker.postMessage({ type: 'query', query, generation: this.generation, request }), 120);
  }
  destroy(): void { clearTimeout(this.timer); this.worker.terminate(); }
}
