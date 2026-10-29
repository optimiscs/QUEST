import { expect, test } from 'vitest';
import { createStatus } from './status';

test('execution, scoring and lifecycle overrides retain their meaning', () => {
  const state = { data: { run: { stopped: false } }, datasetMeta: { lifecycleOverride: '' } };
  const { caseState } = createStatus(state);
  expect(caseState({ correct: true }).key).toBe('pass');
  expect(caseState({ correct: false }).key).toBe('fail');
  expect(caseState({ correct: null }).key).toBe('error');
  expect(caseState({ score: 0.7 }).key).toBe('scored');
  expect(caseState({ inProgress: true }).key).toBe('running');
  state.datasetMeta.lifecycleOverride = 'stopped';
  expect(caseState({ inProgress: true }).key).toBe('stopped');
  expect(caseState({ correct: true }).key).toBe('pass');
});
