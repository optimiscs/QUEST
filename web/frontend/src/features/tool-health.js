export const eventKey = (run, id) => JSON.stringify([run, id]);
export function summarize(events) {
  const out = { success: 0, failed: 0, pending: 0, unknown: 0, excluded: 0, zero: 0, partial: 0, rate: null };
  for (const event of events) {
    if (event.status in out) out[event.status]++;
    if (event.zeroResults && event.status === 'success') out.zero++;
    if (event.partial && event.status === 'failed') out.partial++;
  }
  const completed = out.success + out.failed;
  out.rate = completed ? out.success / completed * 100 : null;
  return out;
}
export function historicalSeries(events, bucket = 60) {
  const bins = new Map();
  for (const event of events) {
    if (!['success', 'failed'].includes(event.status) || !Number.isFinite(event.elapsedSeconds)) continue;
    const end = (Math.floor(event.elapsedSeconds / bucket) + 1) * bucket;
    if (!bins.has(end)) bins.set(end, []);
    bins.get(end).push(event);
  }
  let success = 0, total = 0;
  return [...bins.keys()].sort((a, b) => a - b).map(x => {
    for (const event of bins.get(x)) { success += event.status === 'success' ? 1 : 0; total++; }
    return { x, y: success / total * 100, n: total };
  });
}
export function filterEvents(events, status, reason) {
  return events.filter(e => (status === 'all' || (status === 'zero' ? e.zeroResults && e.status === 'success' : e.status === status)) && (!reason || e.reasons.includes(reason)));
}
