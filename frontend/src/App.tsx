import { useEffect, useRef, useState } from 'react';
import type { Language } from './types';
import { useMicrophone } from './hooks/useMicrophone';
import { useSession } from './hooks/useSession';
import TracePanel from './components/TracePanel';
import DesignPreview from './components/DesignPreview';

function MicIcon({ stop = false }: { stop?: boolean }) {
  return <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">{stop
    ? <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
    : <><rect x="9" y="3" width="6" height="12" rx="3" stroke="currentColor" strokeWidth="1.7" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></>}</svg>;
}

export default function App() {
  const session = useSession();
  const [preview, setPreview] = useState(false);
  const [draft, setDraft] = useState('');
  const [language, setLanguage] = useState<Language>('ru');
  const [speaking, setSpeaking] = useState(false);
  const [audioError, setAudioError] = useState('');
  const [voiceLanguage, setVoiceLanguage] = useState('');
  const mic = useMicrophone(text => { setDraft(previous => [previous.trim(), text].filter(Boolean).join(' ').slice(0, 4000)); input.current?.focus(); });
  const input = useRef<HTMLTextAreaElement>(null);
  const history = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const connecting = session.connection === 'connecting';
  const listening = mic.phase !== 'idle';
  const blocked = session.busy || connecting || session.closed;
  useEffect(() => { if (history.current && stickToBottom.current) history.current.scrollTop = history.current.scrollHeight; }, [session.messages, mic.partial]);
  useEffect(() => {
    const update = () => setVoiceLanguage(window.speechSynthesis?.getVoices().find(v => v.lang.toLowerCase().startsWith(language))?.lang ?? '');
    update(); window.speechSynthesis?.addEventListener('voiceschanged', update);
    return () => window.speechSynthesis?.removeEventListener('voiceschanged', update);
  }, [language]);
  useEffect(() => () => window.speechSynthesis?.cancel(), []);

  function send() {
    if (blocked || listening || speaking) return;
    if (session.send(draft, language)) setDraft('');
  }
  function stopSound() { window.speechSynthesis?.cancel(); setSpeaking(false); }
  function speak(text: string) {
    stopSound(); setAudioError('');
    if (!voiceLanguage) { setAudioError('Для выбранного языка в браузере нет голоса. Текст ответа доступен.'); return; }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = voiceLanguage;
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = e => { setSpeaking(false); if (e.error !== 'interrupted' && e.error !== 'canceled') setAudioError('Не удалось воспроизвести ответ.'); };
    window.speechSynthesis.speak(utterance);
  }
  function reset() { mic.abort(); mic.clearError(); stopSound(); setAudioError(''); setDraft(''); session.reset(); }
  const status = mic.phase === 'starting' ? 'Ожидаю доступ к микрофону…' : mic.phase === 'listening' ? 'Слушаю вас…' : mic.phase === 'stopping' ? 'Завершаю распознавание…' : speaking ? 'Воспроизвожу ответ' : session.busy ? 'Обрабатываю сообщение…' : connecting ? 'Подключаюсь…' : session.closed ? 'Разговор завершён' : 'Можно говорить или написать';

  if (preview) return <DesignPreview onExit={() => setPreview(false)} />;

  return <div className="app">
    <header className="header"><a className="brand" href="/" aria-label="Saqta — главная"><span className="brand-symbol" aria-hidden="true">s.</span><span>Saqta<span className="brand-caption">Голосовой помощник</span></span></a>
      <div className="header-actions"><button onClick={() => { mic.abort(); stopSound(); setPreview(true); }} disabled={session.busy || connecting}>Предпросмотр дизайна</button><button className="new-chat" onClick={reset} disabled={session.busy || connecting}><span aria-hidden="true">＋</span> Новый разговор</button></div>
    </header>
    <main>
      <div className="page-heading"><div><p className="eyebrow">SAQTA INSURANCE</p><h1>Давайте поговорим</h1><p className="muted">На русском или қазақша. Голосом или текстом.</p></div><span className="demo-label">Тестовая среда</span></div>
      <section className="chat" aria-label="Разговор с помощником">
        <div className="chat-header"><span>Разговор</span><span className="connection">{session.connection === 'online' ? 'Сервер подключён' : connecting ? 'Подключение' : 'Проверка интерфейса'}</span></div>
        <div className="history" ref={history} role="log" aria-label="История разговора" aria-live="polite" onScroll={e => { const el = e.currentTarget; stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60; }}>
          {!session.messages.length && <div className="empty"><div className="empty-icon"><MicIcon /></div><h2>С чего начнём?</h2><p>Нажмите микрофон или напишите свой вопрос.<br />Распознанную речь можно проверить перед отправкой.</p></div>}
          {session.messages.map(message => <article key={message.id} className={`message ${message.role}`}><span className="message-role">{message.role === 'user' ? 'Вы' : 'Saqta'}</span><p>{message.text}</p>{message.local && <small>Сохранено здесь · сервер не подключён</small>}{message.role === 'assistant' && <button className="text-button" disabled={listening || !voiceLanguage} onClick={() => speak(message.text)}>Озвучить ответ</button>}</article>)}
          {mic.partial && <div className="partial"><span>Распознавание…</span><p>{mic.partial}</p></div>}
          {session.busy && <p className="muted processing">Помощник обрабатывает вашу реплику…</p>}
        </div>
        <div className="controls">
          {(mic.error || session.error || audioError) && <div className="error" role="alert">{mic.error || session.error || audioError}</div>}
          <div className="voice-status" role="status"><span className={mic.phase === 'listening' ? 'recording-dot' : 'idle-dot'} />{status}</div>
          {session.closed ? <div className="conversation-ended"><p>История доступна выше. Для следующего вопроса начните новый разговор.</p><button className="primary" onClick={reset}>Начать новый разговор</button></div> : <>
          <div className="voice-controls">
            <label className="language">Язык речи<select value={language} onChange={e => setLanguage(e.target.value as Language)} disabled={listening || blocked || speaking}><option value="ru">Русский</option><option value="kk">Қазақша</option></select></label>
            <button className={`primary microphone ${listening ? 'recording' : ''}`} onClick={() => { if (listening) mic.stop(); else { stopSound(); mic.start(language); } }} disabled={blocked || !mic.supported || mic.phase === 'stopping'} aria-pressed={listening}><MicIcon stop={listening} />{listening ? 'Завершить реплику' : 'Начать говорить'}</button>
            {speaking && <button onClick={stopSound}>Остановить звук</button>}
          </div>
          {!mic.supported && <p className="notice">Этот браузер не поддерживает распознавание. Откройте в Chrome или введите текст.</p>}
          <form className="composer" onSubmit={e => { e.preventDefault(); send(); }}><label className="sr-only" htmlFor="message">Ваше сообщение</label><textarea id="message" ref={input} value={draft} maxLength={4000} disabled={blocked || listening || speaking} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} placeholder="Введите сообщение…" rows={2} /><button className="send" type="submit" disabled={!draft.trim() || blocked || listening || speaking} aria-label="Отправить сообщение"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true"><path d="m5 12 7-7 7 7M12 5v15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg></button></form>
          <p className="input-help">Enter — отправить · Shift + Enter — новая строка</p>
          </>}
        </div>
      </section>
      <div className="integration"><p>{session.connection === 'online' ? 'Операции выполняются в тестовых данных.' : 'Распознавание можно проверить сейчас. Для ответов помощника нужен сервер.'}</p>{session.connection !== 'online' && <button className="text-button" disabled={connecting || listening || session.busy} onClick={() => { stopSound(); void session.connect(); }}>{connecting ? 'Подключение…' : 'Подключить сервер'}</button>}</div>
      <TracePanel traces={session.traces} />
      <footer>Проверка голоса использует сервис браузера: аудио может обрабатываться онлайн. Поддержка қазақша зависит от сервиса и требует проверки.</footer>
    </main>
  </div>;
}
