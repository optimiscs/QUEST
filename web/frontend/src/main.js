import { createStatus } from './shared/status';
import { createWorkspaces } from './features/workspaces';
import { createOverview } from './features/overview';
import { createTrajectory } from './features/trajectory';
import { createTimeline } from './features/timeline';
import { renderMarkdown } from './shared/markdown';
import { escapeHTML, escapeAttr, safeURL, pad, number, pluralCount, formatSeconds, formatDuration, formatAxis, clampText } from './shared/format';
import './styles.css';
import { getJSON, loadRun, loadTrace, runURL } from './api/client';
import { TraceCache } from './state/trace-cache';
import { deriveSessionStats, compactTokens } from './features/session-stats';


  const state = {
    data: null,
    index: 0,
    tab: "trajectory",
    chartMode: "duration",
    query: "",
    groupCollapsed: false,
    manifest: [],
    datasetId: null,
    datasetMeta: null,
    activeTrace: null,
    runId: null,
    revision: null,
    taskFilter: "all",
    workspaceStats: {},
    workspaceStatsKey: "",
  };

  const { caseState, caseStateDetail, hasGroundTruth, runLifecycleState, statusLabel, riskInfo } = createStatus(state);

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const isMobile = () => window.innerWidth <= 920;

  const dom = {
    app: $("#app"),
    sidebar: $("#sidebar"),
    sidebarBackdrop: $("#sidebarBackdrop"),
    sidebarToggle: $("#sidebarToggle"),
    sidebarClose: $("#sidebarClose"),
    brandLink: $("#brandLink"),
    taskList: $("#taskList"),
    taskFilter: $("#taskFilter"),
    workspaceTrigger: $("#workspaceTrigger"),
    workspaceMenu: $("#workspaceMenu"),
    workspaceName: $("#workspaceName"),
    workspaceSub: $("#workspaceSub"),
    workspaceFootSite: $("#workspaceFootSite"),
    datasetMenuDivider: $("#datasetMenuDivider"),
    datasetOptions: $("#datasetOptions"),
    workspaceActionMenu: $("#workspaceActionMenu"),
    breadcrumbWorkspace: $("#breadcrumbWorkspace"),
    breadcrumbBenchmark: $("#breadcrumbBenchmark"),
    modeModel: $("#modeModel"),
    navTraceCount: $("#navTraceCount"),
    taskIndexCount: $("#taskIndexCount"),
    summaryPass: $("#summaryPass"),
    summaryTurns: $("#summaryTurns"),
    summaryTools: $("#summaryTools"),
    openBriefTop: $("#openBriefTop"),
    openBrief: $("#openBrief"),
    downloadData: $("#downloadData"),
    openInfoSide: $("#openInfoSide"),
    openInfoTop: $("#openInfoTop"),
    copyLinkTop: $("#copyLinkTop"),
    tabOverview: $("#tabOverview"),
    tabTrajectory: $("#tabTrajectory"),
    tabMeta: $("#tabMeta"),
    trajectoryView: $("#trajectoryView"),
    overviewView: $("#overviewView"),
    contextIndex: $("#contextIndex"),
    contextField: $("#contextField"),
    contextJudge: $("#contextJudge"),
    contextTitle: $("#contextTitle"),
    contextQuestion: $("#contextQuestion"),
    contextStats: $("#contextStats"),
    traceSearch: $("#traceSearch"),
    searchCount: $("#searchCount"),
    chartTitle: $("#chartTitle"),
    chartSub: $("#chartSub"),
    chartLegend: $("#chartLegend"),
    timelineVisual: $("#timelineVisual"),
    logRoundCount: $("#logRoundCount"),
    logGroupState: $("#logGroupState"),
    logEventCount: $("#logEventCount"),
    expandAll: $("#expandAll"),
    groupToggle: $("#groupToggle"),
    logBody: $("#logBody"),
    logEmpty: $("#logEmpty"),
    logConclusion: $("#logConclusion"),
    conclusionAnswer: $("#conclusionAnswer"),
    conclusionNote: $("#conclusionNote"),
    conclusionJudge: $("#conclusionJudge"),
    viewFullAnswer: $("#viewFullAnswer"),
    viewGroundTruth: $("#viewGroundTruth"),
    overviewQuestion: $("#overviewQuestion"),
    overviewState: $("#overviewState"),
    overviewJudge: $("#overviewJudge"),
    overviewAnswer: $("#overviewAnswer"),
    overviewAnswerNote: $("#overviewAnswerNote"),
    overviewFacts: $("#overviewFacts"),
    overviewViewFull: $("#overviewViewFull"),
    overviewCopyAnswer: $("#overviewCopyAnswer"),
    overviewGroundTruth: $("#overviewGroundTruth"),
    overviewSourceCount: $("#overviewSourceCount"),
    overviewSources: $("#overviewSources"),
    overviewIntegrity: $("#overviewIntegrity"),
    tabDate: $("#tabDate"),
    footerSource: $("#footerSource"),
    footerFine: $("#footerFine"),
    dockModel: $("#dockModel"),
    dockIndex: $("#dockIndex"),
    dockSummary: $("#dockSummary"),
    dockTabButton: $("#dockTabButton"),
    dockCopy: $("#dockCopy"),
    prevTask: $("#prevTask"),
    nextTask: $("#nextTask"),
    modal: $("#modal"),
    modalKicker: $("#modalKicker"),
    modalTitle: $("#modalTitle"),
    modalBody: $("#modalBody"),
    modalClose: $("#modalClose"),
    toast: $("#toast"),
    toastText: $("#toastText"),
  };

  const icon = (name, className = "icon") =>
    `<svg class="${className}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  function nowHash(index = state.index, tab = state.tab) {
    return `#${state.data?.cases[index]?.id || `trace-${pad(index + 1)}`}${tab === "overview" ? "/overview" : ""}`;
  }

  function parseHash() {
    const raw = window.location.hash.replace(/^#\/?/, "");
    const [tracePart, viewPart] = raw.split("/");
    const found = state.data ? state.data.cases.findIndex((item) => item.id === tracePart) : -1;
    const index = found >= 0 ? found : 0;
    return {
      index: Number.isFinite(index) ? index : 0,
      tab: viewPart === "overview" ? "overview" : "trajectory",
    };
  }

  function activeCase() {
    return state.activeTrace;
  }

  function rowCount(caseData) {
    return caseData.steps.reduce((total, step) => total + 1 + (step.tool ? 1 : 0), 0);
  }

  function toolLabel(step) {
    return step.tool?.name || "";
  }

  function toolDisplayName(step) {
    const name = toolLabel(step);
    if (name === "PythonInterpreter") return "python";
    return name;
  }

  function toolPreview(step) {
    if (step.kind === "search") {
      const queries = step.tool?.queries || [];
      const first = queries[0]?.query || "无查询";
      const extra = queries.length > 1 ? ` +${queries.length - 1}` : "";
      return `${first}${extra}`;
    }
    if (step.kind === "read") {
      const pages = step.tool?.pages || [];
      return pages[0]?.title || pages[0]?.domain || "未返回页面";
    }
    if (step.kind === "compute") {
      const firstLine = (step.tool?.code || "").split("\n").find((line) => line.trim()) || "Python sandbox";
      return cleanCodePreview(firstLine);
    }
    return step.tool?.name || "";
  }

  function cleanCodePreview(value) {
    return String(value || "").replace(/^\s*#\s?/, "").slice(0, 120);
  }

  function toolSub(step) {
    if (step.kind === "search") {
      const queries = step.tool?.queries || [];
      return `${queries.length} 次查询 · ${number(step.tool?.resultCount || 0)} 条结果`;
    }
    if (step.kind === "read") {
      const pages = step.tool?.pages || [];
      return `${pages.length} 个页面${pages[0]?.domain ? ` · ${pages[0].domain}` : ""}`;
    }
    if (step.kind === "compute") {
      const lines = (step.tool?.code || "").split("\n").length;
      return `${lines} 行代码 · 沙箱`;
    }
    return "";
  }

  function roleChip(role) {
    if (role === "assistant") return `<span class="role-chip role-assistant">助手</span>`;
    return `<span class="role-chip role-tool">工具</span>`;
  }





  const TASK_FILTERS = ["all", "pass", "fail", "running", "stopped", "error"];

  function matchesTaskFilter(caseData) {
    return state.taskFilter === "all" || caseState(caseData).key === state.taskFilter;
  }

  function filteredTaskEntries() {
    return state.data.cases
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => matchesTaskFilter(item));
  }

  function renderTaskFilter() {
    if (!dom.taskFilter) return;
    const counts = { all: 0, pass: 0, fail: 0, running: 0, stopped: 0, error: 0 };
    state.data.cases.forEach((item) => {
      counts.all += 1;
      counts[caseState(item).key] += 1;
    });
    $$("[data-filter-count]", dom.taskFilter).forEach((element) => {
      element.textContent = String(counts[element.dataset.filterCount] ?? 0);
    });
    $$("[data-task-filter]", dom.taskFilter).forEach((button) => {
      const active = button.dataset.taskFilter === state.taskFilter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function setTaskFilter(filter) {
    if (!TASK_FILTERS.includes(filter)) return;
    state.taskFilter = filter;
    renderTaskList();
  }

  function judgeTag(caseData, element) {
    if (!element) return;
    const status = caseState(caseData);
    element.classList.remove("is-fail", "is-pass", "is-running", "is-stopped", "is-error", "is-scored");
    element.classList.add(`is-${status.key}`);
    element.innerHTML = `<i></i>${status.label}`;
    element.title = caseStateDetail(caseData);
  }



  /* ---------- workspace folders ---------- */


  const siteLocale = /(?:^|\/)trace-viewer-zh(?:\/|$)/.test(window.location.pathname) ? "zh" : "en";
  const { setupWorkspaceSwitcher, readWorkspaceLayout, saveWorkspaceLayout, defaultWorkspaceFolder, workspaceFolderTitle, workspaceDatasetLabel, workspaceStatsFor, workspaceMetricsHTML, workspaceGroupPassHTML, workspaceDatasetRow, renderDatasetOptions, closeWorkspaceActionMenu, openWorkspaceActionMenu, toggleWorkspaceFolder, startInlineRename, beginCreateFolder, updateWorkspaceLinks, loadWorkspaceManifest, refreshWorkspaceStats, fitWorkspaceMenu, openWorkspaceMenu, closeWorkspaceMenu, toggleWorkspaceMenu } = createWorkspaces({ state, dom, $, $$, icon, escapeHTML, escapeAttr, nowHash, runLifecycleState, showToast, getJSON, siteLocale });

  /* ---------- chrome and navigation ---------- */

  function renderTaskList() {
    renderTaskFilter();
    const entries = filteredTaskEntries();
    if (!entries.length) {
      dom.taskList.innerHTML = `<div class="task-list-empty">没有符合当前筛选的评估轨迹</div>`;
      return;
    }
    dom.taskList.innerHTML = entries
      .map(({ item, index }) => {
        const active = index === state.index;
        const status = caseState(item);
        const statusDetail = caseStateDetail(item);
        return `<button class="task-item${active ? " is-active" : ""}" type="button" data-case="${index}" aria-current="${active ? "true" : "false"}" title="${escapeAttr(item.topicZh)}">
          <span class="task-num">${pad(item.index)}</span>
          <span class="task-copy"><strong>${escapeHTML(item.topicZh)}</strong><small>${item.stats.steps} 轮 · ${formatDuration(item.durationSeconds)}</small></span>
          <span class="task-status-dot is-${status.key}" title="${escapeAttr(statusDetail)}" aria-label="${escapeAttr(statusDetail)}"></span>
        </button>`;
      })
      .join("");
    const active = $(".task-item.is-active", dom.taskList);
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  function renderTabs() {
    const isTrajectory = state.tab === "trajectory";
    dom.trajectoryView.hidden = !isTrajectory;
    dom.overviewView.hidden = isTrajectory;
    dom.tabTrajectory.classList.toggle("is-active", isTrajectory);
    dom.tabOverview.classList.toggle("is-active", !isTrajectory);
    dom.tabTrajectory.setAttribute("aria-selected", String(isTrajectory));
    dom.tabOverview.setAttribute("aria-selected", String(!isTrajectory));
    const navTrajectory = $('.nav-item[data-tab="trajectory"]');
    const navOverview = $('.nav-item[data-tab="overview"]');
    navTrajectory?.classList.toggle("is-active", isTrajectory);
    navOverview?.classList.toggle("is-active", !isTrajectory);
    dom.dockTabButton.textContent = isTrajectory ? "查看结论" : "查看轨迹";
    dom.dockTabButton.dataset.action = isTrajectory ? "overview" : "trajectory";
  }

  function renderTabMeta() {
    const c = activeCase();
    dom.tabMeta.textContent = `任务 ${pad(c.index)} · ${c.stats.steps} 轮`;
    updateWorkspaceLinks();
  }

  let renderedTrace = null;

  function setTab(tab, options = {}) {
    if (!state.data) return;
    if (tab !== "trajectory" && tab !== "overview") return;
    if (state.tab === tab && !options.force) {
      return;
    }
    state.tab = tab;
    if (tab === "trajectory" && renderedTrace !== activeCase()) {
      renderChart(); renderLog(); renderedTrace = activeCase();
    }
    renderTabs();
    renderTabMeta();
    $("#mainScroll").scrollTop = 0;
    if (options.hash !== false) {
      history.replaceState(null, "", nowHash(state.index, state.tab));
    }
  }

  const traceCache = new TraceCache();
  let selectionController = null;
  let navigationGeneration = 0;

  async function fetchCase(summary, signal) {
    const key = JSON.stringify([state.runId, summary.id, summary.revision]);
    let value = traceCache.get(key);
    if (!value) {
      value = await loadTrace(state.runId, summary.id, signal, summary.revision);
      traceCache.set(key, value);
    }
    return value;
  }

  async function selectCase(index, options = {}) {
    if (!state.data) return;
    const target = Math.max(0, Math.min(state.data.cases.length - 1, index));
    const generation = ++navigationGeneration;
    selectionController?.abort();
    selectionController = new AbortController();
    dom.app.setAttribute('aria-busy', 'true');
    try {
      const detail = await fetchCase(state.data.cases[target], selectionController.signal);
      if (generation !== navigationGeneration) return;
      state.activeTrace = detail;
      state.index = target;
      state.query = '';
      state.groupCollapsed = false;
      state.searchMatches = null;
      dom.traceSearch.value = '';
      renderTaskList();
      renderAllContent();
      if (options.push !== false) history.pushState(null, '', nowHash(state.index, state.tab));
      $('#mainScroll').scrollTop = 0;
      if (isMobile()) closeSidebar();
    } catch (error) {
      if (error.name !== 'AbortError') showToast('轨迹加载失败，请重试');
    } finally {
      if (generation === navigationGeneration) dom.app.removeAttribute('aria-busy');
    }
  }

  /* ---------- context ---------- */

  function renderContext() {
    const c = activeCase();
    dom.contextIndex.textContent = `任务 ${pad(c.index)}`;
    dom.contextField.textContent = c.fieldZh || c.field;
    judgeTag(c, dom.contextJudge);
    dom.contextTitle.textContent = c.topicZh || c.topic;
    dom.contextQuestion.textContent = c.question;
    dom.contextQuestion.title = c.question;
    const stats = [
      [c.stats.steps, "轮次"],
      [formatDuration(c.durationSeconds), "用时"],
      [c.stats.searchCalls, "搜索"],
      [c.stats.readCalls, "读取"],
      [c.stats.uniqueSources, "来源"],
    ];
    dom.contextStats.innerHTML = stats
      .map(([value, label]) => `<span class="context-stat"><b>${escapeHTML(value)}</b><span>${label}</span></span>`)
      .join("");
  }

  /* ---------- timeline chart ---------- */

  const { makeBar, axisHTML, laneHTML, renderDurationChart, renderRoundsChart, renderCallsChart, renderChart } = createTimeline({ state, dom, activeCase, $$, formatAxis, escapeAttr, formatDuration, number, formatSeconds, escapeHTML, pad });

  /* ---------- log rendering ---------- */

  const { buildAssistantRow, buildToolRow, renderLog, updateExpandAllLabel, hydrateRow, assistantDetailHTML, toolDetailHTML, updateSearchMeta, applySearch, traceSearch } = createTrajectory({ state, dom, activeCase, $, $$, icon, roleChip, toolDisplayName, toolPreview, toolSub, statusLabel, caseState, judgeTag, escapeHTML, escapeAttr, clampText, pad, formatSeconds, number, safeURL, formatAxis });

  /* ---------- overview ---------- */

  const { collectSources, overviewStateLabel, renderOverview } = createOverview({ state, dom, activeCase, riskInfo, caseState, judgeTag, icon, formatDuration, safeURL, escapeHTML, escapeAttr });

  /* ---------- current task statistics ---------- */
  const statusRoot = $("#sessionStatus");
  const statusCards = ["Timing", "Tokens", "Context"].map(name => ({button: $(`#session${name}Button`), card: $(`#session${name}Card`)}));
  function closeStatusCards() {
    statusCards.forEach(({button, card}) => { card.hidden = true; button.setAttribute("aria-expanded", "false"); });
  }
  statusCards.forEach(({button, card}) => button.addEventListener("click", () => {
    const opening = card.hidden;
    closeStatusCards();
    if (opening) { card.hidden = false; button.setAttribute("aria-expanded", "true"); }
  }));
  document.addEventListener("click", event => { if (!statusRoot.contains(event.target)) closeStatusCards(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") closeStatusCards(); });
  function renderSessionStats(trace) {
    const s = deriveSessionStats(trace);
    const num = value => value === null ? "未记录" : new Intl.NumberFormat("en-US").format(value);
    const duration = value => value === null ? "未记录" : formatDuration(value);
    const percent = value => value === null ? "未记录" : `${Math.round(value * 100)}%`;
    const rate = s.tps === null ? "未记录" : `${s.tps.toFixed(1).replace(/\.0$/, "")} tok/s`;
    const rows = pairs => pairs.map(([label, value]) => `<div class="session-card-row"><span>${label}</span><strong>${escapeHTML(value)}</strong></div>`).join("");
    $("#sessionTimingSummary").textContent = `${s.rounds === null ? "轮次未记录" : `${num(s.rounds)} 轮`} · ${s.events === null ? "步数未记录" : `${num(s.events)} 步`} · ${rate}`;
    $("#sessionTokensSummary").textContent = `${compactTokens(s.total)}${s.total === null ? "" : " tok"} · 缓存命中 ${percent(s.cacheRate)}`;
    $("#sessionContextSummary").textContent = `上下文 ${percent(s.contextRate)}`;
    $("#sessionTimingCard").innerHTML = `<h3>◴　会话统计</h3>${rows([["模型用时", duration(s.modelSeconds)], ["工具调用用时", duration(s.toolSeconds)], ["首 token 平均（TTFT）", duration(s.ttftSeconds)], ["输出速度（TPS）", rate]])}<p class="session-card-note">速度按模型调用总耗时计算；TTFT 样本 ${num(s.ttftSamples)} / 已完成调用 ${num(s.completedCalls)}。</p>`;
    $("#sessionTokensCard").innerHTML = `<h3>▤　Token 用量 <strong>${s.total === null ? "未记录" : `${num(s.total)} tok`}</strong></h3>${rows([["缓存命中", percent(s.cacheRate)], ["未缓存输入", num(s.uncached)], ["缓存读取", num(s.cached)], ["输出", num(s.outputTokens)]])}${s.cacheSamples !== null && s.usageSamples !== null && s.cacheSamples < s.usageSamples ? `<p class="session-card-note">缓存数据仅覆盖 ${num(s.cacheSamples)} / ${num(s.usageSamples)} 次调用，命中率和输入分项仅按已记录部分计算。</p>` : ''}`;
    const progress = s.contextRate === null ? 0 : Math.min(100, s.contextRate * 100);
    $("#sessionContextCard").innerHTML = `<h3>上下文已用 ${percent(s.contextRate)} <strong>${s.contextUsed === null ? "未记录" : `${compactTokens(s.contextUsed)} / ${s.contextCapacity === null ? "容量未记录" : compactTokens(s.contextCapacity)}`}</strong></h3><div class="session-progress" role="progressbar" aria-label="上下文使用量" ${s.contextRate === null ? "" : `aria-valuenow="${Math.round(progress)}" aria-valuemin="0" aria-valuemax="100"`}><i style="width:${progress}%"></i></div>${rows([["系统提示词", num(s.systemTokens)], ["工具定义", num(s.toolTokens)], ["对话消息", num(s.messageTokens)]])}${s.breakdownEstimated ? '<p class="session-card-note">分类按文本估算，不含模板开销；上下文总量以最近一次请求的服务端计数为准。</p>' : ''}`;
  }

  /* ---------- dock and summary ---------- */

  function renderDock() {
    const c = activeCase();
    dom.dockIndex.textContent = pad(state.index + 1);
    dom.dockSummary.textContent = `${c.stats.steps} 轮 · ${formatDuration(c.durationSeconds)}`;
    dom.prevTask.disabled = state.index === 0;
    dom.nextTask.disabled = state.index === state.data.cases.length - 1;
    $(".dock-position span").textContent = String(state.data.cases.length);
  }

  function renderRunChrome() {
    const { run } = state.data;
    const lifecycle = runLifecycleState();
    const summaryLive = $(".summary-live");
    const runState = $(".run-state");
    [summaryLive, runState].forEach((element) => {
      if (!element) return;
      element.classList.remove("is-pass", "is-running", "is-stopped", "is-error");
      element.classList.add(`is-${lifecycle.key}`);
    });
    if (summaryLive) summaryLive.innerHTML = `<i></i>${lifecycle.short}`;
    if (runState) runState.innerHTML = `<i></i>${lifecycle.label}`;
    if (dom.modeModel) dom.modeModel.textContent = run.model || "QUEST-4B";
    if (dom.dockModel) dom.dockModel.textContent = run.model || "QUEST-4B";
    if (dom.tabDate) dom.tabDate.textContent = run.dateShort || run.date || "—";
    if (dom.footerSource) dom.footerSource.textContent = `${run.model || "Agent"} · ${run.benchmark || "Evaluation"} · ${run.dateShort || run.date || "—"}`;
    if (dom.footerFine) dom.footerFine.textContent = `${run.judgePassed ?? "—"} / ${run.judgeScored ?? run.totalCases ?? "—"} judge accepted · one rollout per task · judge acceptance ≠ accuracy.`;
  }

  function renderSidebarSummary() {
    const { run } = state.data;
    dom.navTraceCount.textContent = String(run.totalCases);
    dom.taskIndexCount.textContent = String(run.totalCases);
    dom.summaryPass.innerHTML = `${pad(run.judgePassed)}<small>/${run.judgeScored ?? run.totalCases}</small>`;
    dom.summaryTurns.textContent = String(run.rounds);
    dom.summaryTools.textContent = String(run.toolCalls);
  }

  function renderAllContent() {
    if (!state.data) return;
    renderTabs();
    renderTabMeta();
    renderContext();
    if (state.tab === "trajectory") { renderChart(); renderLog(); renderedTrace = activeCase(); }
    else renderedTrace = null;
    renderOverview();
    renderDock();
    renderSessionStats(activeCase());
    const groundTruthAvailable = hasGroundTruth(activeCase());
    [dom.overviewGroundTruth, dom.viewGroundTruth].forEach((button) => {
      if (button) button.hidden = !groundTruthAvailable;
    });
    document.title = `${activeCase().topicZh} · ${state.datasetMeta ? state.datasetMeta.label + " · " : ""}Search Agent 轨迹展示页面`;
  }

  /* ---------- modal and utilities ---------- */

  function openModal(kicker, title, html, options = {}) {
    if (dom.modal.open) return;
    dom.modalKicker.textContent = kicker;
    dom.modalTitle.textContent = title;
    dom.modalBody.innerHTML = html;
    dom.modalBody.classList.toggle("is-brief", Boolean(options.brief));
    if (typeof dom.modal.showModal === "function") dom.modal.showModal();
    else dom.modal.setAttribute("open", "");
    dom.modalBody.scrollTop = 0;
  }

  function closeModal() {
    if (typeof dom.modal.close === "function") dom.modal.close();
    else dom.modal.removeAttribute("open");
  }

  function openBrief() {
    const c = activeCase();
    openModal(
      `任务 ${pad(c.index)} · ${c.fieldZh || c.field}`,
      "完整问题",
      `<p>${escapeHTML(c.question)}</p>`,
      { brief: true }
    );
  }

  function openFullAnswer() {
    const c = activeCase();
    openModal(
      `任务 ${pad(c.index)} · ${c.model || state.data.run.model}`,
      "完整回答",
      `<div class="response-meta"><span>${escapeHTML(c.model)}</span><span>${c.stats.steps} 轮</span><span>${formatDuration(c.durationSeconds)}</span><span>${caseState(c).label}</span></div>${renderMarkdown(c.finalAnswer)}`
    );
  }

  function openGroundTruth() {
    const c = activeCase();
    if (!hasGroundTruth(c)) return;
    const status = caseState(c);
    const judge = c.judge && !["true", "false"].includes(String(c.judge)) ? String(c.judge) : "";
    const level = c.groundTruthLevel ? `Level ${c.groundTruthLevel}` : "";
    const benchmark = c.fieldZh || c.field || state.data.run.benchmark || "基准";
    const standardAnswer = String(c.groundTruth).trim();
    const modelAnswer = String(c.answer || "").trim() || "尚未产生答案";
    openModal(
      `任务 ${pad(c.index)} · 标准答案`,
      "标准答案对比",
      `<div class="gt-compare">
        <div class="gt-question">
          <span class="gt-caption">题目</span>
          <p>${escapeHTML(c.question)}</p>
        </div>
        <div class="gt-pair">
          <section class="gt-card is-standard">
            <div class="gt-caption"><span>标准答案</span><small>${escapeHTML(benchmark)}</small></div>
            <pre class="gt-value">${escapeHTML(standardAnswer)}</pre>
          </section>
          <section class="gt-card">
            <div class="gt-caption"><span>模型答案</span><small>模型最终输出</small></div>
            <pre class="gt-value">${escapeHTML(modelAnswer)}</pre>
          </section>
        </div>
        <div class="gt-verdict">
          <span class="gt-state is-${status.key}"><i></i>${status.label}</span>
          <span class="gt-judge">${escapeHTML(judge || "未记录评分方式")}</span>
        </div>
        <p class="info-note">标准答案来自 ${escapeHTML(benchmark)} 参考标注${level ? `（${escapeHTML(level)}）` : ""}。这里用于人工核对；答案的字面差异不一定等同于语义错误，最终以 judge 规则为准。</p>
      </div>`
    );
  }

  function openInfo() {
    if (!state.data) return;
    const { run, cases } = state.data;
    const exposed = cases.filter((item) => ["warn", "alert"].includes(item.risk.level)).length;
    const unaudited = cases.filter((item) => item.risk.level === "unknown").length;
    const confirmed = cases.filter((item) => item.risk.level === "alert").length;
    const datasetRow = state.datasetMeta
      ? `<div class="info-row"><span>数据集文件夹</span><b>${escapeHTML(state.datasetMeta.folder || `datasets/${state.datasetMeta.id}`)}</b></div>`
      : "";
    openModal(
      "本次运行",
      "数据与完整性说明",
      `<div class="info-grid">
        <div class="info-row"><span>模型</span><b>${escapeHTML(run.model)}</b></div>
        <div class="info-row"><span>基准</span><b>${escapeHTML(run.benchmark)}</b></div>
        <div class="info-row"><span>运行日期</span><b>${escapeHTML(run.dateShort || "2026.10.27")}</b></div>
        <div class="info-row"><span>任务 / 轮次</span><b>${run.totalCases} / ${run.rounds}</b></div>
        <div class="info-row"><span>工具调用</span><b>${run.toolCalls}</b></div>
        <div class="info-row"><span>评审通过</span><b>${run.judgePassed} / ${run.judgeScored ?? run.totalCases}</b></div>
        <div class="info-row"><span>网页读取</span><b>${run.pagesRead}</b></div>
        <div class="info-row"><span>检索请求</span><b>${run.searchCalls}</b></div>
        ${datasetRow}
      </div>
      <p class="info-note"><b>读取方式</b> · ${state.datasetId?.startsWith("seven-bench-10pct-20261028-r1-") ? "轨迹由模型请求快照和已保存结果重建；部分进行中步骤可能尚未写入。没有可靠的逐步耗时，页面显示为未记录。早期部分搜索和 Python 调用曾受工具故障影响。" : `页面由 ${escapeHTML(run.model)} 的原生事件日志重建，展示的是实际发生的模型调用、搜索、读取、计算与结论。`}<br><br><b>评审边界</b> · 每个任务仅执行一次 rollout。评审通过仅代表 judge 判定，不等同于基准准确率或独立可复现结论。<br><br><b>来源暴露审计</b> · 本批 ${exposed} 条轨迹被标记为存在基准来源线索，其中 ${confirmed} 条确认出现答案暴露；另有 ${unaudited} 条尚未审计。这些标记保留在任务概览与轨迹中。${(siteLocale === "zh" && !state.datasetId) ? "<br><br><b>中文版本</b> · 问题、推理、网页摘要与完整回答经机器翻译；检索式、URL、工具代码/输出和答案字面量保留原文，推理文本中的代码片段可能随翻译轻微改写。" : ""}</p>`
    );
  }

  function showToast(message) {
    dom.toastText.textContent = message;
    dom.toast.classList.add("is-visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => dom.toast.classList.remove("is-visible"), 1800);
  }

  async function copyText(text, message) {
    try {
      await navigator.clipboard.writeText(text);
      showToast(message);
    } catch {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      try {
        document.execCommand("copy");
        showToast(message);
      } catch {
        showToast("当前浏览器无法复制");
      }
      helper.remove();
    }
  }

  function copyCurrentLink() {
    const url = new URL(window.location.href);
    url.hash = nowHash();
    copyText(url.toString(), "链接已复制");
  }

  function copyAnswer() {
    copyText(activeCase().answer, "结论已复制");
  }

  function navigateToStep(stepNumber, role) {
    if (state.tab !== "trajectory") setTab("trajectory", { hash: false, scroll: false });
    if (state.query) {
      state.query = "";
      dom.traceSearch.value = "";
      updateSearchMeta();
    }
    state.groupCollapsed = false;
    dom.groupToggle.setAttribute("aria-expanded", "true");
    $(".log-shell").classList.remove("is-collapsed");
    let row = $(`.log-row[data-step="${stepNumber}"][data-role="${role}"]`, dom.logBody);
    if (!row) row = $(`.log-row[data-step="${stepNumber}"]`, dom.logBody);
    if (!row) return;
    row.open = true;
    hydrateRow(row);
    updateExpandAllLabel();
    const scrollHost = $("#mainScroll");
    const rowTop = row.getBoundingClientRect().top - scrollHost.getBoundingClientRect().top + scrollHost.scrollTop;
    scrollHost.scrollTo({ top: Math.max(0, rowTop - 150), behavior: "smooth" });
    row.classList.add("is-targeted");
    window.setTimeout(() => row.classList.remove("is-targeted"), 1400);
  }

  function openSidebar() {
    if (!isMobile()) return;
    dom.app.classList.add("sidebar-open");
    dom.sidebarBackdrop.hidden = false;
    dom.sidebarToggle.setAttribute("aria-expanded", "true");
  }

  function closeSidebar() {
    dom.app.classList.remove("sidebar-open");
    dom.sidebarBackdrop.hidden = true;
    dom.sidebarToggle.setAttribute("aria-expanded", "false");
    closeWorkspaceMenu();
  }

  function toggleSidebar() {
    if (isMobile()) {
      if (dom.app.classList.contains("sidebar-open")) closeSidebar();
      else openSidebar();
    } else {
      const collapsed = dom.app.classList.toggle("is-sidebar-collapsed");
      dom.sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    }
  }

  function download() {
    const link = document.createElement("a");
    link.href = `${runURL(state.runId)}/export`;
    link.download = `${state.datasetId || "quest"}-traces.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    showToast("轨迹数据已下载");
  }

  /* ---------- events ---------- */

  function bindEvents() {
    dom.sidebarToggle.addEventListener("click", toggleSidebar);
    dom.sidebarClose.addEventListener("click", closeSidebar);
    dom.sidebarBackdrop.addEventListener("click", closeSidebar);

    dom.workspaceTrigger.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleWorkspaceMenu();
    });

    dom.workspaceMenu.addEventListener("click", (event) => {
      const create = event.target.closest("[data-create-folder]");
      if (create) {
        event.preventDefault();
        event.stopPropagation();
        beginCreateFolder();
        return;
      }
      const toggle = event.target.closest("[data-workspace-toggle]");
      if (toggle) {
        event.preventDefault();
        event.stopPropagation();
        closeWorkspaceActionMenu();
        toggleWorkspaceFolder(toggle.dataset.workspaceToggle);
        return;
      }
      const more = event.target.closest("[data-workspace-menu]");
      if (more) {
        event.preventDefault();
        event.stopPropagation();
        openWorkspaceActionMenu(more.dataset.workspaceMenu, more.dataset.workspaceId, more);
        return;
      }
      const datasetOption = event.target.closest("[data-dataset-option]");
      if (datasetOption) {
        if (datasetOption.dataset.datasetOption === state.datasetId) {
          event.preventDefault();
          closeWorkspaceMenu();
        }
        return;
      }
      const option = event.target.closest("[data-site-option]");
      if (!option) return;
      if (!state.datasetId && option.dataset.siteOption === siteLocale) {
        event.preventDefault();
        closeWorkspaceMenu();
      }
    });

    dom.workspaceActionMenu.addEventListener("click", (event) => {
      const button = event.target.closest("[data-ws-action]");
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const kind = dom.workspaceActionMenu.dataset.workspaceKind;
      const id = dom.workspaceActionMenu.dataset.workspaceId;
      if (!kind || !id) return;
      const action = button.dataset.wsAction;
      if (action === "open") {
        closeWorkspaceMenu();
        window.location.href = `?dataset=${encodeURIComponent(id)}`;
        return;
      }
      closeWorkspaceActionMenu();
      if (action === "rename") startInlineRename(kind, id);
      else if (action === "toggle") toggleWorkspaceFolder(id);
    });

    dom.datasetOptions.addEventListener("contextmenu", (event) => {
      const row = event.target.closest("[data-workspace-item]");
      const group = event.target.closest("[data-workspace-folder]");
      if (!row && !group) return;
      event.preventDefault();
      if (row) {
        const trigger = row.querySelector(".ws-more") || row;
        openWorkspaceActionMenu("dataset", row.dataset.workspaceItem, trigger, { x: event.clientX, y: event.clientY });
      } else {
        const trigger = group.querySelector(".ws-group-head .ws-more") || group;
        openWorkspaceActionMenu("folder", group.dataset.workspaceFolder, trigger, { x: event.clientX, y: event.clientY });
      }
    });

    dom.datasetOptions.addEventListener("dragstart", (event) => {
      const row = event.target.closest("[data-workspace-drag]");
      if (!row || !event.dataTransfer) return;
      if (event.target.closest("button, input")) {
        event.preventDefault();
        return;
      }
      event.dataTransfer.setData("text/plain", row.dataset.workspaceDrag);
      event.dataTransfer.effectAllowed = "move";
      row.classList.add("is-dragging");
      closeWorkspaceActionMenu();
    });
    dom.datasetOptions.addEventListener("dragend", (event) => {
      event.target.closest("[data-workspace-drag]")?.classList.remove("is-dragging");
      $$(".ws-group.is-drop-target", dom.datasetOptions).forEach((element) => element.classList.remove("is-drop-target"));
    });
    dom.datasetOptions.addEventListener("dragover", (event) => {
      const folder = event.target.closest("[data-workspace-folder]");
      if (!folder || !event.dataTransfer) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      $$(".ws-group.is-drop-target", dom.datasetOptions).forEach((element) => {
        if (element !== folder) element.classList.remove("is-drop-target");
      });
      folder.classList.add("is-drop-target");
    });
    dom.datasetOptions.addEventListener("dragleave", (event) => {
      const folder = event.target.closest("[data-workspace-folder]");
      if (!folder || folder.contains(event.relatedTarget)) return;
      folder.classList.remove("is-drop-target");
    });
    dom.datasetOptions.addEventListener("drop", (event) => {
      const folder = event.target.closest("[data-workspace-folder]");
      if (!folder || !event.dataTransfer) return;
      event.preventDefault();
      const id = event.dataTransfer.getData("text/plain");
      if (!state.manifest.some((item) => item.id === id)) return;
      const folderId = folder.dataset.workspaceFolder;
      const layout = readWorkspaceLayout();
      layout.placements[id] = folderId;
      layout.expanded = [...new Set([...(layout.expanded || []), folderId])];
      if (saveWorkspaceLayout(layout)) {
        renderDatasetOptions();
        showToast(`已移动到 ${workspaceFolderTitle(folderId)}`);
      }
    });
    dom.workspaceMenu.addEventListener("scroll", () => closeWorkspaceActionMenu(), { passive: true });

    dom.taskList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-case]");
      if (!button) return;
      selectCase(Number(button.dataset.case));
    });

    if (dom.taskFilter) {
      dom.taskFilter.addEventListener("click", (event) => {
        const button = event.target.closest("[data-task-filter]");
        if (!button) return;
        setTaskFilter(button.dataset.taskFilter);
      });
    }

    $$("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        setTab(button.dataset.tab);
        if (isMobile()) closeSidebar();
      });
    });

    $$("[data-chart-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        state.chartMode = button.dataset.chartMode;
        renderChart();
      });
    });

    dom.timelineVisual.addEventListener("click", (event) => {
      const bar = event.target.closest("[data-chart-step]");
      if (!bar) return;
      navigateToStep(Number(bar.dataset.chartStep), bar.dataset.chartRole);
    });

    dom.traceSearch.addEventListener("input", (event) => {
      applySearch(event.target.value);
    });
    dom.traceSearch.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        dom.traceSearch.value = "";
        applySearch("");
        dom.traceSearch.blur();
      }
    });

    dom.groupToggle.addEventListener("click", () => {
      state.groupCollapsed = !state.groupCollapsed;
      dom.groupToggle.setAttribute("aria-expanded", String(!state.groupCollapsed));
      $(".log-shell").classList.toggle("is-collapsed", state.groupCollapsed);
    });

    dom.expandAll.addEventListener("click", async () => {
      const rows = $$(".log-row", dom.logBody);
      const allOpen = rows.every((row) => row.open);
      const current = activeCase();
      for (let start = 0; start < rows.length; start += 8) {
        if (activeCase() !== current) return;
        rows.slice(start, start + 8).forEach(row => {
          row.open = !allOpen;
          if (row.open) hydrateRow(row);
        });
        await new Promise(resolve => requestAnimationFrame(resolve));
      }
      dom.expandAll.textContent = allOpen ? "全部展开" : "全部收起";
    });

    dom.viewFullAnswer.addEventListener("click", openFullAnswer);
    if (dom.viewGroundTruth) dom.viewGroundTruth.addEventListener("click", openGroundTruth);
    dom.overviewViewFull.addEventListener("click", openFullAnswer);
    if (dom.overviewGroundTruth) dom.overviewGroundTruth.addEventListener("click", openGroundTruth);
    dom.overviewCopyAnswer.addEventListener("click", copyAnswer);
    dom.openBrief.addEventListener("click", openBrief);
    dom.openBriefTop.addEventListener("click", () => {
      if (isMobile()) closeSidebar();
      openBrief();
    });

    dom.copyLinkTop.addEventListener("click", copyCurrentLink);
    dom.dockCopy.addEventListener("click", copyCurrentLink);
    dom.openInfoSide.addEventListener("click", () => {
      if (isMobile()) closeSidebar();
      openInfo();
    });
    dom.openInfoTop.addEventListener("click", openInfo);
    dom.downloadData.addEventListener("click", download);

    dom.dockTabButton.addEventListener("click", () => {
      const next = dom.dockTabButton.dataset.action;
      setTab(next, { scroll: true });
    });

    dom.prevTask.addEventListener("click", () => selectCase(state.index - 1, { push: true }));
    dom.nextTask.addEventListener("click", () => selectCase(state.index + 1, { push: true }));

    dom.brandLink.addEventListener("click", (event) => {
      event.preventDefault();
      setTab("trajectory");
      $("#mainScroll").scrollTop = 0;
    });

    dom.modalClose.addEventListener("click", closeModal);
    dom.modal.addEventListener("click", (event) => {
      if (event.target === dom.modal) closeModal();
    });

    document.addEventListener("click", (event) => {
      if (event.target.closest("#workspaceActionMenu")) return;
      if (event.target.closest("[data-workspace-menu]")) return;
      closeWorkspaceActionMenu();
      if (!event.target.closest("#workspaceSwitcher")) closeWorkspaceMenu();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && dom.workspaceActionMenu && !dom.workspaceActionMenu.hidden) {
        event.preventDefault();
        closeWorkspaceActionMenu(true);
        return;
      }
      if (event.key === "Escape" && !dom.workspaceMenu.hidden) {
        closeWorkspaceMenu();
        dom.workspaceTrigger.focus();
        return;
      }
      const modifier = event.metaKey || event.ctrlKey;
      if (modifier && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openBrief();
        return;
      }
      const target = event.target;
      const editable = target instanceof HTMLElement && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (event.key === "/" && !editable && !dom.modal.open) {
        event.preventDefault();
        dom.traceSearch.focus();
      }
    });

    window.addEventListener('popstate', () => {
      const location = parseHash();
      state.tab = location.tab;
      selectCase(location.index, { push: false });
    });

    window.addEventListener("resize", () => {
      closeWorkspaceActionMenu();
      if (!dom.workspaceMenu.hidden) fitWorkspaceMenu();
      if (!isMobile()) closeSidebar();
    });
  }

  let pollInFlight = false;
  async function pollWorkspace() {
    if (pollInFlight || !state.data || document.hidden) return;
    pollInFlight = true;
    const generation = navigationGeneration;
    try {
      const selectedId = activeCase().id;
      const stats = await getJSON(`${runURL(state.runId)}/traces/${encodeURIComponent(selectedId)}/session-stats`);
      if (generation !== navigationGeneration) return;
      if (stats.data && state.activeTrace?.id === selectedId) {
        state.activeTrace.sessionStats = stats.data.sessionStats;
        renderSessionStats(state.activeTrace);
      }
      await refreshWorkspaceStats();
      const manifest = await loadWorkspaceManifest();
      if (JSON.stringify(manifest) !== JSON.stringify(state.manifest)) {
        state.manifest = manifest;
        setupWorkspaceSwitcher();
      }
      const check = await getJSON(runURL(state.runId), undefined, `"${state.revision}"`);
      if (!check.data) return;
      const next = await loadRun(state.runId);
      const currentId = activeCase().id;
      let nextIndex = next.cases.findIndex(item => item.id === currentId);
      if (nextIndex < 0) nextIndex = 0;
      const summary = next.cases[nextIndex];
      if (!summary) return;
      const previous = state.data.cases[state.index];
      const changed = summary.id !== currentId || summary.revision !== previous.revision;
      const detail = changed ? await fetchCase(summary) : state.activeTrace;
      if (generation !== navigationGeneration) return;
      const openRows = new Set($$('.log-row[open]', dom.logBody).map(row => `${row.dataset.step}:${row.dataset.role}`));
      const scrollTop = $('#mainScroll').scrollTop;
      const listScrollTop = dom.taskList.scrollTop;
      state.data = { run: next.info.run, cases: next.cases };
      state.revision = next.info.revision;
      state.datasetMeta = state.datasetId ? next.info.metadata : null;
      state.index = nextIndex;
      state.activeTrace = detail;
      setupWorkspaceSwitcher();
      renderSidebarSummary();
      renderRunChrome();
      renderTaskList();
      if (changed) {
        renderAllContent();
        $$('.log-row', dom.logBody).forEach(row => {
          if (openRows.has(`${row.dataset.step}:${row.dataset.role}`)) { row.open = true; hydrateRow(row); }
        });
        if (state.query) traceSearch.search(state.query);
      } else {
        // Run lifecycle changes update badges without replacing event DOM.
        renderContext();
        renderOverview();
        dom.logGroupState.innerHTML = `<i></i>${statusLabel(activeCase())}`;
      }
      $('#mainScroll').scrollTop = scrollTop;
      dom.taskList.scrollTop = listScrollTop;
    } catch (error) {
      console.warn('Workspace refresh failed; retaining the previous view', error);
    } finally { pollInFlight = false; }
  }

  async function init() {
    bindEvents();
    try {
      state.manifest = await loadWorkspaceManifest();
      const requested = new URLSearchParams(window.location.search).get('dataset');
      if (requested && !state.manifest.some(item => item.id === requested)) throw new Error('工作区不存在');
      state.datasetId = requested;
      state.runId = requested || `default-${siteLocale}`;
      const next = await loadRun(state.runId);
      state.data = { run: next.info.run, cases: next.cases };
      state.revision = next.info.revision;
      state.datasetMeta = requested ? next.info.metadata : null;
      const location = parseHash();
      state.index = location.index;
      state.tab = location.tab;
      state.activeTrace = await fetchCase(state.data.cases[state.index]);
      setupWorkspaceSwitcher();
      renderSidebarSummary();
      renderRunChrome();
      renderTaskList();
      renderAllContent();
      refreshWorkspaceStats();
      if (window.location.hash !== nowHash()) history.replaceState(null, '', nowHash());
      dom.sidebarToggle.setAttribute('aria-expanded', String(!isMobile()));
      window.setInterval(pollWorkspace, 5000);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) pollWorkspace(); });
    } catch (error) {
      console.error(error);
      dom.logBody.innerHTML = '<div class="log-empty"><p>轨迹数据加载失败</p><span>请检查服务连接和数据导入状态，刷新页面重试。</span></div>';
    }
  }

  init();
