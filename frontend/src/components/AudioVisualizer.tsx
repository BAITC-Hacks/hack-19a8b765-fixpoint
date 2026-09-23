import { useEffect, useRef, type RefObject } from 'react';

export default function AudioVisualizer({ analyserRef, listening }: { analyserRef: RefObject<AnalyserNode | null>; listening: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    let frame = 0;
    let samples = new Uint8Array(0);
    const heights = Array<number>(40).fill(4);
    function draw() {
      if (!canvas || !context) return;
      const analyser = listening ? analyserRef.current : null;
      if (analyser) {
        if (samples.length !== analyser.frequencyBinCount) samples = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(samples);
      }
      context.clearRect(0, 0, 320, 80);
      context.fillStyle = '#0e7453';
      for (let i = 0; i < heights.length; i++) {
        const bin = Math.floor(2 + Math.abs(i - 19.5) * 3);
        const target = analyser ? 4 + (samples[bin] / 255) * 68 : 4;
        heights[i] += (target - heights[i]) * .25;
        context.beginPath();
        context.roundRect(i * 8 + 1, (80 - heights[i]) / 2, 4, heights[i], 2);
        context.fill();
      }
      frame = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(frame);
  }, [analyserRef, listening]);
  return <canvas ref={canvasRef} className="audio-visualizer" width={320} height={80} aria-hidden="true" />;
}
