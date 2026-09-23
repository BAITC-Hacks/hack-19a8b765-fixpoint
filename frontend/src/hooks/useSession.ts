import { useEffect, useReducer, useRef, useState } from 'react';
import { initialState, sessionReducer } from '../state/sessionReducer';
import type { Language, ServerEvent } from '../types';

export function useSession() {
  const [state, dispatch] = useReducer(sessionReducer, initialState);
  const [connection, setConnection] = useState<'local' | 'connecting' | 'online'>('local');
  const socket = useRef<WebSocket | null>(null);
  const session = useRef<string | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const request = useRef<AbortController | null>(null);
  function disconnect() {
    generation.current++; request.current?.abort(); request.current = null;
    clearTimeout(timeout.current); pending.current = false;
    const previous = socket.current; socket.current = null; previous?.close();
    const id = session.current; session.current = null;
    if (id) void fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE', keepalive: true }).catch(() => {});
  }
  useEffect(() => () => disconnect(), []);
  async function connect() {
    if (pending.current || socket.current) return;
    disconnect();
    const epoch = ++generation.current; pending.current = true; setConnection('connecting');
    dispatch({ type: 'error', error: '' });
    const controller = new AbortController(); request.current = controller;
    const connectTimer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch('/api/sessions', { method: 'POST', signal: controller.signal });
      if (!response.ok) throw new Error();
      const data: unknown = await response.json();
      if (!data || typeof data !== 'object' || !('session_id' in data) || typeof data.session_id !== 'string') throw new Error();
      if (epoch !== generation.current) { void fetch(`/api/sessions/${encodeURIComponent(data.session_id)}`, { method: 'DELETE' }).catch(() => {}); return; }
      session.current = data.session_id;
      const url = new URL(`/api/sessions/${encodeURIComponent(data.session_id)}/stream`, location.href);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(url); socket.current = ws;
      timeout.current = setTimeout(() => { if (socket.current === ws && connection !== 'online') ws.close(); }, 8000);
      ws.onopen = () => {
        if (epoch !== generation.current) return;
        clearTimeout(timeout.current); pending.current = false; setConnection('online'); dispatch({ type: 'reset' });
      };
      ws.onmessage = event => {
        if (epoch !== generation.current || typeof event.data !== 'string') return;
        try {
          const value = JSON.parse(event.data) as ServerEvent;
          if (!value || typeof value.type !== 'string' || !Number.isInteger(value.event_id) || !value.payload || typeof value.payload !== 'object') return;
          dispatch({ type: 'event', event: value });
          if (value.type === 'turn.completed' || value.type === 'error') { clearTimeout(timeout.current); pending.current = false; }
        } catch { dispatch({ type: 'error', error: 'Неверный формат ответа сервера.' }); ws.close(); }
      };
      ws.onclose = () => {
        if (epoch !== generation.current) return;
        clearTimeout(timeout.current); socket.current = null; pending.current = false; setConnection('local');
        dispatch({ type: 'error', error: 'Соединение закрыто. Последняя реплика не отправляется повторно. Можно начать новую сессию.' });
      };
    } catch {
      if (epoch !== generation.current) return;
      pending.current = false; setConnection('local');
      dispatch({ type: 'error', error: 'Сервер помощника недоступен. Микрофон и ввод текста можно проверить отдельно.' });
    } finally { clearTimeout(connectTimer); }
  }
  function send(text: string, language: Language) {
    if (!text.trim() || text.length > 4000 || pending.current || state.closed) return false;
    const id = crypto.randomUUID(); const ws = socket.current;
    const online = ws?.readyState === WebSocket.OPEN;
    if (online) {
      pending.current = true;
      try { ws.send(JSON.stringify({ type: 'text.submit', request_id: id, payload: { text: text.trim(), language } })); }
      catch { pending.current = false; dispatch({ type: 'error', error: 'Не удалось отправить сообщение.' }); return false; }
      timeout.current = setTimeout(() => {
        // Do not unlock and resend an operation whose result is unknown.
        dispatch({ type: 'error', error: 'Ответ задерживается. Результат операции неизвестен; повторная отправка заблокирована до завершения или новой сессии.' });
      }, 30000);
    }
    dispatch({ type: 'user', message: { id, role: 'user', text: text.trim(), local: !online }, online: !!online });
    return true;
  }
  function reset() { disconnect(); setConnection('local'); dispatch({ type: 'reset' }); }
  return { ...state, connection, connect, send, reset };
}
