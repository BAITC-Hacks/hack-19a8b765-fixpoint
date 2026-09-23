import { useEffect, useRef, useState } from 'react';
import type { Trace } from '../types';
import TracePanel from './TracePanel';

type Summary = {
  session_id: string; created_at: string; updated_at: string; status: string;
  turn_count: number; preview: string; pending_request: boolean;
};
type SavedSession = {
  session_id: string; status: string; close_reason: string | null;
  turns: { turn_id: string; text: string | null; trace: Trace; input: { source: string } }[];
  traces: Trace[]; in_progress: { input: { text: string; source: string } } | null;
};
const statusLabel: Record<string, string> = { active: 'Активен', closed: 'Завершён', interrupted: 'Прерван' };
const PAGE_SIZE = 20;

export default function SessionArchive() {
  const [rows, setRows] = useState<Summary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState('');
  const [document, setDocument] = useState<SavedSession | null>(null);
  const [listError, setListError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [loading, setLoading] = useState(false);
  const request = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setListError('');
    void fetch(`/api/sessions?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('list');
        const data = await response.json() as { sessions: Summary[]; total: number };
        if (!Array.isArray(data.sessions) || typeof data.total !== 'number') throw new Error('format');
        if (!controller.signal.aborted) { setRows(data.sessions); setTotal(data.total); }
      })
      .catch(() => { if (!controller.signal.aborted) setListError('Не удалось загрузить архив. Проверьте сервер.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, revision]);

  useEffect(() => {
    const controller = new AbortController();
    const epoch = ++request.current;
    setDocument(null);
    setDetailError('');
    if (selected) void fetch(`/api/sessions/${encodeURIComponent(selected)}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('detail');
        const data = await response.json() as SavedSession;
        if (!Array.isArray(data.turns) || !Array.isArray(data.traces)) throw new Error('format');
        if (request.current === epoch && !controller.signal.aborted) setDocument(data);
      })
      .catch(() => { if (!controller.signal.aborted) setDetailError('Не удалось прочитать выбранный разговор.'); });
    return () => controller.abort();
  }, [selected, revision]);

  return <section className="session-archive" aria-label="Сохранённые разговоры">
    <h2>Сохранённые разговоры</h2>
    <p className="muted">История и трассировка сохраняются на сервере после каждого хода. Архив открывается для просмотра, без повторного выполнения операций.</p>
    <div className="trace-tools">
      <button onClick={() => setRevision(value => value + 1)} disabled={loading}>Обновить архив</button>
      <span>{total} разговоров</span>
    </div>
    {listError && <p role="alert" className="error">{listError}</p>}
    {loading && <p role="status">Загружаю…</p>}
    {!loading && !listError && !rows.length && <p>Сохранённых разговоров пока нет.</p>}
    <ul className="archive-list">{rows.map(row => <li key={row.session_id}>
      <button onClick={() => setSelected(row.session_id)} aria-pressed={selected === row.session_id}>
        <span>{new Date(row.created_at).toLocaleString('ru-RU')} · {statusLabel[row.status] ?? row.status} · {row.turn_count} реплик{row.pending_request ? ' · незавершённый ход' : ''}</span>
        <strong>{row.preview || 'Без реплик'}</strong>
        <small>{row.session_id}</small>
      </button>
    </li>)}</ul>
    <div className="trace-tools">
      <button disabled={page === 0 || loading} onClick={() => setPage(value => value - 1)}>Назад</button>
      <span>Страница {page + 1}</span>
      <button disabled={(page + 1) * PAGE_SIZE >= total || loading} onClick={() => setPage(value => value + 1)}>Далее</button>
    </div>
    {detailError && <p role="alert" className="error">{detailError}</p>}
    {selected && !document && !detailError && <p role="status">Загружаю разговор…</p>}
    {document && <div className="archive-detail">
      <p><strong>{statusLabel[document.status] ?? document.status}</strong> · {document.session_id}</p>
      <a href={`/api/sessions/${encodeURIComponent(document.session_id)}/export`} download>Скачать разговор и трассировки (JSON)</a>
      {document.in_progress && <p className="notice">Последний ход не завершён. Результат операции может быть неизвестен; архив не запускает её повторно.</p>}
      <div className="archive-dialogue">{document.turns.map((turn, index) => <article key={`${turn.turn_id}-${index}`}>
        <p className="muted">Ход {turn.trace.turn} · {turn.input.source === 'audio' ? 'Голос' : 'Текст'}</p>
        <p><strong>Вы:</strong> {turn.trace.transcript || 'Транскрипт отсутствует'}</p>
        <p><strong>Saqta:</strong> {turn.text ?? 'Ответ не сформирован'}</p>
      </article>)}</div>
      <TracePanel key={document.session_id} traces={document.traces} openByDefault />
    </div>}
  </section>;
}
