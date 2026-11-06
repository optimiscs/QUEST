const DATA_URL = '/assets/search-behavior.json';
const DEFAULT_RUN = 'gaia-quest4b-32-20261027-r2';
const NS = 'http://www.w3.org/2000/svg';

const BEHAVIOURS = {
  repeat: { label: '反复追问', color: '#b45309' },
  expand: { label: '持续拓展', color: '#1d4ed8' },
  mixed: { label: '混合迭代', color: '#667085' },
  single: { label: '单次检索', color: '#98a2b3' },
};
const CATEGORIES = {
  start: { label: '起始', color: '#0f2f66' },
  new: { label: '新方向', color: '#1d4ed8' },
  extend: { label: '逐步拓展', color: '#7c9bd6' },
  near: { label: '近重复', color: '#c59a4a' },
  exact: { label: '完全重复', color: '#b45309' },
};
const STATUSES = {
  pass: '通过',
  fail: '未通过',
  running: '进行中',
  interrupted: '已中断',
  unscored: '未评分',
};

const state = {
  data: null,
  run: null,
  cases: [],
  selectedId: null,
  completedOnly: true,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function pct(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

function number(value) {
  return new Intl.NumberFormat('zh-CN').format(Number(value) || 0);
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function shortText(value, limit = 90) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function formatTimestamp(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date).replace(/\//g, '-');
}

function setStatus(node, status) {
  node.className = 'status-pill';
  if (status) node.classList.add(status);
  node.textContent = STATUSES[status] || '未知';
}

function behaviorLabel(behavior) {
  return BEHAVIOURS[behavior]?.label || '未知';
}

function caseSort(a, b) {
  return (b.repeatRate - a.repeatRate) || (b.queryTotal - a.queryTotal) || String(a.id).localeCompare(String(b.id));
}

function filteredCases(run, completedOnly) {
  const cases = (run?.cases || []).filter((item) => item.queryTotal > 0);
  return (completedOnly ? cases.filter((item) => item.status !== 'running' && item.status !== 'interrupted') : cases).sort(caseSort);
}

function selectedCase() {
  return state.cases.find((item) => item.id === state.selectedId) || state.cases[0] || null;
}

function defaultCase(cases) {
  return cases[0] || null;
}

function populateRuns(data) {
  const select = $('#run-select');
  const groups = new Map();
  for (const run of data.runs) {
    const benchmark = run.benchmark || '未分类';
    if (!groups.has(benchmark)) groups.set(benchmark, []);
    groups.get(benchmark).push(run);
  }
  const fragment = document.createDocumentFragment();
  for (const benchmark of [...groups.keys()].sort((a, b) => a.localeCompare(b, 'zh-CN'))) {
    const group = document.createElement('optgroup');
    group.label = benchmark;
    for (const run of groups.get(benchmark)) {
      const option = document.createElement('option');
      option.value = run.id;
      option.textContent = `${run.label} · ${run.caseCount} 条轨迹`;
      group.append(option);
    }
    fragment.append(group);
  }
  select.replaceChildren(fragment);
  const exists = data.runs.some((run) => run.id === DEFAULT_RUN);
  const fallback = data.runs.find((run) => run.caseCount > 0)?.id || '';
  select.value = exists ? DEFAULT_RUN : fallback;
}

function populateCaseSelect(cases) {
  const select = $('#case-select');
  const fragment = document.createDocumentFragment();
  for (const item of cases) {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = `${item.topic || item.id} · ${item.queryTotal} 次`;
    fragment.append(option);
  }
  select.replaceChildren(fragment);
  if (state.selectedId) select.value = state.selectedId;
}

function chooseRun(runId) {
  const run = state.data?.runs.find((item) => item.id === runId);
  if (!run) return;
  state.run = run;
  state.cases = filteredCases(run, state.completedOnly);
  state.selectedId = defaultCase(state.cases)?.id || null;
  populateCaseSelect(state.cases);
  $('#case-select').disabled = !state.cases.length;
  render();
}

function setSelectedCase(caseId, shouldScroll = false) {
  if (!state.cases.some((item) => item.id === caseId)) return;
  state.selectedId = caseId;
  renderChart();
  renderDetail();
  renderTable();
  const select = $('#case-select');
  if (select.value !== caseId) select.value = caseId;
  if (shouldScroll && window.innerWidth <= 1120) {
    $('.detail-panel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function renderMeta() {
  const data = state.data;
  const totalCases = data.runs.reduce((sum, run) => sum + run.cases.length, 0);
  const totalQueries = data.runs.reduce((sum, run) => sum + run.cases.reduce((count, item) => count + item.queryTotal, 0), 0);
  $('#generated-at').textContent = formatTimestamp(data.generatedAt);
  $('#dataset-summary').textContent = `${data.runs.length} 个评估集 · ${number(totalCases)} 条轨迹`;
  $('#footer-generated').textContent = `SNAPSHOT ${formatTimestamp(data.generatedAt)} · ${number(totalQueries)} QUERIES`;
}

function renderKpis() {
  const cases = state.cases;
  const followUps = cases.reduce((sum, item) => sum + item.followUps, 0);
  const repeats = cases.reduce((sum, item) => sum + item.counts.exact + item.counts.near, 0);
  const newDirections = cases.reduce((sum, item) => sum + item.counts.new, 0);
  const extensions = cases.reduce((sum, item) => sum + item.counts.extend, 0);
  const totalQueries = cases.reduce((sum, item) => sum + item.queryTotal, 0);
  const medianQueries = median(cases.map((item) => item.queryTotal));

  $('#kpi-traces').textContent = number(cases.length);
  $('#kpi-traces-note').textContent = `共 ${number(totalQueries)} 次查询`;
  $('#kpi-median').textContent = Number.isInteger(medianQueries) ? medianQueries : medianQueries.toFixed(1);
  $('#kpi-repeat').textContent = followUps ? pct(repeats / followUps) : '0%';
  $('#kpi-expand').textContent = followUps ? pct((extensions + newDirections) / followUps) : '0%';
  $('#kpi-expand-note').textContent = `占后续查询 · 新方向 ${followUps ? pct(newDirections / followUps) : '0%'}`;
}

function renderBehaviourLegend() {
  const root = $('#behaviour-legend');
  const counts = { repeat: 0, expand: 0, mixed: 0, single: 0 };
  for (const item of state.cases) counts[item.behavior] = (counts[item.behavior] || 0) + 1;
  const fragment = document.createDocumentFragment();
  for (const key of ['expand', 'repeat', 'mixed', 'single']) {
    const span = document.createElement('span');
    span.className = `legend-${key}`;
    const dot = document.createElement('i');
    const label = document.createTextNode(BEHAVIOURS[key].label);
    const count = el('b', '', counts[key] || 0);
    span.append(dot, label, count);
    fragment.append(span);
  }
  root.replaceChildren(fragment);
}

function renderChart() {
  const svg = $('#scatter');
  const empty = $('#chart-empty');
  svg.replaceChildren();
  const cases = state.cases;
  empty.hidden = cases.length > 0;

  const wrap = $('.chart-wrap');
  const width = Math.max(300, Math.round(wrap?.clientWidth || 720));
  const height = Math.round(Math.max(270, Math.min(440, width * (window.innerWidth <= 760 ? .88 : .58))));
  const margin = { left: width < 480 ? 46 : 54, right: width < 480 ? 16 : 24, top: 19, bottom: 38 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  const sx = (value) => margin.left + (value / 100) * plotW;
  const sy = (value) => margin.top + (1 - value / 100) * plotH;
  const tickValues = [0, 25, 50, 75, 100];

  for (const value of tickValues) {
    const x = sx(value);
    const y = sy(value);
    svg.append(svgEl('line', { x1: x, x2: x, y1: margin.top, y2: margin.top + plotH, stroke: '#f0f3f8', 'stroke-width': 1 }));
    svg.append(svgEl('line', { x1: margin.left, x2: margin.left + plotW, y1: y, y2: y, stroke: '#f0f3f8', 'stroke-width': 1 }));

    const xText = svgEl('text', { x, y: margin.top + plotH + 20, fill: '#98a2b3', 'font-size': 9, 'text-anchor': 'middle' });
    xText.textContent = `${value}%`;
    svg.append(xText);
    const yText = svgEl('text', { x: margin.left - 10, y: y + 3, fill: '#98a2b3', 'font-size': 9, 'text-anchor': 'end' });
    yText.textContent = `${value}%`;
    svg.append(yText);
  }

  svg.append(svgEl('line', { x1: margin.left, x2: margin.left, y1: margin.top, y2: margin.top + plotH, stroke: '#dce3ed', 'stroke-width': 1 }));
  svg.append(svgEl('line', { x1: margin.left, x2: margin.left + plotW, y1: margin.top + plotH, y2: margin.top + plotH, stroke: '#dce3ed', 'stroke-width': 1 }));

  const thresholdX = sx(45);
  const thresholdY = sy(30);
  svg.append(svgEl('line', { x1: thresholdX, x2: thresholdX, y1: margin.top, y2: margin.top + plotH, stroke: '#c9d7eb', 'stroke-width': 1, 'stroke-dasharray': '3 4' }));
  svg.append(svgEl('line', { x1: margin.left, x2: margin.left + plotW, y1: thresholdY, y2: thresholdY, stroke: '#c9d7eb', 'stroke-width': 1, 'stroke-dasharray': '3 4' }));

  const expandLabel = svgEl('text', { x: margin.left + 10, y: margin.top + 16, fill: '#2563eb', 'font-size': 9, 'font-weight': 500 });
  expandLabel.textContent = '持续拓展';
  svg.append(expandLabel);
  const expandHint = svgEl('text', { x: margin.left + 10, y: margin.top + 28, fill: '#98a2b3', 'font-size': 8 });
  expandHint.textContent = '低重复 · 高发散';
  svg.append(expandHint);
  const repeatLabel = svgEl('text', { x: margin.left + plotW - 10, y: margin.top + plotH - 16, fill: '#b45309', 'font-size': 9, 'font-weight': 500, 'text-anchor': 'end' });
  repeatLabel.textContent = '反复追问';
  svg.append(repeatLabel);
  const repeatHint = svgEl('text', { x: margin.left + plotW - 10, y: margin.top + plotH - 4, fill: '#98a2b3', 'font-size': 8, 'text-anchor': 'end' });
  repeatHint.textContent = '高重复 · 低发散';
  svg.append(repeatHint);
  const progressiveLabel = svgEl('text', { x: margin.left + 10, y: thresholdY - 8, fill: '#7c9bd6', 'font-size': 9, 'font-weight': 500 });
  progressiveLabel.textContent = '渐进拓展';
  svg.append(progressiveLabel);
  const mixedLabel = svgEl('text', { x: margin.left + plotW - 10, y: margin.top + 16, fill: '#98a2b3', 'font-size': 9, 'font-weight': 500, 'text-anchor': 'end' });
  mixedLabel.textContent = '混合迭代';
  svg.append(mixedLabel);

  const xTitle = svgEl('text', { x: margin.left + plotW / 2, y: height - 7, fill: '#98a2b3', 'font-size': 8.5, 'text-anchor': 'middle' });
  xTitle.textContent = '重复 / 近重复查询占比 →';
  svg.append(xTitle);
  const yTitle = svgEl('text', { x: 13, y: margin.top + plotH / 2, fill: '#98a2b3', 'font-size': 8.5, 'text-anchor': 'middle', transform: `rotate(-90 13 ${margin.top + plotH / 2})` });
  yTitle.textContent = '新方向查询占比 →';
  svg.append(yTitle);

  const ordered = [...cases].sort((a, b) => {
    if (a.id === state.selectedId) return 1;
    if (b.id === state.selectedId) return -1;
    return a.queryTotal - b.queryTotal;
  });
  for (const item of ordered) {
    const selected = item.id === state.selectedId;
    const x = sx(Math.max(0, Math.min(100, item.repeatRate * 100)));
    const y = sy(Math.max(0, Math.min(100, item.newRate * 100)));
    const color = BEHAVIOURS[item.behavior]?.color || '#667085';
    const radius = 3.8 + Math.min(3.8, Math.log2(item.queryTotal + 1) * .58);
    if (selected) {
      svg.append(svgEl('circle', { cx: x, cy: y, r: radius + 3.4, fill: 'none', stroke: '#0f172a', 'stroke-width': 1.2, opacity: .82 }));
    }
    const circle = svgEl('circle', {
      cx: x,
      cy: y,
      r: radius,
      fill: color,
      opacity: selected ? 1 : .72,
      stroke: '#ffffff',
      'stroke-width': 1,
      'data-case-id': item.id,
      class: 'scatter-point',
      tabindex: 0,
      role: 'button',
      'aria-label': `${item.topic || item.id}，重复 ${pct(item.repeatRate)}，新方向 ${pct(item.newRate)}，${behaviorLabel(item.behavior)}`,
    });
    circle.addEventListener('pointerenter', () => showTooltip(item, circle));
    circle.addEventListener('focus', () => showTooltip(item, circle));
    circle.addEventListener('pointerleave', hideTooltip);
    circle.addEventListener('blur', hideTooltip);
    circle.addEventListener('click', () => setSelectedCase(item.id));
    circle.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        setSelectedCase(item.id);
      }
    });
    svg.append(circle);
  }
}

function showTooltip(item, circle) {
  const tooltip = $('#chart-tooltip');
  const wrap = $('.chart-wrap');
  if (!tooltip || !wrap) return;
  tooltip.replaceChildren();
  const title = document.createElement('strong');
  title.textContent = `${item.topic || item.id} · ${item.id}`;
  const question = document.createElement('em');
  question.textContent = shortText(item.question, 78);
  const row = document.createElement('div');
  row.className = 'tip-row';
  const left = document.createElement('span');
  left.textContent = `重复 ${pct(item.repeatRate)} · 新方向 ${pct(item.newRate)}`;
  row.append(left);
  const second = document.createElement('div');
  second.className = 'tip-row';
  const behaviour = document.createElement('span');
  behaviour.textContent = behaviorLabel(item.behavior);
  const count = document.createElement('b');
  count.textContent = `${item.queryTotal} 次查询`;
  second.append(behaviour, count);
  tooltip.append(title, question, row, second);
  tooltip.hidden = false;

  const wrapRect = wrap.getBoundingClientRect();
  const circleRect = circle.getBoundingClientRect();
  let leftPos = circleRect.left - wrapRect.left + circleRect.width / 2 + 9;
  let topPos = circleRect.top - wrapRect.top - tooltip.offsetHeight - 9;
  if (leftPos + tooltip.offsetWidth > wrap.clientWidth - 4) leftPos = leftPos - tooltip.offsetWidth - 18;
  if (leftPos < 4) leftPos = 4;
  if (topPos < 4) topPos = circleRect.bottom - wrapRect.top + 9;
  tooltip.style.left = `${leftPos}px`;
  tooltip.style.top = `${topPos}px`;
}

function hideTooltip() {
  const tooltip = $('#chart-tooltip');
  if (tooltip) tooltip.hidden = true;
}

function buildInsight(item) {
  const counts = item.counts;
  const parts = [];
  parts.push(`共 ${item.queryTotal} 次查询：起始 1 次、完全重复 ${counts.exact} 次、近重复 ${counts.near} 次、逐步拓展 ${counts.extend} 次、新方向 ${counts.new} 次。`);
  if (item.maxRepeat > 1) parts.push(`同一查询最多出现 ${item.maxRepeat} 次。`);
  if (item.behavior === 'repeat') {
    parts.push(`后续查询中重复/近重复占 ${pct(item.repeatRate)}，更像在同一个问题上反复追问。`);
  } else if (item.behavior === 'expand') {
    parts.push(`重复/近重复仅占 ${pct(item.repeatRate)}，拓展与新方向合计 ${pct(item.extendRate + item.newRate)}，更像持续拓展。`);
  } else if (item.behavior === 'single') {
    parts.push('只有一次搜索，无法判断后续是重复还是拓展。');
  } else {
    parts.push(`重复/近重复 ${pct(item.repeatRate)}，新方向 ${pct(item.newRate)}，两种模式并存，属于混合迭代。`);
  }
  return parts.join('');
}

function renderDetail() {
  const item = selectedCase();
  const empty = $('#detail-empty');
  const content = $('#detail-content');
  if (!item) {
    empty.hidden = false;
    content.hidden = true;
    return;
  }
  empty.hidden = true;
  content.hidden = false;

  $('#case-id').textContent = item.topic && item.topic !== item.id ? `${item.topic} · ${item.id}` : item.id;
  setStatus($('#case-status'), item.status);
  $('#case-question').textContent = item.question || '（无可展示的问题文本）';
  const run = state.run;
  const model = run?.model && run.model !== run.label ? ` · ${run.model}` : '';
  $('#case-meta').textContent = `${run?.benchmark || ''}${model} · ${item.duration ? `${item.duration}s` : '时长未知'}`;
  $('#case-queries').textContent = item.queryTotal;
  $('#case-rounds').textContent = item.queryRounds || item.rounds || '—';
  $('#case-repeat').textContent = pct(item.repeatRate);
  $('#case-expand').textContent = pct(item.extendRate + item.newRate);
  const behavior = $('#case-behaviour');
  behavior.className = `behaviour-pill ${item.behavior}`;
  behavior.textContent = behaviorLabel(item.behavior);
  $('#case-unique').textContent = `${item.unique} 个唯一查询 · 新方向 ${pct(item.newRate)} · ${item.followUps} 次后续查询`;

  const fingerprint = $('#fingerprint');
  const fingerprintCaption = $('#fingerprint-caption');
  fingerprint.replaceChildren();
  for (const query of item.queries) {
    const segment = document.createElement('span');
    segment.className = query.category;
    segment.title = `Q${query.index} · ${CATEGORIES[query.category]?.label || query.category} · ${query.q}`;
    fingerprint.append(segment);
  }
  fingerprintCaption.textContent = `${item.queryTotal} 个查询 · 颜色代表分类`;
  const categoryLegend = $('#category-legend');
  categoryLegend.replaceChildren();
  for (const key of ['start', 'new', 'extend', 'near', 'exact']) {
    const label = document.createElement('span');
    const dot = document.createElement('i');
    dot.style.background = CATEGORIES[key].color;
    label.append(dot, document.createTextNode(CATEGORIES[key].label));
    categoryLegend.append(label);
  }
  $('#case-insight').textContent = buildInsight(item);

  const list = $('#query-list');
  list.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const query of item.queries) {
    const row = document.createElement('li');
    row.className = `query-item ${query.category}`;
    const round = el('span', 'query-round', query.round ? `R${query.round}` : 'R–');
    const line = el('div', 'query-line');
    const top = el('div', 'query-top');
    const badge = el('span', `query-badge ${query.category}`, CATEGORIES[query.category]?.label || query.category);
    const index = el('span', 'query-index', `Q${query.index}`);
    top.append(badge, index);
    const resultCount = el('span', 'query-results', `${number(query.results)} 个结果`);
    top.append(resultCount);
    const text = el('p', 'query-text', query.q);
    const meta = el('div', 'query-meta');
    if (query.seconds > 0) meta.append(el('span', '', `${query.seconds}s`));
    if (query.category === 'exact' && query.related) {
      meta.append(el('span', '', `与 Q${query.related} 完全相同`));
    } else if (query.category === 'near' && query.related) {
      meta.append(el('span', '', `与 Q${query.related} 近重复 · ${pct(query.similarity)}`));
    } else if (query.category === 'extend' && query.related) {
      meta.append(el('span', '', `最相似 Q${query.related} · ${pct(query.similarity)}`));
    } else if (query.category === 'new' && query.related) {
      meta.append(el('span', '', `最相似 Q${query.related} · ${pct(query.similarity)}`));
    } else if (query.category === 'start') {
      meta.append(el('span', '', '首条查询'));
    }
    line.append(top, text);
    if (['new', 'extend'].includes(query.category) && query.newTerms?.length) {
      const terms = el('div', 'new-terms');
      for (const term of query.newTerms.slice(0, 5)) terms.append(el('span', '', `+${term}`));
      line.append(terms);
    }
    line.append(meta);
    row.append(round, line);
    fragment.append(row);
  }
  list.append(fragment);
  $('#query-caption').textContent = `${item.queryTotal} 次查询 · ${item.queryRounds} 轮${item.queryTotal > 4 ? ' · 向下滚动' : ''}`;
  $('#detail-content').scrollTop = 0;
}

function miniFingerprint(queries, max = 34) {
  const root = el('div', 'mini-fingerprint');
  if (!queries.length) return root;
  if (queries.length <= max) {
    for (const query of queries) {
      const segment = document.createElement('i');
      segment.className = query.category;
      root.append(segment);
    }
  } else {
    for (let index = 0; index < max; index += 1) {
      const source = queries[Math.min(queries.length - 1, Math.floor((index / max) * queries.length))];
      const segment = document.createElement('i');
      segment.className = source.category;
      root.append(segment);
    }
  }
  root.title = queries.map((query) => `${query.index}:${CATEGORIES[query.category]?.label || query.category}`).join(' · ');
  return root;
}

function renderTable() {
  const body = $('#case-rows');
  body.replaceChildren();
  const cases = state.cases;
  $('#table-count').textContent = `· ${cases.length} 条`;
  $('#table-empty').hidden = cases.length > 0;
  $('.table-wrap').hidden = cases.length === 0;
  const fragment = document.createDocumentFragment();
  for (const item of cases) {
    const row = document.createElement('tr');
    row.tabIndex = 0;
    row.dataset.caseId = item.id;
    if (item.id === state.selectedId) row.classList.add('is-selected');
    const label = el('td');
    const labelWrap = el('span', 'case-label');
    labelWrap.append(el('span', '', item.topic || item.id), el('small', '', item.id));
    label.append(labelWrap);
    const status = el('td');
    status.append(el('span', `table-status ${item.status}`, STATUSES[item.status] || '未知'));
    const queries = el('td', '', item.queryTotal);
    const repeat = el('td', '', pct(item.repeatRate));
    const fresh = el('td', '', pct(item.newRate));
    const behaviour = el('td');
    behaviour.append(el('span', `table-behaviour ${item.behavior}`, behaviorLabel(item.behavior)));
    const print = el('td');
    print.append(miniFingerprint(item.queries));
    row.append(label, status, queries, repeat, fresh, behaviour, print);
    row.addEventListener('click', () => setSelectedCase(item.id, true));
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        setSelectedCase(item.id, true);
      }
    });
    fragment.append(row);
  }
  body.append(fragment);
}

