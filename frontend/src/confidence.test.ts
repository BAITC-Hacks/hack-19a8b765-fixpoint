import test from 'node:test';
import assert from 'node:assert/strict';
import { confidenceDisplay } from './confidence.ts';
import type { Trace } from './types.ts';

const base: Trace = {
  turn: 1, transcript: 'Где офис?', language: 'ru', confidence: .75, confidence_source: 'llm',
  scenarios: [{ scenario_id: 'SC33', confidence: .75 }], alternatives: [], reason: 'Офис',
  slots: {}, actions: [], latency_ms: {}, status: 'completed',
};

test('confidence bands use the case thresholds', () => {
  assert.equal(confidenceDisplay(base).band, 'high');
  assert.equal(confidenceDisplay({ ...base, confidence: .45 }).band, 'medium');
  assert.equal(confidenceDisplay({ ...base, confidence: .44 }).band, 'low');
  assert.equal(confidenceDisplay(base).value, '0.75 (75%)');
});

test('dialogue rule is not presented as model confidence', () => {
  const shown = confidenceDisplay({ ...base, confidence: null, confidence_source: 'dialogue_rule',
    scenarios: [{ scenario_id: 'SC33', confidence: 1 }] });
  assert.equal(shown.value, '—');
  assert.match(shown.note, /правилом диалога/);
});
