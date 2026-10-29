(() => {
  "use strict";

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
    dataUrl: "data/traces.json",
    taskFilter: "all",
  };

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

  function escapeHTML(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function escapeAttr(value) {
    return escapeHTML(value).replace(/`/g, "&#096;");
  }

  function safeURL(value) {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "#";
    } catch {
      return "#";
    }
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function number(value) {
    return new Intl.NumberFormat("en-US").format(value || 0);
  }

  function pluralCount(count, unit) {
    return `${number(count)} ${unit}`;
  }

  function formatSeconds(value, precise = false) {
    const seconds = Number(value || 0);
    if (seconds < 0.1) return "<0.1s";
    if (seconds < 10) return `${seconds.toFixed(1).replace(/\.0$/, "")}s`;
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) {
      const mins = Math.floor(seconds / 60);
      const secs = Math.round(seconds % 60);
      return precise ? `${mins}m ${pad(secs)}s` : `${mins}m ${pad(secs)}s`;
    }
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  }

  function formatDuration(value) {
    return formatSeconds(value, true);
  }

  function formatAxis(value) {
    const seconds = Math.max(0, Math.round(Number(value || 0)));
    if (seconds < 3600) {
      return `${Math.floor(seconds / 60)}:${pad(seconds % 60)}`;
    }
    return `${Math.floor(seconds / 3600)}:${pad(Math.floor((seconds % 3600) / 60))}:${pad(seconds % 60)}`;
  }

  function clampText(value, limit = 180) {
    const normalized = String(value || "").replace(/\s+/g, " ").trim();
    if (normalized.length <= limit) return normalized;
    return `${normalized.slice(0, limit - 1).trimEnd()}…`;
  }

  function nowHash(index = state.index, tab = state.tab) {
    return `#${state.data?.cases[index]?.id || `trace-${pad(index + 1)}`}${tab === "overview" ? "/overview" : ""}`;
  }

  function parseHash() {
    const raw = window.location.hash.replace(/^#\/?/, "");
    const [tracePart, viewPart] = raw.split("/");
    const match = /^trace-(\d{1,2})$/.exec(tracePart || "");
    const found = match && state.data ? state.data.cases.findIndex((item) => item.id === `trace-${pad(Number(match[1]))}`) : -1;
    const index = found >= 0 ? found : 0;
    return {
      index: Number.isFinite(index) ? index : 0,
      tab: viewPart === "overview" ? "overview" : "trajectory",
    };
  }

  function activeCase() {
    return state.data.cases[state.index];
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

  function caseState(caseData) {
    if (caseData.inProgress && (state.data.run?.stopped || state.datasetMeta?.lifecycleOverride === "stopped")) return { key: "stopped", label: "已终止" };
    if (caseData.inProgress) return { key: "running", label: "进行中" };
    if (caseData.correct === true) return { key: "pass", label: "通过" };
    if (caseData.correct === false) return { key: "fail", label: "未通过" };
    return { key: "error", label: "未评分或错误" };
  }

  function caseStateDetail(caseData) {
    const status = caseState(caseData);
    if (status.key === "error") {
      return "未评分或评分不可用";
    }
    return status.label;
  }

  function hasGroundTruth(caseData) {
    return Boolean(caseData && typeof caseData.groundTruth === "string" && caseData.groundTruth.trim());
  }

  function runLifecycleState() {
    const run = state.data.run;
    if (state.data.run?.stopped || state.datasetMeta?.lifecycleOverride === "stopped") return { key: "stopped", short: "已终止", label: "评估已终止 · 历史轨迹保留" };
    if (run.paused) return { key: "error", short: "已暂停", label: "评估暂停 · 等待服务恢复" };
    if (run.inProgress) return { key: "running", short: "进行中", label: "评估进行中" };
    return { key: "pass", short: "已完成", label: "运行完成" };
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
    element.classList.remove("is-fail", "is-pass", "is-running", "is-stopped", "is-error");
    element.classList.add(`is-${status.key}`);
    element.innerHTML = `<i></i>${status.label}`;
    element.title = caseStateDetail(caseData);
  }

  function statusLabel(caseData) {
    return caseState(caseData).label;
  }

  function riskInfo(caseData) {
    const map = {
      unknown: { short: "来源暴露未审计", long: "此轨迹尚未完成来源暴露审计，不能视为无污染结果。" },
      clean: {
        short: "未发现来源暴露",
        long: "本次检索内容中未发现基准来源暴露。评审结果按原始记录保留，但不构成准确率声明。",
      },
      warn: {
        short: "存在来源暴露迹象",
        long: "检索内容中包含基准来源线索。评审结果已如实保留，但不宣称该结论来自完全独立的推导。",
      },
      alert: {
        short: "已确认答案暴露",
        long: "运行过程中出现了基准答案相关材料。轨迹按原生行为保留，不应视为一次干净的独立求解。",
      },
    };
    return map[caseData.risk.level] || map.clean;
  }

  /* ---------- workspace folders ---------- */

  const siteLocale = /(?:^|\/)trace-viewer-zh(?:\/|$)/.test(window.location.pathname) ? "zh" : "en";

  function setupWorkspaceSwitcher() {
    const isZh = siteLocale === "zh";
    const meta = state.datasetMeta;
    const run = state.data?.run || {};
    let workspaceName;
    let workspaceSub;
    let foot;
    let benchmarkLabel;

    if (meta) {
      workspaceName = meta.label || meta.id || run.name || "数据集评估";
      workspaceSub = meta.description || `${run.model || "QUEST-4B"} · ${run.benchmark || "Evaluation"}`;
      foot = meta.folder || meta.data || `datasets/${meta.id}`;
      benchmarkLabel = meta.benchmark || run.benchmark || "本次评估";
    } else {
      workspaceName = isZh ? "16_Search-Agent-zh" : "16_Search-Agent";
      workspaceSub = isZh ? "QUEST-4B · GAIA 前 10 题 · 中文译文" : "QUEST-4B · GAIA 前 10 题";
      foot = isZh ? "trace-viewer-zh" : "trace-viewer";
      benchmarkLabel = "GAIA 前 10 题";
    }

    if (dom.workspaceName) dom.workspaceName.textContent = workspaceName;
    if (dom.workspaceSub) dom.workspaceSub.textContent = workspaceSub;
    if (dom.workspaceFootSite) dom.workspaceFootSite.textContent = foot;
    if (dom.breadcrumbWorkspace) dom.breadcrumbWorkspace.textContent = workspaceName;
    if (dom.breadcrumbBenchmark) dom.breadcrumbBenchmark.textContent = benchmarkLabel;
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

    const hrefs = isZh
      ? { en: "../", zh: "./" }
      : { en: "./", zh: "trace-viewer-zh/" };
    $$("[data-site-option]", dom.workspaceMenu).forEach((option) => {
      const optionSite = option.dataset.siteOption;
      option.href = hrefs[optionSite] || "#";
      const current = !state.datasetId && optionSite === siteLocale;
      option.classList.toggle("is-current", current);
      if (current) option.setAttribute("aria-current", "page");
      else option.removeAttribute("aria-current");
    });
    renderDatasetOptions();
    updateWorkspaceLinks();
  }

  function renderDatasetOptions() {
    if (!dom.datasetOptions || !dom.datasetMenuDivider) return;
    const datasets = (state.manifest || []).filter((item) => item && item.id && item.visible !== false);
    dom.datasetMenuDivider.hidden = datasets.length === 0;
    if (!datasets.length) {
      dom.datasetOptions.innerHTML = "";
      return;
    }
    dom.datasetOptions.innerHTML = datasets
      .map((item) => {
        const active = state.datasetId === item.id;
        const href = siteLocale === "zh"
          ? `?dataset=${encodeURIComponent(item.id)}`
          : `?dataset=${encodeURIComponent(item.id)}`;
        const description = item.description || item.folder || `datasets/${item.id}`;
        return `<a class="workspace-option dataset-option${active ? " is-current" : ""}" href="${escapeAttr(href)}" data-dataset-option="${escapeAttr(item.id)}" role="menuitem"${active ? ' aria-current="page"' : ""}>
          <span class="workspace-option-icon"><svg class="icon"><use href="#i-activity"/></svg></span>
          <span class="workspace-option-copy"><strong>${escapeHTML(item.label || item.id)}</strong><small>${escapeHTML(description)}</small></span>
          <span class="workspace-option-check" aria-hidden="true"><svg class="icon"><use href="#i-check"/></svg></span>
        </a>`;
      })
      .join("");
  }

  function updateWorkspaceLinks() {
    if (!dom.workspaceMenu) return;
    const hash = nowHash();
    const query = window.location.search;
    const hrefs = siteLocale === "zh"
      ? { en: `../${query}${hash}`, zh: `./${query}${hash}` }
      : { en: `./${query}${hash}`, zh: `trace-viewer-zh/${query}${hash}` };
    $$("[data-site-option]", dom.workspaceMenu).forEach((option) => {
      const optionSite = option.dataset.siteOption;
      option.href = hrefs[optionSite] || "#";
    });
  }

  function manifestPath() {
    return siteLocale === "zh" ? "../datasets/index.json" : "datasets/index.json";
  }

  async function loadWorkspaceManifest() {
    try {
      const response = await fetch(manifestPath(), { cache: "no-store" });
      if (!response.ok) return [];
      const payload = await response.json();
      return Array.isArray(payload.datasets) ? payload.datasets : [];
    } catch {
      return [];
    }
  }

  function openWorkspaceMenu() {
    if (!dom.workspaceMenu || !dom.workspaceTrigger) return;
    closeWorkspaceMenu();
    dom.workspaceMenu.hidden = false;
    dom.workspaceTrigger.setAttribute("aria-expanded", "true");
  }

  function closeWorkspaceMenu() {
    if (!dom.workspaceMenu || !dom.workspaceTrigger) return;
    dom.workspaceMenu.hidden = true;
    dom.workspaceTrigger.setAttribute("aria-expanded", "false");
  }

  function toggleWorkspaceMenu() {
    if (dom.workspaceMenu.hidden) openWorkspaceMenu();
    else closeWorkspaceMenu();
  }

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

  function setTab(tab, options = {}) {
    if (!state.data) return;
    if (tab !== "trajectory" && tab !== "overview") return;
    if (state.tab === tab && !options.force) {
      return;
    }
    state.tab = tab;
    renderTabs();
    renderTabMeta();
    $("#mainScroll").scrollTop = 0;
    if (options.hash !== false) {
      history.replaceState(null, "", nowHash(state.index, state.tab));
    }
  }

  function selectCase(index, options = {}) {
    if (!state.data) return;
    const clamped = Math.max(0, Math.min(state.data.cases.length - 1, index));
    state.index = clamped;
    state.query = "";
    state.groupCollapsed = false;
    if (dom.traceSearch) dom.traceSearch.value = "";
    renderTaskList();
    renderAllContent();
    if (options.push !== false) history.pushState(null, "", nowHash(state.index, state.tab));
    $("#mainScroll").scrollTop = 0;
    if (isMobile()) closeSidebar();
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

  function makeBar(step, start, duration, total, type, role) {
    const safeTotal = Math.max(1, total);
    const left = Math.min(99.6, Math.max(0, (Number(start || 0) / safeTotal) * 100));
    const width = Math.min(100 - left, Math.max(0.45, (Number(duration || 0) / safeTotal) * 100));
    const title = `第 ${step.n} 轮 · ${type === "model" ? "模型" : step.label} · ${formatSeconds(duration)} · ${formatAxis(start)}`;
    return `<button type="button" class="chart-bar ${type}" data-chart-step="${step.n}" data-chart-role="${role}" style="left:${left.toFixed(3)}%;width:${width.toFixed(3)}%" title="${escapeAttr(title)}" aria-label="${escapeAttr(title)}"></button>`;
  }

  function axisHTML(total) {
    const marks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => formatAxis(total * ratio));
    return `<div class="chart-axis"><span class="axis-label">时间轴</span><div class="axis-marks">${marks.map((mark) => `<span>${mark}</span>`).join("")}</div></div>`;
  }

  function laneHTML(label, className, bars) {
    return `<div class="chart-lane"><span class="chart-lane-label">${escapeHTML(label)}</span><div class="chart-track">${bars.join("")}</div></div>`;
  }

  function renderDurationChart(c) {
    const total = c.durationSeconds;
    const modelBars = c.steps.map((step) => makeBar(step, step.modelStart, step.model_seconds, total, "model", "assistant"));
    const searchBars = c.steps
      .filter((step) => step.kind === "search")
      .map((step) => makeBar(step, step.toolStart, step.tool_seconds, total, "search", "tool"));
    const readBars = c.steps
      .filter((step) => step.kind === "read")
      .map((step) => makeBar(step, step.toolStart, step.tool_seconds, total, "read", "tool"));
    const computeBars = c.steps
      .filter((step) => step.kind === "compute")
      .map((step) => makeBar(step, step.toolStart, step.tool_seconds, total, "compute", "tool"));
    const readLane = laneHTML("读取 / 计算", "read", [...readBars, ...computeBars]);
    dom.chartTitle.textContent = "执行时间线";
    dom.chartSub.textContent = `${formatDuration(c.durationSeconds)} · 真实调用跨度`;
    dom.chartLegend.innerHTML = [
      ["model", "模型"],
      ["search", "搜索"],
      ["read", "读取"],
      c.stats.computeCalls ? ["compute", "计算"] : null,
    ]
      .filter(Boolean)
      .map(([type, label]) => `<span><i class="legend-dot ${type}"></i>${label}</span>`)
      .join("");
    dom.timelineVisual.innerHTML = `${axisHTML(total)}<div class="chart-lanes">${laneHTML("模型", "model", modelBars)}${laneHTML("搜索", "search", searchBars)}${readLane}</div><div class="chart-footnote"><span>记录窗口 ${formatDuration(total)}</span><span>点击色块定位事件</span></div>`;
  }

  function renderRoundsChart(c) {
    const cells = c.steps
      .map((step) => {
        const kind = step.kind === "answer" ? "answer" : step.kind;
        const label = `第 ${step.n} 轮 · ${step.label} · ${formatSeconds(step.model_seconds + step.tool_seconds)}`;
        return `<button type="button" class="round-cell ${kind}" data-chart-step="${step.n}" data-chart-role="assistant" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"></button>`;
      })
      .join("");
    dom.chartTitle.textContent = "轮次分布";
    dom.chartSub.textContent = `${c.stats.steps} 轮 · ${number(c.stats.searchCalls + c.stats.readCalls + c.stats.computeCalls)} 次工具调用`;
    dom.chartLegend.innerHTML = [
      ["search", "搜索"],
      ["read", "读取"],
      ["compute", "计算"],
      ["answer", "综合"],
    ]
      .filter(([type]) => type !== "compute" || c.stats.computeCalls)
      .map(([type, label]) => `<span><i class="legend-dot ${type}"></i>${label}</span>`)
      .join("");
    dom.timelineVisual.innerHTML = `<div class="round-chart">
      <div class="round-head"><span>第 1 轮 → 第 ${c.stats.steps} 轮</span><span>点击轮次定位</span></div>
      <div class="round-strip">${cells}</div>
      <div class="round-labels"><span>01</span><span>${pad(c.stats.steps)}</span></div>
      <div class="call-summary"><span>搜索 <b>${c.stats.searchCalls}</b></span><span>读取 <b>${c.stats.readCalls}</b></span><span>计算 <b>${c.stats.computeCalls}</b></span></div>
    </div>`;
  }

  function renderCallsChart(c) {
    const total = c.durationSeconds;
    const searchBars = c.steps
      .filter((step) => step.kind === "search")
      .map((step) => makeBar(step, step.toolStart, step.tool_seconds, total, "search", "tool"));
    const readBars = c.steps
      .filter((step) => step.kind === "read")
      .map((step) => makeBar(step, step.toolStart, step.tool_seconds, total, "read", "tool"));
    const computeBars = c.steps
      .filter((step) => step.kind === "compute")
      .map((step) => makeBar(step, step.toolStart, step.tool_seconds, total, "compute", "tool"));
    dom.chartTitle.textContent = "工具调用";
    dom.chartSub.textContent = `${number(c.stats.searchCalls + c.stats.readCalls + c.stats.computeCalls)} 次调用 · ${formatDuration(c.durationSeconds)}`;
    dom.chartLegend.innerHTML = [
      ["search", `搜索 ${c.stats.searchCalls}`],
      ["read", `读取 ${c.stats.readCalls}`],
      ["compute", `计算 ${c.stats.computeCalls}`],
    ]
      .map(([type, label]) => `<span><i class="legend-dot ${type}"></i>${label}</span>`)
      .join("");
    dom.timelineVisual.innerHTML = `${axisHTML(total)}<div class="chart-lanes">
      ${laneHTML("搜索", "search", searchBars)}
      ${laneHTML("读取", "read", readBars)}
      ${laneHTML("计算", "compute", computeBars)}
    </div><div class="chart-footnote"><span>调用跨度 ${formatDuration(total)}</span><span>点击色块定位工具事件</span></div>`;
  }

  function renderChart() {
    if (!state.data) return;
    const c = activeCase();
    $$(".metric-button").forEach((button) => {
      const active = button.dataset.chartMode === state.chartMode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (state.chartMode === "rounds") renderRoundsChart(c);
    else if (state.chartMode === "calls") renderCallsChart(c);
    else renderDurationChart(c);
  }

  /* ---------- log rendering ---------- */

  function buildSearchText(step) {
    const parts = [step.thought || "", step.label || ""];
    if (step.tool) {
      parts.push(step.tool.name || "");
      (step.tool.queries || []).forEach((query) => {
        parts.push(query.query || "");
        (query.results || []).forEach((result) => parts.push(result.title, result.domain, result.snippet));
      });
      (step.tool.pages || []).forEach((page) => parts.push(page.title, page.domain, page.summary, page.rationale, page.evidence));
      if (step.tool.code) parts.push(step.tool.code);
      if (step.tool.stdout) parts.push(step.tool.stdout);
    }
    return parts.join(" ").replace(/\s+/g, " ").toLowerCase();
  }

  function buildAssistantRow(step) {
    const preview = clampText(step.thought || "模型未输出可见推理", 260);
    return `<details class="log-row is-assistant${step.kind === "answer" ? " is-answer" : ""}" data-step="${step.n}" data-role="assistant" data-search="${escapeAttr(buildSearchText(step))}">
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
    return `<details class="log-row is-tool" data-step="${step.n}" data-role="tool" data-search="${escapeAttr(buildSearchText(step))}">
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
    const rows = c.steps.flatMap((step) => {
      const result = [buildAssistantRow(step)];
      if (step.tool) result.push(buildToolRow(step));
      return result;
    });
    dom.logBody.innerHTML = rows.join("");
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
    // Lazy-load details after a row is opened.
    $$(".log-row", dom.logBody).forEach((row) => {
      row.addEventListener("toggle", () => {
        if (row.open) hydrateRow(row);
        updateExpandAllLabel();
      });
    });
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
    const step = activeCase().steps.find((item) => item.n === stepNumber);
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
                    <div class="page-detail-domain">${escapeHTML(page.domain)} · 读取 ${formatSeconds(page.readerSeconds || page.summarySeconds || 0)}</div>
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
      const match = !q || (row.dataset.search || "").includes(q);
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
    updateSearchMeta();
  }

  /* ---------- overview ---------- */

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
    return {running: "评估进行中", pass: "研究完成 · 通过", fail: "研究完成 · 未通过", stopped: "评估已终止", error: "未评分或评分错误"}[status.key] || "状态未知";
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
    renderChart();
    renderLog();
    renderOverview();
    renderDock();
    const groundTruthAvailable = hasGroundTruth(activeCase());
    [dom.overviewGroundTruth, dom.viewGroundTruth].forEach((button) => {
      if (button) button.hidden = !groundTruthAvailable;
    });
    document.title = `${activeCase().topicZh} · ${state.datasetMeta ? state.datasetMeta.label + " · " : ""}Search Agent 轨迹展示页面`;
  }

  /* ---------- modal and utilities ---------- */

  function inlineMarkdown(text) {
    let html = escapeHTML(text);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return html;
  }

  function renderMarkdown(text) {
    const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
    let html = "";
    let paragraph = [];
    let listType = null;
    let listItems = [];
    const flushParagraph = () => {
      if (paragraph.length) {
        html += `<p>${paragraph.map(inlineMarkdown).join("<br>")}</p>`;
        paragraph = [];
      }
    };
    const flushList = () => {
      if (listType && listItems.length) {
        html += `<${listType}>${listItems.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</${listType}>`;
      }
      listType = null;
      listItems = [];
    };
    for (const line of lines) {
      if (/^\s*$/.test(line)) {
        flushParagraph();
        flushList();
        continue;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line.trim());
      if (heading) {
        flushParagraph();
        flushList();
        const level = Math.min(4, heading[1].length + 1);
        html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
        continue;
      }
      if (/^\s*(?:---+|\*\*\*+)\s*$/.test(line)) {
        flushParagraph();
        flushList();
        html += "<hr>";
        continue;
      }
      const unordered = /^\s*[-*+]\s+(.+)$/.exec(line);
      if (unordered) {
        flushParagraph();
        if (listType !== "ul") {
          flushList();
          listType = "ul";
        }
        listItems.push(unordered[1]);
        continue;
      }
      const ordered = /^\s*\d+\.\s+(.+)$/.exec(line);
      if (ordered) {
        flushParagraph();
        if (listType !== "ol") {
          flushList();
          listType = "ol";
        }
        listItems.push(ordered[1]);
        continue;
      }
      if (/^\s*>\s?/.test(line)) {
        flushParagraph();
        flushList();
        html += `<blockquote>${inlineMarkdown(line.replace(/^\s*>\s?/, ""))}</blockquote>`;
        continue;
      }
      flushList();
      paragraph.push(line);
    }
    flushParagraph();
    flushList();
    return html;
  }

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
            <div class="gt-caption"><span>标准答案</span><small>GAIA official</small></div>
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
        <p class="info-note">标准答案来自 GAIA 官方标注${level ? `（${escapeHTML(level)}）` : ""}。这里用于人工核对；答案的字面差异不一定等同于语义错误，最终以 judge 规则为准。</p>
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
      <p class="info-note"><b>读取方式</b> · 页面由 ${escapeHTML(run.model)} 的原生事件日志重建，展示的是实际发生的模型调用、搜索、读取、计算与结论。<br><br><b>评审边界</b> · 每个任务仅执行一次 rollout。评审通过仅代表 judge 判定，不等同于基准准确率或独立可复现结论。<br><br><b>来源暴露审计</b> · 本批 ${exposed} 条轨迹被标记为存在基准来源线索，其中 ${confirmed} 条确认出现答案暴露；另有 ${unaudited} 条尚未审计。这些标记保留在任务概览与轨迹中。${(siteLocale === "zh" && !state.datasetId) ? "<br><br><b>中文版本</b> · 问题、推理、网页摘要与完整回答经机器翻译；检索式、URL、工具代码/输出和答案字面量保留原文，推理文本中的代码片段可能随翻译轻微改写。" : ""}</p>`
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
    link.href = state.dataUrl;
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

    dom.expandAll.addEventListener("click", () => {
      const rows = $$(".log-row", dom.logBody);
      const allOpen = rows.every((row) => row.open);
      rows.forEach((row) => {
        row.open = !allOpen;
        if (row.open) hydrateRow(row);
      });
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
      if (!event.target.closest("#workspaceSwitcher")) closeWorkspaceMenu();
    });

    document.addEventListener("keydown", (event) => {
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

    window.addEventListener("popstate", () => {
      const location = parseHash();
      if (location.index >= state.data.cases.length) return;
      state.index = location.index;
      state.tab = location.tab;
      if (isMobile()) closeSidebar();
      renderTaskList();
      renderAllContent();
      $("#mainScroll").scrollTop = 0;
    });

    window.addEventListener("resize", () => {
      if (!isMobile()) closeSidebar();
    });
  }

  // Poll the selected dataset without reloading the page or losing navigation state.
  function dataFingerprint(text) {
    return text.replace(/("generatedAt"\s*:\s*)"[^"]*"/, '$1""');
  }

  function refreshDatasetView(nextData) {
    const caseId = activeCase()?.id;
    const openRows = new Set($$(".log-row[open]", dom.logBody).map((row) => `${row.dataset.step}:${row.dataset.role}`));
    const mainScroll = $("#mainScroll");
    const scrollTop = mainScroll.scrollTop;
    const listScrollTop = dom.taskList.scrollTop;
    state.data = nextData;
    const nextIndex = nextData.cases.findIndex((item) => item.id === caseId);
    state.index = nextIndex < 0 ? Math.min(state.index, nextData.cases.length - 1) : nextIndex;
    setupWorkspaceSwitcher();
    renderSidebarSummary();
    renderRunChrome();
    renderTaskList();
    renderAllContent();
    $$(".log-row", dom.logBody).forEach((row) => {
      if (openRows.has(`${row.dataset.step}:${row.dataset.role}`)) { row.open = true; hydrateRow(row); }
    });
    mainScroll.scrollTop = scrollTop;
    dom.taskList.scrollTop = listScrollTop;
  }

  let pollInFlight = false;
  async function pollWorkspace() {
    if (pollInFlight || !state.data || document.hidden) return;
    pollInFlight = true;
    try {
      // A failed manifest read must not erase the current workspace list.
      const manifestResponse = await fetch(manifestPath(), { cache: "no-store" });
      if (manifestResponse.ok) {
        const manifestPayload = await manifestResponse.json();
        if (Array.isArray(manifestPayload.datasets) && JSON.stringify(manifestPayload.datasets) !== JSON.stringify(state.manifest)) {
          const previousMeta = JSON.stringify(state.datasetMeta);
          state.manifest = manifestPayload.datasets;
          state.datasetMeta = state.manifest.find((item) => item && item.id === state.datasetId) || state.datasetMeta;
          if (JSON.stringify(state.datasetMeta) !== previousMeta) refreshDatasetView(state.data);
          else setupWorkspaceSwitcher();
        }
      }
      const headers = {};
      if (state.dataLastModified) headers["If-Modified-Since"] = state.dataLastModified;
      const response = await fetch(state.dataUrl, { cache: "no-store", headers });
      if (response.status === 304) return;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rawData = await response.text();
      const fingerprint = dataFingerprint(rawData);
      if (fingerprint === state.dataFingerprint) {
        state.dataLastModified = response.headers.get("Last-Modified");
        return;
      }
      const nextData = JSON.parse(rawData);
      if (!Array.isArray(nextData.cases) || !nextData.cases.length) throw new Error("Empty or invalid dataset");
      refreshDatasetView(nextData);
      state.dataFingerprint = fingerprint;
      state.dataLastModified = response.headers.get("Last-Modified");
    } catch (error) {
      console.warn("Workspace refresh failed; retaining the previous view", error);
    } finally {
      pollInFlight = false;
    }
  }

  /* ---------- initialization ---------- */

  async function init() {
    bindEvents();
    try {
      state.manifest = await loadWorkspaceManifest();
      const requestedDataset = new URLSearchParams(window.location.search).get("dataset");
      let datasetMeta = null;
      let dataUrl = "data/traces.json";
      if (requestedDataset) {
        datasetMeta = state.manifest.find((item) => item && item.id === requestedDataset) || null;
        if (datasetMeta) {
          dataUrl = siteLocale === "zh" ? `../${datasetMeta.data || `datasets/${datasetMeta.id}/traces.json`}` : (datasetMeta.data || `datasets/${datasetMeta.id}/traces.json`);
        }
      }
      const response = await fetch(dataUrl, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rawData = await response.text();
      state.data = JSON.parse(rawData);
      state.dataFingerprint = dataFingerprint(rawData);
      state.dataLastModified = response.headers.get("Last-Modified");
      state.datasetMeta = datasetMeta;
      state.datasetId = datasetMeta?.id || null;
      state.dataUrl = dataUrl;
      setupWorkspaceSwitcher();
      const location = parseHash();
      state.index = Math.min(Math.max(0, location.index), state.data.cases.length - 1);
      state.tab = location.tab;
      renderSidebarSummary();
      renderRunChrome();
      renderTaskList();
      renderAllContent();
      if (window.location.hash !== nowHash()) history.replaceState(null, "", nowHash());
      dom.sidebarToggle.setAttribute("aria-expanded", String(!isMobile()));
      window.setInterval(pollWorkspace, 5000);
      document.addEventListener("visibilitychange", () => { if (!document.hidden) pollWorkspace(); });
    } catch (error) {
      console.error(error);
      dom.logBody.innerHTML = `<div class="log-empty"><p>轨迹数据加载失败</p><span>请通过 HTTP 服务访问此页面，并检查 data/traces.json 或 datasets/index.json。</span></div>`;
    }
  }

  init();
})();
