import { useEffect, useRef, useState } from 'react';
import type { Language } from './types';
import { useMicrophone } from './hooks/useMicrophone';
import { useSession } from './hooks/useSession';
import TracePanel from './components/TracePanel';
import { confidenceDisplay } from './confidence';

const params = new URLSearchParams(location.search);
const dev = params.has('dev');
const jury = dev || params.has('jury');

export default function App() {
  const session = useSession();
  const [phase, setPhase] = useState<'idle' | 'connecting' | 'listening' | 'processing' | 'speaking'>('idle');
  const [draft, setDraft] = useState('');
  const [language, setLanguage] = useState<Language>('auto');
  const [error, setError] = useState('');
  const [active, setActive] = useState(false);
  const activeRef = useRef(false);
  const player = useRef<HTMLAudioElement | null>(null);
  const audioUrl = useRef<string | null>(null);
  const lastAudioTurn = useRef('');
  const history = useRef<HTMLDivElement>(null);
  const mic = useMicrophone((blob, endedAt) => {
    if (!activeRef.current) return;
    setPhase('processing');
    void session.sendAudio(blob, language, endedAt).then(ok => {
      if (!ok && activeRef.current) stop('Не удалось отправить запись. Проверьте соединение и начните разговор снова.');
    });
  });

  function stop(message = '') {
    activeRef.current = false;
    setActive(false);
    mic.abort();
    player.current?.pause();
    player.current = null;
    if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
    audioUrl.current = null;
    session.end();
    setPhase('idle');
    if (message) setError(message);
  }
  async function start() {
    setError('');
    mic.clearError();
    session.reset();
    activeRef.current = true;
    setActive(true);
    setPhase('connecting');
    const connected = await session.connect();
    if (!connected || !activeRef.current) {
      if (activeRef.current) stop('Не удалось соединиться с сервером. Проверьте запуск FastAPI.');
      return;
    }
    const recording = await mic.start();
    if (!recording || !activeRef.current) {
      if (activeRef.current) stop(recording ? '' : 'Микрофон недоступен. Разрешите доступ и начните разговор снова.');
      else mic.abort();
      return;
    }
    setPhase('listening');
  }
  useEffect(() => {
    const item = session.completedAudio;
    if (!item || item.turnId === lastAudioTurn.current || !activeRef.current || phase !== 'processing') return;
    lastAudioTurn.current = item.turnId;
    if (item.failed || !item.segments.length) {
      stop(item.error || 'Ответ получен, но сервер не смог его озвучить. Текст ответа показан ниже.');
      return;
    }
    const bytes = item.segments.map(segment => Uint8Array.from(atob(segment), c => c.charCodeAt(0)));
    const blob = new Blob(bytes, { type: item.mime });
    const url = URL.createObjectURL(blob);
    audioUrl.current = url;
    const audio = new Audio(url);
    player.current = audio;
    let reported = false;
    audio.onplaying = () => {
      setPhase('speaking');
      if (!reported && item.endedAt > 0) {
        reported = true;
        session.reportPlayback(Math.round(performance.now() - item.endedAt), item.turnId);
      }
    };
    audio.onended = () => {
      URL.revokeObjectURL(url);
      audioUrl.current = null;
      player.current = null;
      if (!activeRef.current) return;
      if (session.closed) { stop(); return; }
      setPhase('listening');
      void mic.start().then(ok => { if (!ok && activeRef.current) stop('Микрофон перестал работать. Проверьте доступ и начните разговор снова.'); });
    };
    audio.onerror = () => stop('Не удалось воспроизвести голосовой ответ. Проверьте звук и начните разговор снова.');
    void audio.play().catch(() => stop('Браузер заблокировал воспроизведение звука. Разрешите звук для сайта и начните разговор снова.'));
  }, [session.completedAudio, phase]);
  useEffect(() => { if (history.current) history.current.scrollTop = history.current.scrollHeight; }, [session.messages]);
  useEffect(() => { if (active && session.connection === 'local' && phase !== 'connecting') stop('Соединение потеряно. Начните разговор снова.'); }, [session.connection]);
  useEffect(() => { if (active && mic.error) stop(mic.error); }, [mic.error]);
  useEffect(() => () => {
    activeRef.current = false;
    player.current?.pause();
    if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
  }, []);

  function sendText() {
    if (session.send(draft, language)) setDraft('');
    else setError('Сначала подключите сервер в режиме разработчика.');
  }
  const status = phase === 'connecting' ? 'Подключаюсь…' : phase === 'listening' ? 'Слушаю вас…' :
    phase === 'processing' ? 'Обрабатываю реплику…' : phase === 'speaking' ? 'Отвечаю…' : 'Нажмите кнопку и говорите';
  const visibleError = error || mic.error || session.error;
  const latestTrace = session.traces.at(-1);
  const confidence = latestTrace ? confidenceDisplay(latestTrace) : null;

  return <div className="app">
    <header className="header"><div className="brand"><span className="brand-symbol" aria-hidden="true">s.</span><span>Saqta<span className="brand-caption">Голосовой помощник</span></span></div><span className="demo-label">Демонстрация</span></header>
    <main className="voice-page">
      <p className="eyebrow">SAQTA INSURANCE</p>
      <h1>Чем можем помочь?</h1>
      <p className="muted voice-intro">Говорите на русском или қазақша. После ответа я продолжу слушать.</p>
      <button className={`primary conversation-button ${active ? 'recording' : ''}`} onClick={() => active ? stop() : void start()} aria-pressed={active} aria-label={active ? 'Завершить разговор' : 'Начать разговор'}>
        <span className="conversation-icon" aria-hidden="true">{active ? '■' : '●'}</span>{active ? 'Завершить разговор' : 'Начать разговор'}
      </button>
      <p className="voice-status" role="status"><span className={phase === 'listening' ? 'recording-dot' : 'idle-dot'} />{status}</p>
      {visibleError && <p className="error" role="alert">{visibleError}</p>}
      <section className="conversation-text" aria-label="Текст разговора">
        <h2>Разговор</h2>
        <div className="history" ref={history} role="log" aria-live="polite">
          {session.messages.length ? session.messages.map(message =>
            <article key={message.id} className={`message ${message.role}`}>
              <strong className="message-role">{message.role === 'user' ? 'Вы' : 'Saqta'}</strong>
              <p>{message.text}</p>
            </article>) : <p className="conversation-placeholder">Здесь появятся ваши слова и ответ помощника.</p>}
        </div>
      </section>
      {confidence && <div className={`confidence-card ${confidence.band}`} aria-live="polite">
        <span>Confidence · последняя реплика · {confidence.scenario}</span>
        <strong>{confidence.value}</strong>
        <small>{confidence.note}{latestTrace?.confidence_source === 'llm' ? ' Оценка модели не равна вероятности правильного ответа.' : ''}</small>
      </div>}
      <p className="demo-note">Операции и передача оператору выполняются только в демонстрационных данных.</p>
      {jury && <TracePanel traces={session.traces} openByDefault />}
      {dev && <section className="developer" aria-label="Режим разработчика">
        <h2>Диагностика разговора</h2>
        <p className="muted">Сервер: {session.connection}. Текст использует тот же конвейер после распознавания речи.</p>
        {session.connection !== 'online' && <button onClick={() => { setError(''); void session.connect(); }}>Подключить для текста</button>}
        <label className="language">Язык для диагностики <select value={language} onChange={e => setLanguage(e.target.value as Language)}><option value="auto">Автоматически</option><option value="ru">Русский</option><option value="kk">Қазақша</option></select></label>
        <form className="composer" onSubmit={event => { event.preventDefault(); sendText(); }}><label className="sr-only" htmlFor="message">Сообщение</label><textarea id="message" value={draft} onChange={event => setDraft(event.target.value)} maxLength={4000} rows={2} placeholder="Введите реплику для проверки…" disabled={session.busy || active} /><button type="submit" disabled={!draft.trim() || session.busy || active || session.connection !== 'online'}>Отправить</button></form>
      </section>}
    </main>
  </div>;
}
