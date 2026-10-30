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
    if (value == null || !Number.isFinite(Number(value))) return "未记录";
    const seconds = Number(value);
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
    if (value == null || !Number.isFinite(Number(value))) return "未记录";
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


export { escapeHTML, escapeAttr, safeURL, pad, number, pluralCount, formatSeconds, formatDuration, formatAxis, clampText };
