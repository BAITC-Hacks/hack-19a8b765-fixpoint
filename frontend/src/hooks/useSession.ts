import { useEffect, useReducer, useRef, useState } from 'react';
import { initialState, sessionReducer } from '../state/sessionReducer';
import type { Language, ServerEvent } from '../types';

export type CompletedAudio = { turnId: string; segments: string[]; mime: string; failed: boolean; endedAt: number; error?: string };

export function useSession() {
  const [state, dispatch] = useReducer(sessionReducer, initialState);
  const [connection, setConnection] = useState<'local' | 'connecting' | 'online'>('local');
  const [completedAudio, setCompletedAudio] = useState<CompletedAudio | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const session = useRef<string | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const request = useRef<AbortController | null>(null);
  const segments = useRef<string[]>([]);
  const audioMime = useRef('audio/mpeg');
  const audioFailed = useRef(false);
  const turnError = useRef('');
  const endedAt = useRef(0);

  function disconnect() {
    generation.current++;
    request.current?.abort();
    request.current = null;
    clearTimeout(timer.current);
    pending.current = false;
    const old = socket.current; socket.current = null; old?.close();
    const id = session.current; session.current = null;
    if (id) void fetch(`/api/sessions/${encodeURIComponent(id)}/close`, { method: 'POST', keepalive: true })
      .then(response => { if (!response.ok) throw new Error('archive'); })
      .catch(() => dispatch({ type: 'error', error: 'Не удалось подтвердить закрытие сессии. Проверьте сохранённые разговоры в диагностике.' }));
  }
  useEffect(() => () => disconnect(), []);

  async function connect() {
    if (pending.current || socket.current) return false;
    disconnect();
    const epoch = ++generation.current;
    pending.current = true;
    setConnection('connecting');
    dispatch({ type: 'error', error: '' });
    const controller = new AbortController();
    request.current = controller;
    const connectTimer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch('/api/sessions', { method: 'POST', signal: controller.signal });
      if (!response.ok) throw new Error('Сервер не создаёт сессию.');
      const data = await response.json() as { session_id?: string };
      if (!data.session_id) throw new Error('Некорректный ответ сервера.');
      if (epoch !== generation.current) return false;
      session.current = data.session_id;
      const url = new URL(`/api/sessions/${encodeURIComponent(data.session_id)}/stream`, location.href);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(url);
      socket.current = ws;
      return await new Promise<boolean>(resolve => {
        timer.current = setTimeout(() => { ws.close(); resolve(false); }, 8000);
        ws.onopen = () => {
          if (epoch !== generation.current) { resolve(false); return; }
          clearTimeout(timer.current);
          pending.current = false;
          setConnection('online');
          dispatch({ type: 'reset' });
          resolve(true);
        };
        ws.onmessage = message => {
          if (epoch !== generation.current || typeof message.data !== 'string') return;
          try {
            const event = JSON.parse(message.data) as ServerEvent;
            if (!event || typeof event.type !== 'string' || !Number.isInteger(event.event_id) || !event.payload) return;
            dispatch({ type: 'event', event });
            if (event.type === 'audio.segment' && typeof event.payload.audio_base64 === 'string') {
              segments.current.push(event.payload.audio_base64);
              if (typeof event.payload.mime === 'string') audioMime.current = event.payload.mime;
            }
            if (event.type === 'turn.status' && event.payload.code === 'tts_unavailable') audioFailed.current = true;
            if (event.type === 'error' && typeof event.payload.message === 'string') turnError.current = event.payload.message;
            if (event.type === 'turn.completed') {
              clearTimeout(timer.current);
              pending.current = false;
              setCompletedAudio({ turnId: event.turn_id ?? String(event.event_id), segments: segments.current, mime: audioMime.current, failed: audioFailed.current, endedAt: endedAt.current, error: turnError.current });
              segments.current = [];
              audioFailed.current = false;
              turnError.current = '';
            }
            if (event.type === 'error') { clearTimeout(timer.current); pending.current = false; }
          } catch {
            dispatch({ type: 'error', error: 'Неверный формат ответа сервера.' });
            ws.close();
          }
        };
        ws.onclose = () => {
          if (epoch !== generation.current) return;
          clearTimeout(timer.current);
          socket.current = null;
          pending.current = false;
          setConnection('local');
          dispatch({ type: 'error', error: 'Соединение потеряно. Результат последней операции неизвестен; начните новый разговор.' });
          resolve(false);
        };
      });
    } catch {
      if (epoch === generation.current) {
        pending.current = false;
        setConnection('local');
        dispatch({ type: 'error', error: 'Сервер недоступен. Проверьте, что FastAPI запущен.' });
      }
      return false;
    } finally { clearTimeout(connectTimer); }
  }

  function send(text: string, language: Language) {
    const ws = socket.current;
    if (!text.trim() || text.length > 4000 || pending.current || state.closed || ws?.readyState !== WebSocket.OPEN) return false;
    const id = crypto.randomUUID();
    pending.current = true;
    segments.current = []; audioMime.current = 'audio/mpeg'; audioFailed.current = false; turnError.current = '';
    try { ws.send(JSON.stringify({ type: 'text.submit', request_id: id, payload: { text: text.trim(), language, speak: false } })); }
    catch { pending.current = false; dispatch({ type: 'error', error: 'Не удалось отправить сообщение.' }); return false; }
    dispatch({ type: 'user', message: { id, role: 'user', text: text.trim() } });
    timer.current = setTimeout(() => dispatch({ type: 'error', error: 'Ответ задерживается. Не повторяйте операцию до выяснения результата.' }), 45000);
    return true;
  }

  async function sendAudio(blob: Blob, language: Language, speechEndedAt: number) {
    const ws = socket.current;
    if (pending.current || state.closed || ws?.readyState !== WebSocket.OPEN || blob.size === 0 || blob.size > 12 * 1024 * 1024) return false;
    const bytes = new Uint8Array(await blob.arrayBuffer());
    if (pending.current || ws.readyState !== WebSocket.OPEN) return false;
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    const id = crypto.randomUUID();
    pending.current = true;
    endedAt.current = speechEndedAt;
    segments.current = []; audioMime.current = 'audio/mpeg'; audioFailed.current = false; turnError.current = '';
    try {
      ws.send(JSON.stringify({ type: 'audio.start', payload: { mime: blob.type, language } }));
      ws.send(JSON.stringify({ type: 'audio.chunk', payload: { data: btoa(binary) } }));
      ws.send(JSON.stringify({ type: 'audio.end', request_id: id, payload: { speak: true } }));
      timer.current = setTimeout(() => dispatch({ type: 'error', error: 'Ответ задерживается. Результат операции неизвестен.' }), 60000);
      return true;
    } catch {
      pending.current = false;
      dispatch({ type: 'error', error: 'Не удалось отправить запись. Проверьте соединение.' });
      return false;
    }
  }

  function reset() {
    disconnect();
    setConnection('local');
    setCompletedAudio(null);
    dispatch({ type: 'reset' });
  }
  function end() { disconnect(); setConnection('local'); }
  function reportPlayback(ttfaMs: number, turnId: string) {
    if (socket.current?.readyState === WebSocket.OPEN)
      socket.current.send(JSON.stringify({ type: 'playback.started', payload: { ttfa_ms: ttfaMs, turn_id: turnId } }));
  }
  return { ...state, connection, completedAudio, connect, send, sendAudio, reportPlayback, end, reset };
}
