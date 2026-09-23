import { useEffect, useRef, useState } from 'react';
import type { Language } from '../types';

type Result = { isFinal: boolean; 0: { transcript: string } };
interface Recognition {
  lang: string; continuous: boolean; interimResults: boolean;
  onstart: (() => void) | null; onend: (() => void) | null;
  onresult: ((event: { results: ArrayLike<Result> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  start(): void; stop(): void; abort(): void;
}
type SpeechWindow = Window & { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
const errors: Record<string, string> = {
  'not-allowed': 'Доступ к микрофону запрещён. Разрешите его в настройках сайта или введите текст.',
  'service-not-allowed': 'Распознавание запрещено браузером. Используйте текстовый ввод.',
  'audio-capture': 'Микрофон недоступен. Проверьте подключение и доступ к устройству.',
  'no-speech': 'Речь не обнаружена. Нажмите микрофон и повторите.',
  network: 'Сервис распознавания недоступен. Проверьте интернет или введите текст.',
  'language-not-supported': 'Этот язык не поддерживается сервисом браузера. Используйте текстовый ввод.',
};

export function useMicrophone(onText: (text: string) => void) {
  const [phase, setPhase] = useState<'idle' | 'starting' | 'listening' | 'stopping'>('idle');
  const [partial, setPartial] = useState('');
  const [error, setError] = useState('');
  const ref = useRef<Recognition | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const callback = useRef(onText); callback.current = onText;
  const Speech = (window as SpeechWindow).SpeechRecognition ?? (window as SpeechWindow).webkitSpeechRecognition;

  function abort() {
    clearTimeout(timer.current);
    const previous = ref.current; ref.current = null;
    if (previous) { previous.onend = null; previous.onresult = null; previous.onerror = null; previous.onstart = null; previous.abort(); }
    setPhase('idle'); setPartial('');
  }
  useEffect(() => () => {
    clearTimeout(timer.current);
    const current = ref.current; ref.current = null;
    if (current) { current.onend = null; current.onresult = null; current.onerror = null; current.onstart = null; current.abort(); }
  }, []);
  function start(language: Language) {
    if (ref.current) return;
    setError('');
    if (!Speech || !window.isSecureContext) { setError('Распознавание недоступно здесь. Откройте localhost в Chrome или используйте текст.'); return; }
    const recognition = new Speech(); ref.current = recognition;
    recognition.lang = language === 'kk' ? 'kk-KZ' : 'ru-RU';
    recognition.continuous = false; recognition.interimResults = true;
    let final = ''; let failed = false;
    setPhase('starting'); setPartial('');
    recognition.onstart = () => { if (ref.current === recognition) setPhase('listening'); };
    recognition.onresult = event => {
      if (ref.current !== recognition) return;
      const results = Array.from(event.results);
      final = results.filter(r => r.isFinal).map(r => r[0].transcript).join(' ').trim();
      setPartial(results.map(r => r[0].transcript).join(' '));
    };
    recognition.onerror = event => {
      if (ref.current !== recognition) return;
      failed = true;
      setError(errors[event.error] ?? 'Не удалось распознать речь. Повторите или введите текст.');
    };
    recognition.onend = () => {
      if (ref.current !== recognition) return;
      clearTimeout(timer.current); ref.current = null; setPhase('idle'); setPartial('');
      if (final) callback.current(final);
      else if (!failed) setError('Речь не распознана. Попробуйте ещё раз.');
    };
    try {
      recognition.start();
      timer.current = setTimeout(() => { if (ref.current === recognition) { setPhase('stopping'); recognition.stop(); } }, 60000);
    } catch { ref.current = null; setPhase('idle'); setError('Не удалось запустить распознавание. Повторите попытку.'); }
  }
  function stop() { if (ref.current) { setPhase('stopping'); ref.current.stop(); } }
  return { phase, partial, error, supported: !!Speech && window.isSecureContext, start, stop, abort, clearError: () => setError('') };
}
