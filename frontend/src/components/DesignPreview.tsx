import { useState } from 'react';

const states = {
  idle: { label: 'Начало', status: 'Готов к разговору', hint: 'Расскажите, с чем нужна помощь', action: 'Начать говорить' },
  listening: { label: 'Слушаю', status: 'Слушаю вас', hint: 'Говорите в обычном темпе', action: 'Завершить реплику' },
  processing: { label: 'Обработка', status: 'Обрабатываю реплику', hint: 'Учитываю контекст разговора', action: 'Обработка…' },
  speaking: { label: 'Ответ', status: 'Помощник отвечает', hint: 'Ответ также появится в истории', action: 'Остановить ответ' },
  microphone: { label: 'Ошибка микрофона', status: 'Микрофон недоступен', hint: 'Можно продолжить разговор текстом', action: 'Повторить попытку' },
  disconnected: { label: 'Нет связи', status: 'Соединение прервано', hint: 'История разговора сохранена на экране', action: 'Повторить подключение' },
  closed: { label: 'Разговор завершён', status: 'Разговор завершён', hint: 'Вы можете начать новый разговор', action: 'Начать новый разговор' },
};
type Phase = keyof typeof states;

export default function DesignPreview({ onExit }: { onExit: () => void }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [inspector, setInspector] = useState(false);
  const [language, setLanguage] = useState('ru');
  const state = states[phase];
  const error = phase === 'microphone' || phase === 'disconnected';
  function advance() {
    setPhase(phase === 'idle' || error ? 'listening' : phase === 'listening' ? 'processing' : 'idle');
  }
  return <div className="app design-preview">
    <header className="header"><div className="brand"><span className="brand-symbol">s.</span><span>Saqta<span className="brand-caption">Голосовой помощник</span></span></div><button onClick={onExit}>Вернуться к чату <span aria-hidden="true">↗</span></button></header>
    <div className="preview-toolbar"><div><span className="preview-badge">Предпросмотр дизайна</span><p>Тестовые данные · микрофон, звук и сервер не используются</p></div><label>Состояние<select value={phase} onChange={e => setPhase(e.target.value as Phase)}>{Object.entries(states).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select></label></div>
    <main className={`preview-workspace ${inspector ? 'inspector-open' : ''}`}>
      <div className="preview-chat-column">
        <div className="page-heading"><div><p className="eyebrow">ВАШ ПОМОЩНИК ПО СТРАХОВАНИЮ</p><h1>Давайте поговорим</h1><p className="muted">На русском или қазақша. В удобном вам темпе.</p></div></div>
        <section className="chat" aria-label="Предпросмотр разговора">
          <div className="chat-header"><span>Разговор <span className="chat-count">{phase === 'idle' ? '00' : '01'}</span></span><button className="inspect-toggle" aria-expanded={inspector} aria-controls="preview-inspector" onClick={() => setInspector(!inspector)}>Диагностика <span aria-hidden="true">{inspector ? '−' : '+'}</span></button></div>
          <div className="history preview-history" role="log" aria-label="Пример диалога">
            {phase === 'idle' ? <div className="empty"><span className="empty-kicker">Здравствуйте, это Saqta</span><h2>Чем можем помочь?</h2><p>Задайте вопрос о полисе, страховом случае<br />или условиях страхования.</p><div className="topic-labels"><span>Полисы</span><span>Страховые случаи</span><span>Консультации</span></div></div> : <>
              <div className="conversation-date">Пример разговора</div>
              <article className="message user"><span className="message-role">Вы <span>RU</span></span><p>{phase === 'closed' ? 'Спасибо, до свидания!' : 'Здравствуйте! Хочу узнать статус своего страхового случая.'}</p></article>
              {phase === 'closed' && <article className="message assistant"><span className="message-role">Saqta <span>Пример ответа</span></span><p>До свидания! Обращайтесь, если понадобится помощь.</p></article>}
              {phase === 'speaking' && <article className="message assistant"><span className="message-role">Saqta <span>Пример ответа</span></span><p>Подскажите номер вашего страхового случая.</p></article>}
              {phase === 'listening' && <div className="partial"><span>Пример распознавания</span><p>Номер моего страхового случая…</p></div>}
              {phase === 'processing' && <div className="processing-preview"><span className="typing-dots" aria-hidden="true"><i/><i/><i/></span> Помощник готовит ответ</div>}
            </>}
          </div>
          <div className={`controls preview-controls phase-${phase}`}>
            {error && <div className="error" role="alert"><strong>{phase === 'microphone' ? 'Не удалось получить доступ к микрофону' : 'Не удалось связаться с помощником'}</strong><p>{phase === 'microphone' ? 'Проверьте разрешение в браузере. Пока можно написать сообщение.' : 'Проверьте интернет. Последняя реплика не отправляется повторно автоматически.'}</p></div>}
            <div className="voice-stage"><div className="voice-glyph" aria-hidden="true">{[11,20,31,42,25,36,18].map((height, index) => <i key={index} style={{height, animationDelay: `${index * .12}s`}} />)}</div><div className="voice-status" role="status">{state.status}</div><p>{state.hint}</p></div>
            <div className="voice-controls"><label className="language">Язык речи<select value={language} disabled={phase === 'closed'} onChange={e => setLanguage(e.target.value)}><option value="ru">Русский</option><option value="kk">Қазақша</option></select></label><button className={`primary microphone ${phase === 'listening' ? 'recording' : ''}`} disabled={phase === 'processing'} onClick={advance}><span aria-hidden="true">{phase === 'listening' || phase === 'speaking' ? '■' : phase === 'closed' ? '＋' : '↗'}</span>{state.action}</button></div>
            {phase !== 'closed' && <><div className="composer preview-composer"><span>Введите сообщение…</span><button disabled aria-label="Отправка недоступна в предпросмотре">↑</button></div><p className="input-help">Поле ввода показано как образец · для ввода вернитесь к чату</p></>}
          </div>
        </section>
        <div className="preview-footnote"><span>Демонстрация интерфейса</span><span>Все данные на этом экране — примеры</span></div>
      </div>
      {inspector && <aside className="preview-inspector" id="preview-inspector" aria-label="Пример диагностики"><div className="inspector-title"><div><p className="eyebrow">ИНСПЕКТОР</p><h2>Диагностика</h2></div><button aria-label="Закрыть диагностику" onClick={() => setInspector(false)}>×</button></div><p className="sample-notice">Тестовые данные, не результат LLM</p>
        <section className="inspector-section"><h3>Выбранный сценарий</h3><span className="scenario-chip">{phase === 'closed' ? 'SYS_GOODBYE' : 'SC17'}</span><h4>{phase === 'closed' ? 'Завершение разговора' : 'Статус страхового случая'}</h4><p>{phase === 'closed' ? 'В примере клиент прощается с помощником.' : 'В примере клиент спрашивает о ходе рассмотрения заявления.'}</p></section>
        <section className="inspector-section"><h3>Контекст</h3><dl><dt>Язык</dt><dd>Русский · RU</dd><dt>Следующий шаг</dt><dd>{phase === 'closed' ? 'Новый разговор по желанию клиента' : 'Уточнение номера заявления'}</dd><dt>Уверенность</dt><dd>Не рассчитана</dd></dl></section>
        <section className="inspector-section"><h3>Параметры и действия</h3><p>{phase === 'closed' ? 'Сессия завершена. Действия не выполнялись.' : 'Номер заявления ещё не получен. Действия не выполнялись.'}</p></section>
        <section className="inspector-section"><h3>Время обработки</h3>{['Распознавание речи', 'Выбор сценария', 'Подготовка ответа', 'До начала звука'].map(label => <div className="timing-row" key={label}><span>{label}</span><span>—</span></div>)}<p className="timing-note">В предпросмотре время не измеряется.</p></section>
      </aside>}
    </main>
  </div>;
}
