interface Step {
  n: number; thought?: string; label?: string;
  tool?: { name?: string; queries?: {query?: string; results?: {title?: string; domain?: string; snippet?: string}[]}[];
    pages?: {title?: string; domain?: string; summary?: string; rationale?: string; evidence?: string}[];
    code?: string; stdout?: string };
}
let index: { n: number; text: string }[] = [];
self.onmessage = ({ data }: MessageEvent<{ type: string; steps?: Step[]; query?: string; generation: number; request: number }>) => {
  if (data.type === 'index') {
    index = (data.steps || []).map(step => {
      const parts = [step.thought, step.label, step.tool?.name, step.tool?.code, step.tool?.stdout];
      for (const query of step.tool?.queries || []) {
        parts.push(query.query);
        for (const result of query.results || []) parts.push(result.title, result.domain, result.snippet);
      }
      for (const page of step.tool?.pages || []) parts.push(page.title, page.domain, page.summary, page.rationale, page.evidence);
      return { n: step.n, text: parts.join(' ').replace(/\s+/g, ' ').toLowerCase() };
    });
  } else {
    const query = (data.query || '').trim().toLowerCase();
    self.postMessage({ generation: data.generation, request: data.request,
      matches: index.filter(step => !query || step.text.includes(query)).map(step => step.n) });
  }
};