function render() {
  renderKpis();
  renderBehaviourLegend();
  renderChart();
  renderDetail();
  renderTable();
  const select = $('#case-select');
  if (select) select.disabled = state.cases.length === 0;
}

function bindEvents() {
  $('#run-select').addEventListener('change', (event) => {
    hideTooltip();
    chooseRun(event.target.value);
  });
  $('#completed-only').addEventListener('change', (event) => {
    state.completedOnly = event.target.checked;
    state.cases = filteredCases(state.run, state.completedOnly);
    state.selectedId = defaultCase(state.cases)?.id || null;
    populateCaseSelect(state.cases);
    render();
  });
  $('#case-select').addEventListener('change', (event) => {
    setSelectedCase(event.target.value);
  });
  $('.chart-wrap').addEventListener('mouseleave', hideTooltip);
  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    hideTooltip();
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (state.data) renderChart();
    }, 150);
  });
}

async function load() {
  try {
    const response = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    if (!Array.isArray(state.data.runs) || !state.data.runs.length) throw new Error('数据中没有评估集');
    populateRuns(state.data);
    renderMeta();
    $('#loading').hidden = true;
    const initialRunId = $('#run-select').value;
    state.completedOnly = $('#completed-only').checked;
    chooseRun(initialRunId);
    bindEvents();
  } catch (error) {
    $('#loading').hidden = true;
    $('#load-error').hidden = false;
    $('#load-error').textContent = `无法加载搜索行为数据：${error.message}。请确认 /assets/search-behavior.json 可访问。`;
  }
}

load();
