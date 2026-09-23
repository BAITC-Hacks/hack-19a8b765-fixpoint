import { useEffect, useRef, useState } from 'react';
import type { Language } from './types';
import { useMicrophone } from './hooks/useMicrophone';
import { useSession } from './hooks/useSession';
import TracePanel from './components/TracePanel';
import { confidenceDisplay } from './confidence';
import AudioVisualizer from './components/AudioVisualizer';
import SessionArchive from './components/SessionArchive';
import { endOfSpeechForSlot } from './voiceActivity';

const params = new URLSearchParams(location.search);

export default function App() {
  const session = useSession();
  const [phase, setPhase] = useState<'idle' | 'connecting' | 'preparing' | 'listening' | 'processing' | 'speaking'>('idle');
  const [draft, setDraft] = useState('');
  const [language, setLanguage] = useState<Language>('auto');
  const [error, setError] = useState('');
  const [active, setActive] = useState(false);
  const [devOpen, setDevOpen] = useState(params.has('dev') || params.has('jury'));
  const [queuedText, setQueuedText] = useState<string | null>(null);
  const devPanel = useRef<HTMLDialogElement>(null);
  const devToggle = useRef<HTMLButtonElement>(null);
  const activeRef = useRef(false);
  const player = useRef<HTMLAudioElement | null>(null);
  const audioUrl = useRef<string | null>(null);
  const lastAudioTurn = useRef('');
  const history = useRef<HTMLDivElement>(null);
  const mic = useMicrophone((blob, endedAt, capture) => {
    if (!activeRef.current) return;
    setPhase('processing');
    void session.sendAudio(blob, language, endedAt, capture).then(ok => {
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
    setPhase('preparing');
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
      setPhase('preparing');
      void mic.start(endOfSpeechForSlot(session.waitingSlot)).then(ok => {
        if (!activeRef.current) { if (ok) mic.abort(); return; }
        if (!ok) stop('Микрофон перестал работать. Проверьте доступ и начните разговор снова.');
        else setPhase('listening');
      });
    };
    audio.onerror = () => stop('Не удалось воспроизвести голосовой ответ. Проверьте звук и начните разговор снова.');
    void audio.play().catch(() => stop('Браузер заблокировал воспроизведение звука. Разрешите звук для сайта и начните разговор снова.'));
  }, [session.completedAudio, phase]);
  useEffect(() => { if (history.current) history.current.scrollTop = history.current.scrollHeight; }, [session.messages]);
  useEffect(() => { if (active && session.connection === 'local' && phase !== 'connecting') stop('Соединение потеряно. Начните разговор снова.'); }, [session.connection]);
  useEffect(() => { if (active && mic.error) stop(mic.error); }, [mic.error]);
  useEffect(() => {
    if (active && phase === 'listening' && mic.phase === 'stopping') setPhase('processing');
  }, [active, phase, mic.phase]);
  useEffect(() => () => {
    activeRef.current = false;
    player.current?.pause();
    if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
  }, []);

  useEffect(() => {
    if (devOpen) devPanel.current?.showModal();
    else if (devPanel.current?.open) { devPanel.current.close(); devToggle.current?.focus(); }
  }, [devOpen]);
  useEffect(() => {
    if (queuedText === null || session.connection !== 'online' || session.closed) return;
    if (session.send(queuedText, language)) setDraft('');
    else setError('Не удалось отправить сообщение. Попробуйте снова.');
    setQueuedText(null);
  }, [queuedText, session.connection, session.closed]);

  async function sendText() {
    if (!draft.trim() || active || session.busy || queuedText !== null) return;
    setError('');
    mic.clearError();
    if (session.connection === 'online' && !session.closed) {
      if (session.send(draft, language)) setDraft('');
      return;
    }
    setQueuedText(draft);
    if (session.closed) session.reset();
    if (!await session.connect()) setQueuedText(null);
  }
  const status = phase === 'connecting' ? 'Подключаюсь…' : phase === 'preparing' ? 'Готовлю микрофон…' : phase === 'listening' ? 'Слушаю вас…' :
    phase === 'processing' ? 'Обрабатываю реплику…' : phase === 'speaking' ? 'Отвечаю…' :
    queuedText !== null ? 'Подключаюсь…' : session.busy ? 'Готовлю ответ…' : 'Нажмите кнопку и говорите';
  const visibleError = error || mic.error || session.error;
  const latestTrace = session.traces.at(-1);
  const confidence = latestTrace ? confidenceDisplay(latestTrace) : null;

  return <div className="app">
    <button ref={devToggle} className="dev-toggle" aria-label="Открыть инструменты разработчика" aria-expanded={devOpen} aria-controls="dev-panel" onClick={() => setDevOpen(true)}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18" /></svg><span>dev</span>
    </button>
    <main className="voice-page">
      <h1>Чем можем помочь?<span lang="kk">Қалай көмектесе аламыз?</span></h1>
      <div className="voice-interaction">
        <button className={`primary conversation-button ${active ? 'recording' : ''}`} disabled={!active && (session.busy || queuedText !== null || session.connection === 'connecting')} onClick={() => active ? stop() : void start()} aria-pressed={active} aria-label={active ? 'Завершить разговор' : 'Начать разговор'} title={active ? 'Завершить разговор' : 'Начать разговор'}>
          {active ? <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="3" /></svg> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><rect x="9" y="2" width="6" height="13" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" /></svg>}
        </button>
        {active && <AudioVisualizer analyserRef={mic.analyserRef} listening={phase === 'listening'} />}
        <p className="voice-status" role="status">{status}</p>
      </div>
      <form className="composer" onSubmit={event => { event.preventDefault(); void sendText(); }}>
        <label className="sr-only" htmlFor="message">Сообщение / Хабарлама</label>
        <textarea id="message" value={draft} onChange={event => setDraft(event.target.value)} maxLength={4000} rows={2} placeholder="Или напишите нам / Немесе жазыңыз" disabled={session.busy || active || queuedText !== null} onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendText(); }
        }} />
        <button className="send" type="submit" aria-label="Отправить сообщение" disabled={!draft.trim() || session.busy || active || queuedText !== null || session.connection === 'connecting'}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" /></svg>
        </button>
      </form>
      {visibleError && <p className="error" role="alert">{visibleError}</p>}
      <section className={`conversation-text ${session.messages.length ? 'has-messages' : ''}`} aria-label="Текст разговора">
        <div className="history" ref={history} role="log" aria-live="polite">
          {session.messages.map(message =>
            <article key={message.id} className={`message ${message.role}`}>
              <strong className="message-role">{message.role === 'user' ? 'Вы' : 'Saqta'}</strong>
              <p>{message.text}</p>
            </article>)}
        </div>
      </section>
      <p className="demo-note">Демонстрация · Все операции выполняются на тестовых данных.</p>
    </main>
    <dialog ref={devPanel} id="dev-panel" className="developer" aria-labelledby="dev-title" onCancel={() => setDevOpen(false)} onClose={() => setDevOpen(false)} onClick={event => { if (event.target === event.currentTarget) setDevOpen(false); }}>
      <div className="developer-content">
        <div className="developer-heading"><div><p className="eyebrow">SAQTA · DEV MODE</p><h2 id="dev-title">Инструменты</h2></div><button aria-label="Закрыть инструменты разработчика" onClick={() => setDevOpen(false)}>×</button></div>
        <dl className="session-status"><dt>Соединение</dt><dd>{session.connection}</dd><dt>Состояние</dt><dd>{phase}</dd></dl>
        <div className="developer-actions">
          {session.connection !== 'online' && <button disabled={session.connection === 'connecting' || queuedText !== null} onClick={() => { setError(''); void session.connect(); }}>Подключить сервер</button>}
          <button disabled={queuedText !== null} onClick={() => { stop(); session.reset(); setError(''); mic.clearError(); setDraft(''); }}>Сбросить разговор</button>
        </div>
        <label className="language">Язык для диагностики <select value={language} disabled={active || session.busy || queuedText !== null} onChange={e => setLanguage(e.target.value as Language)}><option value="auto">Автоматически</option><option value="ru">Русский</option><option value="kk">Қазақша</option></select></label>
        {confidence && <div className={`confidence-card ${confidence.band}`} aria-live="polite">
        <span>Confidence · последняя реплика · {confidence.scenario}</span>
        <strong>{confidence.value}</strong>
        <small>{confidence.note}{latestTrace?.confidence_source === 'llm' ? ' Оценка модели не равна вероятности правильного ответа.' : ''}</small>
      </div>}
        <TracePanel traces={session.traces} openByDefault />
        {devOpen && <SessionArchive />}
      </div>
    </dialog>
  </div>;
}
