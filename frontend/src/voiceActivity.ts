// Energy-based endpointing, not speech recognition. Audio is recorded throughout
// calibration, so the detector never trims the beginning of the recording.
export const END_OF_SPEECH_MS = 500;
export const IDENTIFIER_END_OF_SPEECH_MS = 1000;
const IDENTIFIER_SLOTS = new Set(['iin', 'drivers_iin', 'new_driver_iin', 'phone',
  'vehicle_plate', 'culprit_vehicle_plate', 'policy_number', 'claim_number']);
export function endOfSpeechForSlot(waitingSlot: string | null) {
  return waitingSlot && IDENTIFIER_SLOTS.has(waitingSlot) ? IDENTIFIER_END_OF_SPEECH_MS : END_OF_SPEECH_MS;
}
export const LEVEL_INTERVAL_MS = 20;
const CALIBRATION_MS = 300;
const MIN_SPEECH_MS = 80;
const STEADY_WINDOW_MS = 500;
const WEAK_TAIL_MS = 1200;
const IDENTIFIER_WEAK_TAIL_MS = 2000;
type Sample = { rms: number; at: number };

function noiseLevel(samples: Sample[]) {
  const levels = samples.map(sample => sample.rms).sort((a, b) => a - b);
  return Math.max(.0001, levels[Math.floor((levels.length - 1) * .2)] ?? .0001);
}

export class VoiceActivityDetector {
  private calibration: Sample[] = [];
  private ambient: Sample[] = [];
  private candidateAt: number | null = null;
  private weakSince: number | null = null;
  private recent: Sample[] = [];
  private speechPeak = 0;
  private previousRms: number | null = null;
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
    const levelChange = this.previousRms === null ? 0 : Math.abs(sample.rms - this.previousRms);
    this.previousRms = sample.rms;
    const threshold = this.speaking ? this.continueThreshold : this.startThreshold;
    if (sample.rms >= threshold) {
      this.recent.push(sample);
      this.recent = this.recent.filter(frame => sample.at - frame.at <= STEADY_WINDOW_MS);
      this.speechPeak = Math.max(sample.rms, this.speechPeak * .9998);
      const levels = this.recent.map(frame => frame.rms);
      const steady = this.recent.length >= STEADY_WINDOW_MS / LEVEL_INTERVAL_MS
        && Math.max(...levels) - Math.min(...levels) <= Math.max(.0004, sample.rms * .18);
      const modulated = levelChange >= Math.max(.0008, sample.rms * .22, this.speechPeak * .025);
      const weak = this.speaking && !modulated
        && (sample.rms < Math.max(this.startThreshold, this.speechPeak * .35)
        || (steady && sample.rms < this.speechPeak * .9));
      if (weak) {
        this.weakSince ??= sample.at;
        const maxTail = this.endOfSpeechMs >= IDENTIFIER_END_OF_SPEECH_MS
          ? IDENTIFIER_WEAK_TAIL_MS : WEAK_TAIL_MS;
        if (sample.at - this.weakSince >= maxTail) {
          // Sustained low or flat energy is background, even when it remains
          // above the continuation threshold. Backdate the last speech frame.
          this.lastVoiceAt = this.weakSince;
          this.speaking = false;
          this.candidateAt = null;
          this.updateAmbient(sample);
          return;
        }
      } else {
        this.weakSince = null;
      }
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
    this.weakSince = null;
    this.recent = [];
    this.updateAmbient(sample);
  }

  private updateAmbient(sample: Sample) {
    // Exclude speech from the ambient estimate so long utterances cannot
    // raise their own threshold. A recent window follows ambient/gain changes.
    this.ambient.push(sample);
    this.ambient = this.ambient.filter(frame => sample.at - frame.at <= 2000);
    const target = noiseLevel(this.ambient);
    this.noiseFloor += (target - this.noiseFloor) * .1;
  }
}
