import { TraceSearch } from './search';
export function createTrajectory(context) {
  const { state, dom, activeCase, $, $$, icon, roleChip, toolDisplayName, toolPreview, toolSub, statusLabel, caseState, judgeTag, escapeHTML, escapeAttr, clampText, pad, formatSeconds, number, safeURL, formatAxis } = context;
  let stepIndex = new Map();
  let labelScheduled = false;
  const traceSearch = new TraceSearch(matches => { state.searchMatches = matches; updateSearchMeta(); });
  dom.logBody.addEventListener('toggle', event => {
    const row = event.target;
    if (!row.matches('.log-row')) return;
    if (row.open) hydrateRow(row);
    if (!labelScheduled) {
      labelScheduled = true;
      requestAnimationFrame(() => { labelScheduled = false; updateExpandAllLabel(); });
    }
  }, true);

  function buildAssistantRow(step) {
    const preview = clampText(step.thought || "模型未输出可见推理", 260);
    return `<details class="log-row is-assistant${step.kind === "answer" ? " is-answer" : ""}" data-step="${step.n}" data-role="assistant">
      <summary>
        <span class="log-dot"></span>
        ${roleChip("assistant")}
        <span class="log-summary-main"><span class="log-summary-text">${escapeHTML(preview)}</span></span>
        <span class="log-meta">${pad(step.n)} · ${formatSeconds(step.model_seconds)}</span>
        ${icon("chevron", "icon log-chevron")}
      </summary>
      <div class="log-detail-slot"></div>
    </details>`;
  }

  function buildToolRow(step) {
    const label = toolDisplayName(step);
    const preview = clampText(toolPreview(step), 150);
    const sub = toolSub(step);
    return `<details class="log-row is-tool" data-step="${step.n}" data-role="tool">
      <summary>
        <span class="log-dot"></span>
        ${roleChip("tool")}
        <span class="log-summary-main">
          <span class="log-tool-prefix">${escapeHTML(label)}</span>
          <span class="log-summary-text">${escapeHTML(preview)}</span>
          <span class="log-summary-sub">${escapeHTML(sub)}</span>
        </span>
        <span class="log-meta">${formatSeconds(step.tool_seconds)}</span>
        ${icon("chevron", "icon log-chevron")}
      </summary>
      <div class="log-detail-slot"></div>
    </details>`;
  }

  function renderLog() {
    const c = activeCase();
    stepIndex = new Map(c.steps.map(step => [step.n, step]));
    const rows = c.steps.flatMap((step) => {
      const result = [buildAssistantRow(step)];
      if (step.tool) result.push(buildToolRow(step));
      return result;
    });
    dom.logBody.innerHTML = rows.join("");
    state.searchMatches = null;
    traceSearch.index(c.steps);
    dom.logRoundCount.textContent = `${c.stats.steps} 轮`;
    dom.logEventCount.textContent = `${rows.length} 条事件`;
    dom.expandAll.textContent = "全部展开";
    dom.logGroupState.classList.remove("is-fail", "is-pass", "is-running", "is-stopped", "is-error");
    dom.logGroupState.classList.add(`is-${caseState(c).key}`);
    dom.logGroupState.innerHTML = `<i></i>${statusLabel(c)}`;
    dom.conclusionAnswer.textContent = c.answer;
    dom.conclusionNote.textContent = c.answerNote;
    judgeTag(c, dom.conclusionJudge);
    dom.logEmpty.hidden = true;
    dom.logConclusion.hidden = false;
    dom.groupToggle.setAttribute("aria-expanded", String(!state.groupCollapsed));
    $(".log-shell").classList.toggle("is-collapsed", state.groupCollapsed);
    updateSearchMeta();

  }

  function updateExpandAllLabel() {
    const rows = $$(".log-row", dom.logBody);
    if (!rows.length) return;
    const allOpen = rows.every((row) => row.open);
    dom.expandAll.textContent = allOpen ? "全部收起" : "全部展开";
  }

  function hydrateRow(row) {
    if (row.dataset.hydrated === "1") return;
    const stepNumber = Number(row.dataset.step);
    const role = row.dataset.role;
    const step = stepIndex.get(stepNumber);
    const slot = $(".log-detail-slot", row);
    if (!step || !slot) return;
    slot.innerHTML = role === "assistant" ? assistantDetailHTML(step) : toolDetailHTML(step);
    row.dataset.hydrated = "1";
  }

  function assistantDetailHTML(step) {
    const paragraphs = String(step.thought || "").split(/\n{2,}/).filter(Boolean);
    const body = paragraphs.length
      ? paragraphs.map((part) => `<p>${escapeHTML(part)}</p>`).join("")
      : `<p>模型未输出可见推理。</p>`;
    return `<div class="log-detail">
      <div class="detail-eyebrow"><i></i>推理过程 · T+${formatAxis(step.modelStart)} · ${formatSeconds(step.model_seconds)}</div>
      <div class="assistant-detail">${body}</div>
    </div>`;
  }

  function toolDetailHTML(step) {
    const name = toolDisplayName(step);
    const toolMeta = `T+${formatAxis(step.toolStart)} · ${formatSeconds(step.tool_seconds)}`;
    let body = `<div class="tool-empty">没有可展示的工具详情。</div>`;
    if (step.kind === "search") {
      const queries = step.tool?.queries || [];
      body = queries.length
        ? queries
            .map((query) => {
              const results = (query.results || [])
                .map((result) => {
                  const url = safeURL(result.url);
                  return `<a class="result-card" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">
                    <strong>${escapeHTML(result.title)}</strong>
                    <p>${escapeHTML(result.snippet)}</p>
                    <span class="result-domain">${escapeHTML(result.domain)}</span>
                  </a>`;
                })
                .join("");
              return `<div class="query-block">
                <div class="query-line"><strong>${escapeHTML(query.query)}</strong><span>${number(query.count)} 条结果</span></div>
                <div class="query-results">${results || `<span class="tool-empty">未返回结果</span>`}</div>
              </div>`;
            })
            .join("")
        : `<div class="tool-empty">没有可展示的查询。</div>`;
    } else if (step.kind === "read") {
      const pages = step.tool?.pages || [];
      body = pages.length
        ? pages
            .map((page) => {
              const url = safeURL(page.url);
              const evidence = [page.rationale, page.evidence]
                .filter(Boolean)
                .map((text) => escapeHTML(text))
                .join("<br><br>");
              return `<article class="page-detail-card">
                <div class="page-detail-head">
                  <div>
                    <a class="page-detail-title" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(page.title)}</a>
                    <div class="page-detail-domain">${escapeHTML(page.domain)} · 读取 ${formatSeconds(page.readerSeconds ?? page.summarySeconds ?? null)}</div>
                  </div>
                  <a class="page-detail-link" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" aria-label="在新窗口打开来源">${icon("arrow-up-right")}</a>
                </div>
                <p class="page-detail-summary">${escapeHTML(page.summary)}</p>
                ${evidence ? `<details class="page-detail-evidence"><summary>提取依据</summary><div class="evidence-box"><b>PAGE EXTRACTION</b>${evidence}</div></details>` : ""}
              </article>`;
            })
            .join("")
        : `<div class="tool-empty">没有返回页面。</div>`;
    } else if (step.kind === "compute") {
      const code = step.tool?.code || "";
      const output = (step.tool?.stdout || "").replace(/^stdout:\s*/i, "").replace(/^stderr:\s*/i, "");
      body = `<div class="code-block">
        <div class="code-block-head"><span>PYTHON / SANDBOX</span><span>${pad((code.match(/\n/g) || []).length + 1)} 行</span></div>
        <pre>${escapeHTML(code)}</pre>
        ${output ? `<div class="code-output"><span>输出</span>${escapeHTML(output)}</div>` : ""}
      </div>`;
    }
    const headerDetail = step.kind === "search"
      ? `${(step.tool?.queries || []).length} 次查询 · ${number(step.tool?.resultCount || 0)} 条结果`
      : step.kind === "read"
        ? `${(step.tool?.pages || []).length} 个页面`
        : "Python 解释器";
    return `<div class="log-detail">
      <div class="tool-detail-head">
        <div class="tool-detail-title"><b>${escapeHTML(name)}</b><span>${escapeHTML(headerDetail)}</span></div>
        <div class="tool-detail-meta">${toolMeta}</div>
      </div>
      ${body}
    </div>`;
  }

  function updateSearchMeta() {
    if (!state.data) return;
    const q = state.query.trim().toLowerCase();
    const rows = $$(".log-row", dom.logBody);
    let visible = 0;
    rows.forEach((row) => {
      const match = !q || state.searchMatches === null || state.searchMatches.has(Number(row.dataset.step));
      row.hidden = !match;
      if (match) visible += 1;
    });
    dom.searchCount.textContent = q ? String(visible) : "";
    dom.logEventCount.textContent = q ? `${visible} 条匹配` : `${rows.length} 条事件`;
    dom.logEmpty.hidden = !(q && visible === 0);
    dom.logConclusion.hidden = Boolean(q && visible === 0);
    if (q) {
      state.groupCollapsed = false;
      dom.groupToggle.setAttribute("aria-expanded", "true");
      $(".log-shell").classList.remove("is-collapsed");
    }
    updateExpandAllLabel();
  }

  function applySearch(value) {
    state.query = value;
    traceSearch.search(value);
    if (!value.trim()) { state.searchMatches = null; updateSearchMeta(); }
  }


  return { buildAssistantRow, buildToolRow, renderLog, updateExpandAllLabel, hydrateRow, assistantDetailHTML, toolDetailHTML, updateSearchMeta, applySearch, traceSearch };
}
