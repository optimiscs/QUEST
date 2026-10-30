export function createOverview(context) {
  const { state, dom, activeCase, riskInfo, caseState, judgeTag, icon, formatDuration, safeURL, escapeHTML, escapeAttr } = context;
  function collectSources(c) {
    const map = new Map();
    c.steps.forEach((step) => {
      if (step.kind !== "read" || !step.tool) return;
      (step.tool.pages || []).forEach((page) => {
        if (!map.has(page.url)) map.set(page.url, page);
      });
    });
    return Array.from(map.values());
  }

  function overviewStateLabel(status) {
    return {running: "评估进行中", pass: "研究完成 · 通过", fail: "研究完成 · 未通过", scored: "研究完成 · 已评分", stopped: "评估已终止", error: "未评分或评分错误"}[status.key] || "状态未知";
  }

  function renderOverview() {
    const c = activeCase();
    dom.overviewQuestion.textContent = c.question;
    const visualState = caseState(c);
    dom.overviewState.textContent = overviewStateLabel(visualState);
    judgeTag(c, dom.overviewJudge);
    dom.overviewAnswer.textContent = c.answer;
    dom.overviewAnswer.classList.toggle("is-long", c.answer.length > 15);
    dom.overviewAnswerNote.textContent = c.answerNote;
    const facts = [
      [c.stats.steps, "轮次"],
      [c.stats.searchCalls + c.stats.readCalls + c.stats.computeCalls, "工具调用"],
      [c.stats.pagesRead, "网页读取"],
      [formatDuration(c.durationSeconds), "总用时"],
    ];
    dom.overviewFacts.innerHTML = facts
      .map(([value, label]) => `<div class="answer-fact"><b>${escapeHTML(value)}</b><span>${label}</span></div>`)
      .join("");
    const sources = collectSources(c);
    dom.overviewSourceCount.textContent = sources.length > 6 ? `${sources.length} 个来源 · 展示前 6 个` : `${sources.length} 个来源`;
    dom.overviewSources.innerHTML = sources.length
      ? sources
          .slice(0, 6)
          .map((page) => {
            const url = safeURL(page.url);
            const mark = (page.domain || "web").replace(/^www\./, "").charAt(0).toUpperCase();
            return `<a class="source-card" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">
              <span class="source-favicon">${escapeHTML(mark)}</span>
              <span><strong>${escapeHTML(page.title)}</strong><span>${escapeHTML(page.domain)}</span></span>
              ${icon("arrow-up-right")}
            </a>`;
          })
          .join("")
      : `<div class="tool-empty">本轨迹未保留可展示的网页来源。</div>`;
    const risk = riskInfo(c);
    dom.overviewIntegrity.innerHTML = `<b>完整性说明</b> · ${visualState.label} / ${risk.short}。${risk.long}`;
  }


  return { collectSources, overviewStateLabel, renderOverview };
}
