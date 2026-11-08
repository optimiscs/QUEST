import { describe, expect, it } from 'vitest';
import { createTimeline, recordedTiming } from './timeline.js';

function fixture(steps: object[]) {
  const dom = { chartTitle: { textContent: '' }, chartSub: { textContent: '' },
    chartLegend: { innerHTML: '' }, timelineVisual: { innerHTML: '' } };
  const timeline = createTimeline({ state: {}, dom, activeCase: () => null, $$: () => [],
    formatAxis: String, escapeAttr: String, formatDuration: String, number: String,
    formatSeconds: String, escapeHTML: String, pad: String });
  const c = { steps, timingAvailable: false, durationSeconds: 1,
    stats: { computeCalls: 0, searchCalls: 1, readCalls: 0 } };
  return { dom, timeline, c };
}

describe('partial recorded timelines', () => {
  it('keeps resumed calls after the pause on the original wall clock', () => {
    const { dom, timeline, c } = fixture([
      { n: 1, kind: 'answer', modelStart: 1, model_seconds: 2 },
      { n: 2, kind: 'answer', modelStart: 3601, model_seconds: 2 },
    ]);
    timeline.renderDurationChart({ ...c, durationSeconds: 3610, timing: { includesPauses: true } });
    expect(dom.chartSub.textContent).toContain('自首次启动起，含暂停间隔');
    expect(dom.timelineVisual.innerHTML).toContain('left:0.028%');
    expect(dom.timelineVisual.innerHTML).toContain('left:99.600%');
  });
  it('marks failed tool spans and rounds red, including failures without timing', () => {
    const { dom, timeline, c } = fixture([
      { n: 1, kind: 'read', label: '读取', modelStart: 0, model_seconds: 1,
        toolStart: 1, tool_seconds: 2, toolOutcome: { status: 'failed', error: 'TLS error' } },
      { n: 2, kind: 'compute', toolOutcome: { status: 'failed', error: 'execution error' } },
      { n: 3, kind: 'search', toolStart: 3, tool_seconds: 1, toolOutcome: { status: 'success' } },
    ]);
    timeline.renderDurationChart(c);
    expect(dom.timelineVisual.innerHTML).toContain('chart-bar read tool-failed');
    expect(dom.timelineVisual.innerHTML).not.toContain('chart-bar model tool-failed');
    expect(dom.timelineVisual.innerHTML).toContain('chart-bar search"');
    timeline.renderRoundsChart(c);
    expect(dom.timelineVisual.innerHTML).toContain('round-cell compute tool-failed');
    expect(dom.timelineVisual.innerHTML).toContain('工具失败：TLS error');
  });
  it('renders recorded spans despite the legacy incomplete flag, without inventing missing spans', () => {
    const { dom, timeline, c } = fixture([
      { n: 1, kind: 'search', modelStart: 2, model_seconds: 3, toolStart: 5, tool_seconds: 2 },
      { n: 2, kind: 'answer', modelStart: null, model_seconds: null },
    ]);
    timeline.renderDurationChart(c);
    expect(dom.chartSub.textContent).toContain('部分耗时缺失');
    expect(dom.timelineVisual.innerHTML.match(/class="chart-bar /g)).toHaveLength(2);
    expect(dom.timelineVisual.innerHTML).toContain('已记录模型步骤 1/2 · 工具调用 1/1');
    expect(recordedTiming(c).total).toBe(7);
    timeline.renderCallsChart(c);
    expect(dom.timelineVisual.innerHTML.match(/class="chart-bar /g)).toHaveLength(1);
  });

  it('renders tool timings even when every model timing is missing', () => {
    const { dom, timeline, c } = fixture([{ n: 1, kind: 'search', toolStart: 1, tool_seconds: 0 }]);
    timeline.renderDurationChart(c);
    expect(dom.timelineVisual.innerHTML).toContain('class="chart-bar search"');
    expect(dom.timelineVisual.innerHTML).not.toContain('class="chart-bar model"');
  });

  it('keeps unrecorded, negative and nonfinite spans unknown', () => {
    const { dom, timeline, c } = fixture([
      { n: 1, kind: 'search', modelStart: null, model_seconds: 3, toolStart: 2, tool_seconds: null },
      { n: 2, kind: 'read', modelStart: -1, model_seconds: 1, toolStart: 1, tool_seconds: Infinity },
    ]);
    timeline.renderDurationChart(c);
    expect(dom.timelineVisual.innerHTML).toContain('没有可可靠匹配');
    expect(dom.timelineVisual.innerHTML).not.toContain('chart-bar');
    timeline.renderCallsChart(c);
    expect(dom.timelineVisual.innerHTML).not.toContain('chart-bar');
  });
});
