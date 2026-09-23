import { useState } from 'react';
import type { Trace } from '../types';
import { confidenceDisplay } from '../confidence';

export default function TracePanel({ traces, openByDefault = false }: { traces: Trace[]; openByDefault?: boolean }) {
  const [selected, setSelected] = useState('latest');
  const trace = selected === 'latest' ? traces.at(-1) : traces.find(t => String(t.turn) === selected);
  const confidence = trace ? confidenceDisplay(trace) : null;
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(traces, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'saqta-trace.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <details className="diagnostics" open={openByDefault}>
    <summary>Диагностика разговора <span>{traces.length ? `${traces.length} реплик` : 'Нет данных'}</span></summary>
    {!trace ? <p className="muted">Трассировка появится после обработки реплики сервером. Уверенность, сценарии и задержки не имитируются.</p> : <>
      <div className="trace-tools"><label>Реплика <select value={selected} onChange={e => setSelected(e.target.value)}>
        <option value="latest">Последняя</option>{traces.map(t => <option key={t.turn} value={t.turn}>{t.turn}</option>)}
      </select></label><button onClick={download}>Скачать JSON</button></div>
      <dl>
        <dt>Транскрипт</dt><dd>{trace.transcript}</dd>
        <dt>Язык</dt><dd>{trace.language}</dd>
        <dt>Confidence</dt><dd>{confidence?.value} · {confidence?.scenario}. {confidence?.note}</dd>
        <dt>Сценарии</dt><dd>{trace.scenarios.map(s => `${s.scenario_id}${s.name ? ` · ${s.name}` : ''} (${Math.round(s.confidence * 100)}%)`).join(', ') || '—'}</dd>
        <dt>Обоснование</dt><dd>{trace.reason}</dd>
        <dt>Альтернативы</dt><dd>{trace.alternatives.map(s => `${s.scenario_id} (${Math.round(s.confidence * 100)}%)`).join(', ') || '—'}</dd>
        <dt>Задержки</dt><dd>{Object.entries(trace.latency_ms).map(([key, value]) => <div key={key}>{key}: {value == null ? 'не измерено' : `${value} мс`}</div>)}</dd>
      </dl>
      <p className="muted">Уверенность модели — сигнал для выбора действия, а не вероятность правильного ответа.</p>
      <details><summary>Слоты и действия</summary><pre>{JSON.stringify({ slots: trace.slots, actions: trace.actions }, null, 2)}</pre></details>
    </>}
  </details>;
}
