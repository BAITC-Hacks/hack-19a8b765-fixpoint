import { useEffect, useRef, useState } from 'react';

export function useMicrophone(onAudio: (audio: Blob, endedAt: number) => void) {
  const [phase, setPhase] = useState<'idle' | 'starting' | 'listening' | 'stopping'>('idle');
  const [error, setError] = useState('');
  const callback = useRef(onAudio); callback.current = onAudio;
  const active = useRef<{ recorder: MediaRecorder; stream: MediaStream; context: AudioContext; interval: number } | null>(null);

  function abort() {
    const current = active.current;
    active.current = null;
    if (current) {
      window.clearInterval(current.interval);
      current.recorder.onstop = null;
      if (current.recorder.state !== 'inactive') current.recorder.stop();
      current.stream.getTracks().forEach(track => track.stop());
      void current.context.close();
    }
    setPhase('idle');
  }
  useEffect(() => () => {
    const current = active.current;
    active.current = null;
    if (current) {
      window.clearInterval(current.interval);
      current.recorder.onstop = null;
      if (current.recorder.state !== 'inactive') current.recorder.stop();
      current.stream.getTracks().forEach(track => track.stop());
      void current.context.close();
    }
  }, []);

  async function start() {
    if (active.current) return true;
    setError('');
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !window.AudioContext) {
      setError('Запись недоступна в этом браузере. Откройте сайт на localhost или через HTTPS.');
      return false;
    }
    setPhase('starting');
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported(t));
      if (!type) throw new Error('format');
      const recorder = new MediaRecorder(stream, { mimeType: type });
      const context = new AudioContext();
      await context.resume();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      const chunks: BlobPart[] = [];
      let heard = false;
      let lastVoice = performance.now();
      const started = performance.now();
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        const current = active.current;
        if (!current || current.recorder !== recorder) return;
        active.current = null;
        window.clearInterval(current.interval);
        stream?.getTracks().forEach(track => track.stop());
        void context.close();
        setPhase('idle');
        if (heard && chunks.length) callback.current(new Blob(chunks, { type: recorder.mimeType }), lastVoice);
        else setError('Речь не обнаружена. Начните разговор снова.');
      };
      recorder.onerror = () => { setError('Ошибка записи. Проверьте микрофон и попробуйте ещё раз.'); abort(); };
      recorder.start(250);
      const interval = window.setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        let energy = 0;
        for (const value of samples) energy += value * value;
        const rms = Math.sqrt(energy / samples.length);
        const now = performance.now();
        if (rms > .014) { heard = true; lastVoice = now; }
        if ((heard && now - lastVoice > 500 && now - started > 550) || now - started > 30000) {
          setPhase('stopping');
          if (recorder.state === 'recording') recorder.stop();
        }
      }, 100);
      active.current = { recorder, stream, context, interval };
      setPhase('listening');
      return true;
    } catch (exc) {
      stream?.getTracks().forEach(track => track.stop());
      setPhase('idle');
      const name = exc instanceof DOMException ? exc.name : '';
      setError(name === 'NotAllowedError' ? 'Доступ к микрофону запрещён. Разрешите его в настройках браузера.' :
        name === 'NotFoundError' ? 'Микрофон не найден. Подключите устройство и попробуйте снова.' :
        'Не удалось начать запись. Проверьте микрофон и поддержку формата.');
      return false;
    }
  }
  return { phase, error, supported: !!navigator.mediaDevices?.getUserMedia && !!window.MediaRecorder, start, abort, clearError: () => setError('') };
}
