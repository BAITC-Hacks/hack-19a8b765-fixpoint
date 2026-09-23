// Energy-based endpointing, not speech recognition. Audio is recorded throughout
// calibration, so the detector never trims the beginning of the recording.
export const END_OF_SPEECH_MS = 500;
export const IDENTIFIER_END_OF_SPEECH_MS = 1000;
const IDENTIFIER_SLOTS = new Set(['iin', 'drivers_iin', 'new_driver_iin', 'phone', 'policy_number', 'claim_number']);
export function endOfSpeechForSlot(waitingSlot: string | null) {
  return waitingSlot && IDENTIFIER_SLOTS.has(waitingSlot) ? IDENTIFIER_END_OF_SPEECH_MS : END_OF_SPEECH_MS;
}
export const LEVEL_INTERVAL_MS = 20;
const CALIBRATION_MS = 300;
const MIN_SPEECH_MS = 80;
type Sample = { rms: number; at: number };

function noiseLevel(samples: Sample[]) {
  const levels = samples.map(sample => sample.rms).sort((a, b) => a - b);
  return Math.max(.0001, levels[Math.floor((levels.length - 1) * .2)] ?? .0001);
}

export class VoiceActivityDetector {
  private calibration: Sample[] = [];
  private ambient: Sample[] = [];
  private candidateAt: number | null = null;
  private speaking = false;
  private initialized = false;
  private startedAt: number;
  private endOfSpeechMs: number;
  noiseFloor = .0001;
  heardSpeech = false;
  lastVoiceAt: number;

  constructor(startedAt: number, noiseFloor?: number, endOfSpeechMs = END_OF_SPEECH_MS) {
    this.startedAt = startedAt;
    this.endOfSpeechMs = endOfSpeechMs;
    this.lastVoiceAt = startedAt;
    if (noiseFloor !== undefined) {
      this.noiseFloor = Math.max(.0001, noiseFloor);
      this.initialized = true;
    }
  }

  get startThreshold() { return Math.max(.003, this.noiseFloor * 3); }
  get continueThreshold() { return Math.max(.002, this.noiseFloor * 1.7); }
  get ready() { return this.initialized; }

  observe(rms: number, at: number) {
    const sample = { rms: Math.max(0, Number.isFinite(rms) ? rms : 0), at };
    if (!this.initialized) {
      this.calibration.push(sample);
      if (at - this.startedAt < CALIBRATION_MS) return false;
      this.noiseFloor = noiseLevel(this.calibration);
      this.initialized = true;
      // Reconsider early frames after calibration instead of discarding them.
      for (const early of this.calibration) this.detect(early);
      this.calibration = [];
    } else {
      this.detect(sample);
    }
    // A new onset near the deadline gets time to pass the short-click filter.
    return this.heardSpeech && this.candidateAt === null && at - this.lastVoiceAt >= this.endOfSpeechMs;
  }

  private detect(sample: Sample) {
    const threshold = this.speaking ? this.continueThreshold : this.startThreshold;
    if (sample.rms >= threshold) {
      this.candidateAt ??= sample.at;
      if (this.speaking || sample.at - this.candidateAt >= MIN_SPEECH_MS) {
        this.heardSpeech = true;
        this.speaking = true;
        this.lastVoiceAt = sample.at;
      }
      return;
    }
    this.speaking = false;
    this.candidateAt = null;
    // Exclude speech from the ambient estimate so long utterances cannot
    // raise their own threshold. A recent window follows ambient/gain changes.
    this.ambient.push(sample);
    this.ambient = this.ambient.filter(frame => sample.at - frame.at <= 2000);
    const target = noiseLevel(this.ambient);
    this.noiseFloor += (target - this.noiseFloor) * .1;
  }
}
