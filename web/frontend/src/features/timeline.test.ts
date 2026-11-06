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
