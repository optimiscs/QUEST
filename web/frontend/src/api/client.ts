import type { components } from './generated';

type RunInfo = components['schemas']['RunInfo'];
type TaskPage = components['schemas']['TaskPage'];
type TraceDocument = components['schemas']['TraceDocument'];
export type TaskSummary = components['schemas']['TaskSummary'];

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function getJSON<T>(url: string, signal?: AbortSignal, etag?: string): Promise<{data: T | null; etag: string | null}> {
  const response = await fetch(url, {
    signal, headers: etag ? { 'If-None-Match': etag } : {}, cache: 'no-cache',
  });
  if (response.status === 304) return { data: null, etag: response.headers.get('ETag') };
  if (!response.ok) throw new ApiError(response.status, `请求失败 (${response.status})`);
  return { data: await response.json() as T, etag: response.headers.get('ETag') };
}

export const runURL = (id: string) => `/api/v1/runs/${encodeURIComponent(id)}`;

export async function loadRun(id: string, signal?: AbortSignal) {
  // Retry if an importer publishes a new run between page requests.
  for (let attempt = 0; attempt < 3; attempt++) {
    const info = (await getJSON<RunInfo>(runURL(id), signal)).data!;
    const cases: TaskSummary[] = [];
    let cursor: number | null = 0;
    let consistent = true;
    while (cursor !== null) {
      const page: TaskPage = (await getJSON<TaskPage>(`${runURL(id)}/traces?limit=200&cursor=${cursor}`, signal)).data!;
      if (page.runRevision !== info.revision) { consistent = false; break; }
      cases.push(...page.items);
      cursor = page.nextCursor;
    }
    if (consistent) return { info, cases };
  }
  throw new Error('工作区正在更新，请稍后重试');
}

export const loadTrace = (run: string, id: string, signal?: AbortSignal, revision?: string) =>
  getJSON<TraceDocument>(`${runURL(run)}/traces/${encodeURIComponent(id)}`, signal).then(result => {
    if (revision && result.etag !== `"${revision}"`) throw new Error('轨迹正在更新，请重试');
    return result.data!;
  });
