export function createStatus(state) {
  function caseState(caseData) {
    if (caseData.interrupted) return { key: "stopped", label: "已中断" };
    if (caseData.inProgress && (state.data.run?.stopped || state.datasetMeta?.lifecycleOverride === "stopped")) return { key: "stopped", label: "已终止" };
    if (caseData.inProgress) return { key: "running", label: "进行中" };
    if (caseData.correct === true) return { key: "pass", label: "通过" };
    if (caseData.correct === false) return { key: "fail", label: "未通过" };
    if (typeof caseData.score === "number" && Number.isFinite(caseData.score)) return { key: "scored", label: `已评分 ${caseData.score.toFixed(3)}` };
    if (caseData.scoredDimensions) return { key: "scored", label: "已完成维度评分" };
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

return { caseState, caseStateDetail, hasGroundTruth, runLifecycleState, statusLabel, riskInfo };
}
