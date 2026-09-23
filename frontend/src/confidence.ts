import type { Trace } from './types';

export function confidenceDisplay(trace: Trace) {
  const scenario = trace.scenarios[0]?.scenario_id ?? '—';
  if (trace.confidence_source !== 'llm' || typeof trace.confidence !== 'number') {
    const source = trace.confidence_source === 'dialogue_rule' ? 'Ход обработан правилом диалога.' :
      trace.confidence_source === 'manual_demo' ? 'Сценарий выбран вручную.' :
      trace.confidence_source === 'mock' ? 'LLM не подключена.' : 'Оценка недоступна.';
    return { scenario, value: '—', note: source, band: 'unavailable' };
  }
  const value = `${trace.confidence.toFixed(2)} (${Math.round(trace.confidence * 100)}%)`;
  if (trace.confidence >= .75) return { scenario, value, note: 'Порог запуска сценария: 0,75.', band: 'high' };
  if (trace.confidence >= .45) return { scenario, value, note: 'Нужно уточнить запрос: 0,45–0,75.', band: 'medium' };
  return { scenario, value, note: trace.status === 'handoff' ? 'Низкая уверенность: передача оператору.' :
    'Низкая уверенность: нужен уточняющий вопрос.', band: 'low' };
}
