import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, sessionReducer } from './sessionReducer.ts';
test('replayed events do not duplicate assistant messages', () => {
  const action = { type: 'event' as const, event: { type: 'assistant.text', event_id: 2, turn_id: 't1', payload: { text: 'Ответ сервера' } } };
  const state = sessionReducer(initialState, action);
  assert.equal(sessionReducer(state, action).messages.length, 1);
  assert.equal(sessionReducer(state, { ...action, event: { ...action.event, event_id: 1 } }), state);
});
test('pending turn blocks double submit; reset removes history and traces', () => {
  const action = { type: 'user' as const, message: { id: 'one', role: 'user' as const, text: 'Вопрос' }, online: true };
  const state = sessionReducer(initialState, action);
  assert.equal(state.busy, true);
  assert.equal(sessionReducer(state, { ...action, message: { ...action.message, id: 'two' } }), state);
  assert.deepEqual(sessionReducer(state, { type: 'reset' }), initialState);
});
test('unknown timings stay null; trace updates replace the same turn', () => {
  const event = { type: 'trace.updated', event_id: 1, payload: { turn: 1, scenarios: [], alternatives: [], reason: 'Уточнение', latency_ms: { total: null } } };
  const state = sessionReducer(initialState, { type: 'event', event });
  const updated = sessionReducer(state, { type: 'event', event: { ...event, event_id: 2 } });
  assert.equal(updated.traces.length, 1);
  assert.equal(updated.traces[0].latency_ms.total, null);
});

test('audio transcript and answer share one server turn without duplicates', () => {
  const transcript = { type: 'event' as const, event: { type: 'transcript.final', event_id: 1, turn_id: 'turn-1', payload: { text: 'Где офис?', source: 'audio' } } };
  const answer = { type: 'event' as const, event: { type: 'assistant.text', event_id: 2, turn_id: 'turn-1', payload: { text: 'В Алматы.', language: 'ru' } } };
  const state = sessionReducer(sessionReducer(initialState, transcript), answer);
  assert.deepEqual(state.messages.map(m => m.text), ['Где офис?', 'В Алматы.']);
  assert.equal(sessionReducer(state, answer).messages.length, 2);
  assert.equal(state.messages[1].language, 'ru');
});
