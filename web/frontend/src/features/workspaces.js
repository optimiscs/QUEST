export function createWorkspaces(context) {
  const { state, dom, $, $$, icon, escapeHTML, escapeAttr, nowHash, runLifecycleState, showToast, getJSON, siteLocale } = context;
  function setupWorkspaceSwitcher() {
    const isZh = siteLocale === "zh";
    const meta = state.datasetMeta;
    const run = state.data?.run || {};
    let workspaceName;
    let workspaceSub;
    let foot;
    let benchmarkLabel;

    if (meta) {
      workspaceName = readWorkspaceLayout().names[meta.id] || meta.label || meta.id || run.name || "数据集评估";
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

    const hrefs = { en: "/", zh: "/trace-viewer-zh/" };
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

  const WORKSPACE_LAYOUT_KEY = "quest.trace.workspace-layout.v1";

  function readWorkspaceLayout() {
    try {
      const raw = JSON.parse(window.localStorage.getItem(WORKSPACE_LAYOUT_KEY) || "{}");
      return {
        folders: raw.folders || {},
        placements: raw.placements || {},
        names: raw.names || {},
        expanded: Array.isArray(raw.expanded) ? raw.expanded : [],
      };
    } catch (_) { return { folders: {}, placements: {}, names: {}, expanded: [] }; }
  }

  function saveWorkspaceLayout(layout) {
    try { window.localStorage.setItem(WORKSPACE_LAYOUT_KEY, JSON.stringify(layout)); return true; }
    catch (_) { showToast("无法保存工作区设置，请检查浏览器存储权限"); return false; }
  }

  function defaultWorkspaceFolder(item) {
    return `auto:${item.group || item.benchmark || "其他评估"}`;
  }

  let workspaceActionTrigger = null;

  function workspaceFolderTitle(id, layout = readWorkspaceLayout()) {
    if (layout.folders[id]) return layout.folders[id];
    return id.startsWith("auto:") ? id.slice(5) : "新目录";
  }

  function workspaceDatasetLabel(item, layout = readWorkspaceLayout()) {
    return layout.names[item.id] || item.label || item.id;
  }

  function workspaceStatsFor(id) {
    const raw = state.workspaceStats?.[id];
    if (!raw || typeof raw !== "object") return null;
    const total = Number(raw.total);
    if (!Number.isFinite(total) || total <= 0) return null;
    const pass = Math.max(0, Number(raw.pass) || 0);
    const running = Math.max(0, Number(raw.running) || 0);
    return { total, pass, running, other: Math.max(0, total - pass - running) };
  }

  function workspaceMetricsHTML(stats) {
    return `<span class="ws-item-metrics" title="通过 ${stats.pass} · 进行中 ${stats.running} · 未通过/异常 ${stats.other}">
      <span class="ws-metric is-pass" title="通过 ${stats.pass}"><i></i><b>${stats.pass}</b></span>
      <span class="ws-metric is-running" title="进行中 ${stats.running}"><i></i><b>${stats.running}</b></span>
      <span class="ws-metric is-error" title="未通过/异常 ${stats.other}"><i></i><b>${stats.other}</b></span>
    </span>`;
  }

  function workspaceGroupPassHTML(items) {
    let passed = 0;
    let total = 0;
    for (const item of items) {
      const stats = workspaceStatsFor(item.id);
      if (!stats) continue;
      passed += stats.pass;
      total += stats.total;
    }
    if (!total) return "";
    return `<span class="ws-group-pass${passed ? "" : " is-zero"}" title="${items.length} 个运行 · ${total} 个任务 · ${passed} 个通过">${icon("check")}${passed}/${total}</span>`;
  }

  function workspaceDatasetRow(item, layout) {
    const id = item.id;
    const active = state.datasetId === id;
    const label = workspaceDatasetLabel(item, layout);
    const description = item.description || item.folder || `datasets/${id}`;
    const href = `?dataset=${encodeURIComponent(id)}`;
    return `<div class="ws-item-row${active ? " is-current" : ""}" draggable="true" data-workspace-drag="${escapeAttr(id)}" data-workspace-item="${escapeAttr(id)}">
      <a class="ws-item" href="${escapeAttr(href)}" data-dataset-option="${escapeAttr(id)}" role="menuitem" draggable="false"${active ? ' aria-current="page"' : ""}>
        <span class="ws-item-icon"><svg class="icon"><use href="#i-activity"/></svg></span>
        <span class="ws-item-copy"><strong data-ws-dataset-name="${escapeAttr(id)}">${escapeHTML(label)}</strong><small>${escapeHTML(description)}</small>${workspaceStatsFor(id) ? workspaceMetricsHTML(workspaceStatsFor(id)) : ""}</span>
        <span class="ws-item-check" aria-hidden="true"><svg class="icon"><use href="#i-check"/></svg></span>
      </a>
      <button class="ws-more" type="button" data-workspace-menu="dataset" data-workspace-id="${escapeAttr(id)}" aria-haspopup="menu" aria-label="${escapeAttr(label)} 的工作区操作" title="工作区操作">
        <svg class="icon"><use href="#i-more"/></svg>
      </button>
    </div>`;
  }

  function renderDatasetOptions() {
    closeWorkspaceActionMenu();
    if (!dom.datasetOptions || !dom.datasetMenuDivider) return;
    const datasets = (state.manifest || []).filter((item) => item && item.id && item.visible !== false);
    const layout = readWorkspaceLayout();
    const expandedIds = new Set(Array.isArray(layout.expanded) ? layout.expanded : []);
    const groupOrder = new Map();
    for (const item of datasets) {
      const id = defaultWorkspaceFolder(item);
      if (!groupOrder.has(id)) groupOrder.set(id, groupOrder.size);
    }
    for (const id of Object.keys(layout.folders)) {
      if (!groupOrder.has(id)) groupOrder.set(id, groupOrder.size);
    }
    const groups = new Map();
    for (const item of datasets) {
      const id = layout.placements[item.id] || defaultWorkspaceFolder(item);
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(item);
    }
    for (const id of Object.keys(layout.folders)) if (!groups.has(id)) groups.set(id, []);
    const orderedGroups = [...groups.entries()].sort(([left], [right]) => {
      return (groupOrder.get(left) ?? Number.MAX_SAFE_INTEGER) - (groupOrder.get(right) ?? Number.MAX_SAFE_INTEGER);
    });
    dom.datasetMenuDivider.hidden = false;
    dom.datasetOptions.innerHTML = orderedGroups
      .map(([id, items]) => {
        const title = workspaceFolderTitle(id, layout);
        const expanded = expandedIds.has(id);
        const rows = items.map((item) => workspaceDatasetRow(item, layout)).join("");
        return `<section class="ws-group${expanded ? "" : " is-collapsed"}" data-workspace-folder="${escapeAttr(id)}">
          <div class="ws-group-head">
            <button class="ws-group-toggle" type="button" data-workspace-toggle="${escapeAttr(id)}" aria-expanded="${String(expanded)}" title="${escapeAttr(expanded ? "收起" : "展开")} ${escapeAttr(title)}">
              <svg class="icon ws-chevron"><use href="#i-chevron"/></svg>
              <svg class="icon ws-group-icon"><use href="#i-folder"/></svg>
              <span class="ws-group-name" data-ws-folder-name="${escapeAttr(id)}">${escapeHTML(title)}</span>
              <span class="ws-group-count">${items.length}</span>
              ${workspaceGroupPassHTML(items)}
            </button>
            <button class="ws-more" type="button" data-workspace-menu="folder" data-workspace-id="${escapeAttr(id)}" aria-haspopup="menu" aria-label="${escapeAttr(title)} 的目录操作" title="目录操作">
              <svg class="icon"><use href="#i-more"/></svg>
            </button>
          </div>
          <div class="ws-group-body"${expanded ? "" : " hidden"}>${rows || '<div class="ws-empty">暂无工作区，可拖入此目录</div>'}</div>
        </section>`;
      })
      .join("");
  }

  function closeWorkspaceActionMenu(restoreFocus = false) {
    if (!dom.workspaceActionMenu) return;
    const trigger = workspaceActionTrigger;
    dom.workspaceActionMenu.hidden = true;
    dom.workspaceActionMenu.innerHTML = "";
    delete dom.workspaceActionMenu.dataset.workspaceKind;
    delete dom.workspaceActionMenu.dataset.workspaceId;
    workspaceActionTrigger = null;
    if (restoreFocus && trigger && trigger.isConnected) trigger.focus();
  }

  function openWorkspaceActionMenu(kind, id, trigger, point = null) {
    if (!dom.workspaceActionMenu) return;
    closeWorkspaceActionMenu();
    const layout = readWorkspaceLayout();
    let actions;
    if (kind === "folder") {
      const expanded = (layout.expanded || []).includes(id);
      actions = [
        { action: "rename", icon: "edit", label: "重命名目录" },
        { action: "toggle", icon: "chevron", label: expanded ? "收起目录" : "展开目录" },
      ];
    } else {
      const item = (state.manifest || []).find((entry) => entry.id === id);
      if (!item) return;
      actions = [
        { action: "open", icon: "arrow-up-right", label: "打开工作区" },
        { action: "rename", icon: "edit", label: "重命名" },
      ];
    }
    dom.workspaceActionMenu.dataset.workspaceKind = kind;
    dom.workspaceActionMenu.dataset.workspaceId = id;
    dom.workspaceActionMenu.innerHTML = actions
      .map((entry) => `<button class="ws-action-item" type="button" role="menuitem" data-ws-action="${entry.action}">${icon(entry.icon)}<span>${entry.label}</span></button>`)
      .join("");
    dom.workspaceActionMenu.hidden = false;
    workspaceActionTrigger = trigger;
    const width = dom.workspaceActionMenu.offsetWidth;
    const height = dom.workspaceActionMenu.offsetHeight;
    const rect = trigger.getBoundingClientRect();
    let left;
    let top;
    if (point) {
      left = point.x + 2;
      top = point.y + 2;
    } else {
      left = rect.right - width;
      top = rect.bottom + 4;
    }
    left = Math.min(Math.max(8, left), Math.max(8, window.innerWidth - width - 8));
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, (point ? point.y : rect.top) - height - 4);
    }
    top = Math.min(Math.max(8, top), Math.max(8, window.innerHeight - height - 8));
    dom.workspaceActionMenu.style.left = `${Math.round(left)}px`;
    dom.workspaceActionMenu.style.top = `${Math.round(top)}px`;
    requestAnimationFrame(() => {
      const first = $(".ws-action-item", dom.workspaceActionMenu);
      first?.focus({ preventScroll: true });
    });
  }

  function toggleWorkspaceFolder(id) {
    const layout = readWorkspaceLayout();
    const expanded = new Set(layout.expanded || []);
    if (expanded.has(id)) expanded.delete(id);
    else expanded.add(id);
    layout.expanded = [...expanded];
    if (saveWorkspaceLayout(layout)) renderDatasetOptions();
  }

  function startInlineRename(kind, id) {
    closeWorkspaceActionMenu();
    const layout = readWorkspaceLayout();
    const isFolder = kind === "folder";
    let host = null;
    let initial = "";
    if (isFolder) {
      const group = $$(".ws-group", dom.datasetOptions).find((element) => element.dataset.workspaceFolder === id);
      host = group?.querySelector(".ws-group-head") || null;
      initial = workspaceFolderTitle(id, layout);
    } else {
      const row = $$("[data-workspace-item]", dom.datasetOptions).find((element) => element.dataset.workspaceItem === id);
      const item = (state.manifest || []).find((entry) => entry.id === id);
      if (row) {
        host = row;
        row.draggable = false;
        initial = layout.names[id] || item?.label || id;
      }
    }
    if (!host) return;
    host.classList.add("is-renaming");
    host.innerHTML = `<span class="ws-rename-icon">${icon(isFolder ? "folder" : "activity")}</span><input class="ws-inline-input" type="text" maxlength="${isFolder ? 80 : 120}" spellcheck="false" autocomplete="off" aria-label="${isFolder ? "重命名目录" : "重命名工作区"}">`;
    const input = $(".ws-inline-input", host);
    input.value = initial;
    input.focus();
    input.select();
    let settled = false;
    const finish = (commit) => {
      if (settled) return;
      settled = true;
      const next = input.value.trim();
      if (commit && next) {
        const latest = readWorkspaceLayout();
        if (isFolder) latest.folders[id] = next.slice(0, 80);
        else latest.names[id] = next.slice(0, 120);
        saveWorkspaceLayout(latest);
        showToast(isFolder ? "目录已重命名" : "工作区已重命名");
      }
      if (isFolder) renderDatasetOptions();
      else setupWorkspaceSwitcher();
    };
    input.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      } else if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("blur", () => finish(true));
    input.addEventListener("click", (event) => event.stopPropagation());
  }

  function beginCreateFolder() {
    closeWorkspaceActionMenu();
    if (!dom.datasetOptions) return;
    const existing = $(".ws-create-row", dom.datasetOptions);
    if (existing) {
      $(".ws-inline-input", existing)?.focus();
      return;
    }
    const row = document.createElement("div");
    row.className = "ws-create-row";
    row.innerHTML = `<span class="ws-rename-icon">${icon("folder")}</span><input class="ws-inline-input" type="text" maxlength="80" spellcheck="false" autocomplete="off" placeholder="目录名称" aria-label="新目录名称">`;
    dom.datasetOptions.appendChild(row);
    const input = $(".ws-inline-input", row);
    row.scrollIntoView({ block: "nearest" });
    input.focus();
    let settled = false;
    const finish = (commit) => {
      if (settled) return;
      settled = true;
      const name = input.value.trim();
      row.remove();
      if (!commit || !name) return;
      const layout = readWorkspaceLayout();
      const id = `custom:${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      layout.folders[id] = name.slice(0, 80);
      layout.expanded = [...new Set([...(layout.expanded || []), id])];
      if (saveWorkspaceLayout(layout)) {
        renderDatasetOptions();
        const group = $$(".ws-group", dom.datasetOptions).find((element) => element.dataset.workspaceFolder === id);
        group?.scrollIntoView({ block: "nearest" });
        showToast("目录已创建");
      }
    };
    input.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      } else if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("blur", () => finish(false));
    input.addEventListener("click", (event) => event.stopPropagation());
  }

  function updateWorkspaceLinks() {
    if (!dom.workspaceMenu) return;
    const hash = nowHash();
    const query = window.location.search;
    const hrefs = { en: `/${query}${hash}`, zh: `/trace-viewer-zh/${query}${hash}` };
    $$("[data-site-option]", dom.workspaceMenu).forEach((option) => {
      const optionSite = option.dataset.siteOption;
      option.href = hrefs[optionSite] || "#";
    });
  }

  async function loadWorkspaceManifest() {
    return (await getJSON('/api/v1/runs')).data.datasets;
  }

  let workspaceStatsInFlight = false;

  async function refreshWorkspaceStats() {
    if (workspaceStatsInFlight || document.hidden) return;
    workspaceStatsInFlight = true;
    try {
      const response = await fetch("/api/v1/workspace-status", { cache: "no-cache" });
      if (!response.ok) return;
      const payload = await response.json();
      const next = payload && payload.datasets && typeof payload.datasets === "object" ? payload.datasets : null;
      if (!next) return;
      const signature = JSON.stringify(next);
      if (signature === state.workspaceStatsKey) return;
      state.workspaceStats = next;
      state.workspaceStatsKey = signature;
      if (dom.workspaceMenu && dom.workspaceMenu.hidden) renderDatasetOptions();
    } catch (_) {
      // Optional endpoint: static hosting still renders the workspace tree without metrics.
    } finally {
      workspaceStatsInFlight = false;
    }
  }

  function fitWorkspaceMenu() {
    if (!dom.workspaceMenu || !dom.workspaceTrigger) return;
    const bottom = dom.workspaceTrigger.getBoundingClientRect().bottom;
    const available = Math.max(180, window.innerHeight - bottom - 14);
    dom.workspaceMenu.style.maxHeight = `${Math.min(560, available)}px`;
  }

  function openWorkspaceMenu() {
    if (!dom.workspaceMenu || !dom.workspaceTrigger) return;
    closeWorkspaceActionMenu();
    renderDatasetOptions();
    dom.workspaceMenu.hidden = false;
    fitWorkspaceMenu();
    dom.workspaceTrigger.setAttribute("aria-expanded", "true");
  }

  function closeWorkspaceMenu() {
    closeWorkspaceActionMenu();
    if (!dom.workspaceMenu || !dom.workspaceTrigger) return;
    dom.workspaceMenu.hidden = true;
    dom.workspaceTrigger.setAttribute("aria-expanded", "false");
  }

  function toggleWorkspaceMenu() {
    if (dom.workspaceMenu.hidden) openWorkspaceMenu();
    else closeWorkspaceMenu();
  }


  return { setupWorkspaceSwitcher, readWorkspaceLayout, saveWorkspaceLayout, defaultWorkspaceFolder, workspaceFolderTitle, workspaceDatasetLabel, workspaceStatsFor, workspaceMetricsHTML, workspaceGroupPassHTML, workspaceDatasetRow, renderDatasetOptions, closeWorkspaceActionMenu, openWorkspaceActionMenu, toggleWorkspaceFolder, startInlineRename, beginCreateFolder, updateWorkspaceLinks, loadWorkspaceManifest, refreshWorkspaceStats, fitWorkspaceMenu, openWorkspaceMenu, closeWorkspaceMenu, toggleWorkspaceMenu };
}
