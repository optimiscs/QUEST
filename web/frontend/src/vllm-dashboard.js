import './vllm-dashboard.css';

const $ = selector => document.querySelector(selector);
const history = new Map();
const trend = [];
let busy = false;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const val = (sample, key) => sample?.values?.[key];
const fmt = (v, digits = 1) => Number.isFinite(v) ? new Intl.NumberFormat('en-US', {maximumFractionDigits: digits}).format(v) : '—';
const pct = v => Number.isFinite(v) ? `${fmt(v * 100, 1)}%` : '—';
const sec = v => Number.isFinite(v) ? `${fmt(v, 2)}s` : '—';
const delta = (a, b, key) => {
  const x = val(a, key), y = val(b, key);
  return Number.isFinite(x) && Number.isFinite(y) && x >= y ? x - y : null;
};
function rate(a, b, key) {
  const seconds = a?.sampledAt - b?.sampledAt;
  const change = delta(a, b, key);
  return seconds > 0 && seconds < 6 && change !== null ? change / seconds : null;
}
function ratio(a, b, numerator, denominator) {
  const x = delta(a, b, numerator), y = delta(a, b, denominator);
  return x !== null && y > 0 && x <= y ? x / y : null;
}
function histogram(a, b, key) {
  const current = a?.histograms?.[key], previous = b?.histograms?.[key];
  if (!current || !previous) return {mean: null, p95: null, count: 0};
  const count = current.count - previous.count, sum = current.sum - previous.sum;
  if (!(count > 0) || !(sum >= 0)) return {mean: null, p95: null, count: 0};
  const bounds = Object.keys(current.buckets || {}).map(k => k === '+Inf' ? Infinity : Number(k)).sort((x,y) => x-y);
  let before = 0, lower = 0, p95 = null;
  for (const bound of bounds) {
    // Preserve the exact Prometheus label (e.g. "1.0") rather than normalizing it.
    const raw = Object.keys(current.buckets).find(k => (k === '+Inf' ? Infinity : Number(k)) === bound);
    const after = current.buckets[raw] - previous.buckets?.[raw];
    if (!Number.isFinite(after) || after < before) return {mean: sum / count, p95: null, count};
    if (after >= count * .95) {
      if (Number.isFinite(bound)) p95 = lower + (bound - lower) * (count * .95 - before) / Math.max(1, after - before);
      break;
    }
    before = after; lower = bound;
  }
  return {mean: sum / count, p95, count};
}
function endpointRow(row) {
  const key = `${row.server}:${row.port}`, series = history.get(key) || [];
  if (!row.online) { history.delete(key); return {...row}; }
  const last = series.at(-1), window = series[0];
  const input = rate(row, last, 'prompt_tokens_total'), output = rate(row, last, 'generation_tokens_total');
  const cache = ratio(row, window, 'prefix_cache_hits_total', 'prefix_cache_queries_total');
  const mtp = ratio(row, window, 'spec_decode_num_accepted_tokens_total', 'spec_decode_num_draft_tokens_total');
  const preemptions = delta(row, window, 'num_preemptions_total');
  const ttft = histogram(row, window, 'time_to_first_token_seconds');
  const prefill = histogram(row, window, 'request_prefill_time_seconds');
  const decode = histogram(row, window, 'request_decode_time_seconds');
  const queue = histogram(row, window, 'request_queue_time_seconds');
  series.push(row);
  while (series.length > 1 && row.sampledAt - series[0].sampledAt > 60) series.shift();
  history.set(key, series);
  return {...row, input, output, cache, mtp, preemptions, ttft, prefill, decode, queue};
}
function cell(v, label) { return `<td title="${esc(label)}">${v}</td>`; }
function renderServer(server, rows) {
  const online = rows.filter(x => x.online).length;
  return `<section class="server"><div class="server-head"><div class="server-name"><span class="status ${online ? '' : 'offline'}"></span><strong>${esc(server)}服务器</strong><small>${server.startsWith('SSH ') ? 'SSH 服务器' : '本地服务'}</small></div><span class="server-count">${online} / ${rows.length} 在线</span></div><div class="table-wrap"><table><thead><tr><th>设备 / 模型</th><th>服务</th><th>运行 / 排队</th><th>输入 tok/s</th><th>输出 tok/s</th><th>KV 使用</th><th>缓存命中</th><th>TTFT P95</th><th>Prefill P95</th><th>Decode P95</th><th>排队 P95</th><th>抢占 / 60s</th><th>MTP 接受</th></tr></thead><tbody>${rows.map(r => {
    if (!r.online) return `<tr><td><span class="gpu-badge">${esc(r.gpu)}</span>${esc(r.model || r.role)}</td><td><span class="status offline">离线 · ${esc(r.port)}</span></td><td colspan="11" class="muted">${esc(r.error || '采集失败')}，等待恢复</td></tr>`;
    const kv = val(r, 'kv_cache_usage_perc');
    return `<tr><td><span class="gpu-badge">${esc(r.gpu)}</span>${esc(r.model || r.role)}</td><td><span class="status">在线 · ${esc(r.port)}</span></td>${cell(`${fmt(val(r,'num_requests_running'),0)} / ${fmt(val(r,'num_requests_waiting'),0)}`,'当前运行和等待请求数')}${cell(fmt(r.input),'最近采样间隔输入 token/s')}${cell(fmt(r.output),'最近采样间隔输出 token/s')}<td class="cache-cell">${pct(kv)}${Number.isFinite(kv) ? `<span class="bar"><i style="width:${Math.min(100,Math.max(0,kv*100))}%"></i></span>` : ''}</td>${cell(pct(r.cache),'近 60 秒前缀缓存命中 tokens / 查询 tokens')}${cell(sec(r.ttft?.p95),`TTFT 近 60 秒 P95；样本 ${r.ttft?.count || 0}`)}${cell(sec(r.prefill?.p95),`Prefill 近 60 秒 P95；样本 ${r.prefill?.count || 0}`)}${cell(sec(r.decode?.p95),`Decode 近 60 秒 P95；样本 ${r.decode?.count || 0}`)}${cell(sec(r.queue?.p95),`排队近 60 秒 P95；样本 ${r.queue?.count || 0}`)}${cell(fmt(r.preemptions,0),'近 60 秒新增抢占次数')}${cell(pct(r.mtp),'近 60 秒 MTP 接受 tokens / 草稿 tokens')}</tr>`;
  }).join('')}</tbody></table></div></section>`;
}
function renderChart() {
  const svg = $('#chart');
  if (trend.length < 2) { $('#chart-empty').hidden = false; svg.innerHTML = ''; return; }
  $('#chart-empty').hidden = true;
  const max = Math.max(1, ...trend.flatMap(v => [v.input || 0, v.output || 0]));
  const end = trend.at(-1).time, start = end - 60;
  const points = key => trend.filter(v => Number.isFinite(v[key])).map(v => `${Math.max(0, (v.time-start)/60*1000).toFixed(1)},${(158-v[key]/max*145).toFixed(1)}`).join(' ');
  svg.innerHTML = `<polyline points="${points('input')}" fill="none" stroke="#2457d6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/><polyline points="${points('output')}" fill="none" stroke="#91a9cf" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;
}
async function refresh() {
  if (busy || document.hidden) return;
  busy = true;
  try {
    const response = await fetch('/api/v1/vllm/metrics', {cache:'no-store', signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json(), rows = payload.endpoints.map(endpointRow), live = rows.filter(r => r.online);
    const total = key => { const values = live.map(r => r[key]).filter(Number.isFinite); return values.length ? values.reduce((a,b) => a+b,0) : null; };
    const sumValues = key => { const values = live.map(r => val(r,key)).filter(Number.isFinite); return values.length ? values.reduce((a,b) => a+b,0) : null; };
    $('#online').textContent = `${live.length} / ${rows.length}`;
    $('#input').textContent = fmt(total('input')); $('#output').textContent = fmt(total('output'));
    $('#requests').textContent = `${fmt(sumValues('num_requests_running'),0)} / ${fmt(sumValues('num_requests_waiting'),0)}`;
    $('#timestamp').textContent = new Date(payload.sampledAt*1000).toLocaleTimeString('zh-CN', {hour12:false});
    $('#sample-detail').textContent = `每秒轮询 · 最慢采集 ${fmt(rows.length ? Math.max(...rows.map(r => r.scrapeMs)) : null,0)} ms`;
    const onlineAll = rows.length > 0 && live.length === rows.length;
    const health = onlineAll ? 'online' : (live.length ? 'degraded' : 'offline');
    const topRight = $('.top-right');
    if (topRight) topRight.dataset.state = health;
    $('#connection').textContent = !rows.length ? '未发现服务' : onlineAll ? '全部在线' : `${rows.length - live.length} 个服务离线`;
    $('#endpoint-count').textContent = `${rows.length} 个端点`;
    const alert = $('#alert');
    const warnings = payload.discoveryWarnings || [];
    alert.hidden = onlineAll && !warnings.length;
    alert.textContent = [!rows.length ? '未发现 vLLM 服务。' : (!onlineAll ? `${rows.length - live.length} 个端点暂时不可用；汇总仅包含在线端点。` : ''), ...warnings].filter(Boolean).join('；');
    const names = [...new Set(rows.map(r => r.server))];
    $('#servers').innerHTML = names.map(name => renderServer(name, rows.filter(r => r.server === name))).join('');
    if (total('input') !== null || total('output') !== null) trend.push({time:payload.sampledAt,input:total('input'),output:total('output')});
    while (trend.length && payload.sampledAt - trend[0].time > 60) trend.shift();
    renderChart();
  } catch (error) {
    const topRight = $('.top-right');
    if (topRight) topRight.dataset.state = 'offline';
    $('#connection').textContent = '采集失败';
    $('#alert').hidden = false;
    $('#alert').textContent = `无法读取指标：${error.message}。保留上一次画面。`;
  } finally { busy = false; }
}
refresh();
setInterval(refresh, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
