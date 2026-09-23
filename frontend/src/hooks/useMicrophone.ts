import { useEffect, useRef, useState } from 'react';
import { LEVEL_INTERVAL_MS, VoiceActivityDetector } from '../voiceActivity';

type Input = { stream: MediaStream; context: AudioContext; analyser: AnalyserNode; noiseFloor?: number };
type Recording = { recorder: MediaRecorder; interval: number; ready: (ok: boolean) => void };

export function useMicrophone(onAudio: (audio: Blob, endedAt: number) => void) {
  const [phase, setPhase] = useState<'idle' | 'starting' | 'listening' | 'stopping'>('idle');
  const [error, setError] = useState('');
  const analyserRef = useRef<AnalyserNode | null>(null);
  const callback = useRef(onAudio); callback.current = onAudio;
  const input = useRef<Input | null>(null);
  const active = useRef<Recording | null>(null);
  const generation = useRef(0);
  const starting = useRef<Promise<boolean> | null>(null);

  function release() {
    analyserRef.current = null;
    generation.current++;
    starting.current = null;
    const current = active.current;
    active.current = null;
    if (current) {
      window.clearInterval(current.interval);
      current.ready(false);
      current.recorder.onstart = null;
      current.recorder.onstop = null;
      current.recorder.onerror = null;
      if (current.recorder.state !== 'inactive') current.recorder.stop();
    }
    const device = input.current;
    input.current = null;
    device?.stream.getTracks().forEach(track => track.stop());
    if (device) void device.context.close();
  }

  function abort() { release(); setPhase('idle'); }
  useEffect(() => () => release(), []);

  function start(endOfSpeechMs?: number): Promise<boolean> {
    if (starting.current) return starting.current;
    if (active.current) return Promise.resolve(active.current.recorder.state === 'recording');
    const epoch = generation.current;
    const attempt = begin(epoch, endOfSpeechMs);
    starting.current = attempt;
    void attempt.finally(() => { if (starting.current === attempt) starting.current = null; });
    return attempt;
  }

  async function begin(epoch: number, endOfSpeechMs?: number) {
    setError('');
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !window.AudioContext) {
      setError('Запись недоступна в этом браузере. Откройте сайт на localhost или через HTTPS.');
      return false;
    }
    setPhase('starting');
    let acquired: MediaStream | null = null;
    let createdContext: AudioContext | null = null;
    try {
      if (!input.current) {
        acquired = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        if (epoch !== generation.current) { acquired.getTracks().forEach(track => track.stop()); return false; }
        createdContext = new AudioContext();
        const analyser = createdContext.createAnalyser();
        analyserRef.current = analyser;
        analyser.fftSize = 2048;
        createdContext.createMediaStreamSource(acquired).connect(analyser);
        input.current = { stream: acquired, context: createdContext, analyser };
      }
      const device = input.current;
      await device.context.resume();
      if (epoch !== generation.current) return false;
      if (device.stream.getAudioTracks().every(track => track.readyState === 'ended')) throw new Error('device-ended');
      const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported(t));
      if (!type) throw new Error('format');
      const recorder = new MediaRecorder(device.stream, { mimeType: type });
      const samples = new Float32Array(device.analyser.fftSize);
      const chunks: BlobPart[] = [];
      const started = performance.now();
      const detector = new VoiceActivityDetector(started, device.noiseFloor, endOfSpeechMs);
      let ready!: (ok: boolean) => void;
      const readiness = new Promise<boolean>(resolve => { ready = resolve; });
      const recording: Recording = { recorder, interval: 0, ready };
      active.current = recording;
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        if (active.current !== recording || epoch !== generation.current) return;
        active.current = null;
        window.clearInterval(recording.interval);
        ready(false);
        // Keep the device open between turns. Recording is off during TTS;
        // abort/end/unmount releases the actual microphone and AudioContext.
        device.noiseFloor = detector.noiseFloor;
        setPhase('idle');
        if (detector.heardSpeech && chunks.length) callback.current(new Blob(chunks, { type: recorder.mimeType }), detector.lastVoiceAt);
        else setError('Речь не обнаружена. Начните разговор снова.');
      };
      recorder.onerror = () => {
        if (epoch !== generation.current) return;
        setError('Ошибка записи. Проверьте микрофон и попробуйте ещё раз.');
        abort();
      };
      recorder.onstart = () => {
        if (active.current !== recording || epoch !== generation.current) return;
        let listening = false;
        const announceReady = () => {
          if (!listening && detector.ready) {
            listening = true;
            setPhase('listening');
            ready(true);
          }
        };
        announceReady();
        recording.interval = window.setInterval(() => {
          device.analyser.getFloatTimeDomainData(samples);
          let energy = 0;
          for (const value of samples) energy += value * value;
          const now = performance.now();
          const finished = detector.observe(Math.sqrt(energy / samples.length), now);
          announceReady();
          if (finished || now - started >= 30000) {
            window.clearInterval(recording.interval);
            setPhase('stopping');
            if (recorder.state === 'recording') recorder.stop();
          }
        }, LEVEL_INTERVAL_MS);
      };
      recorder.start(100);
      return await readiness;
    } catch (exc) {
      if (epoch !== generation.current) return false;
      if (!input.current) {
        acquired?.getTracks().forEach(track => track.stop());
        if (createdContext) void createdContext.close();
      }
      release();
      setPhase('idle');
      const name = exc instanceof DOMException ? exc.name : '';
      setError(name === 'NotAllowedError' ? 'Доступ к микрофону запрещён. Разрешите его в настройках браузера.' :
        name === 'NotFoundError' ? 'Микрофон не найден. Подключите устройство и попробуйте снова.' :
        'Не удалось начать запись. Проверьте микрофон и поддержку формата.');
      return false;
    }
  }
  return { phase, error, analyserRef, supported: !!navigator.mediaDevices?.getUserMedia && !!window.MediaRecorder, start, abort, clearError: () => setError('') };
}
