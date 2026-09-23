import test from 'node:test';
import assert from 'node:assert/strict';
import { END_OF_SPEECH_MS, IDENTIFIER_END_OF_SPEECH_MS, VoiceActivityDetector, endOfSpeechForSlot } from './voiceActivity.ts';

function feed(detector: VoiceActivityDetector, from: number, to: number, rms: number) {
  let finished = false;
  for (let at = from; at <= to; at += 20) finished ||= detector.observe(rms, at);
  return finished;
}

test('quiet speech below the old fixed threshold is detected', () => {
  const detector = new VoiceActivityDetector(0);
  feed(detector, 0, 400, .0006);
  feed(detector, 420, 800, .006);
  assert.equal(detector.heardSpeech, true);
  assert.equal(detector.lastVoiceAt, 800);
});

test('a pause inside an identifier stays in the same turn; one second ends it', () => {
  const detector = new VoiceActivityDetector(0, .001, IDENTIFIER_END_OF_SPEECH_MS);
  feed(detector, 0, 300, .02);
  assert.equal(feed(detector, 320, 1120, .001), false);
  feed(detector, 1140, 1400, .02);
  assert.equal(feed(detector, 1420, 2380, .001), false);
  assert.equal(detector.observe(.001, 1400 + IDENTIFIER_END_OF_SPEECH_MS), true);
  assert.equal(detector.lastVoiceAt, 1400); // latency includes the endpoint wait
});

test('ordinary first question ends after half a second of silence', () => {
  const detector = new VoiceActivityDetector(0, .001);
  feed(detector, 0, 300, .02);
  assert.equal(feed(detector, 320, 780, .001), false);
  assert.equal(detector.observe(.001, 300 + END_OF_SPEECH_MS), true);
});

test('only requested identifiers use the longer pause', () => {
  assert.equal(endOfSpeechForSlot(null), END_OF_SPEECH_MS);
  assert.equal(endOfSpeechForSlot('city'), END_OF_SPEECH_MS);
  assert.equal(endOfSpeechForSlot('drivers_iin'), IDENTIFIER_END_OF_SPEECH_MS);
  assert.equal(endOfSpeechForSlot('phone'), IDENTIFIER_END_OF_SPEECH_MS);
});

test('continuous ambient noise above the old threshold is not a turn', () => {
  const detector = new VoiceActivityDetector(0);
  assert.equal(feed(detector, 0, 3000, .018), false);
  assert.equal(detector.heardSpeech, false);
  feed(detector, 3020, 3500, .075);
  assert.equal(detector.heardSpeech, true);
  assert.equal(feed(detector, 3520, 4500, .018), true);
});

test('resuming just before the silence deadline does not cut the new word', () => {
  const detector = new VoiceActivityDetector(0, .001, IDENTIFIER_END_OF_SPEECH_MS);
  feed(detector, 0, 200, .02);
  assert.equal(feed(detector, 220, 1140, .001), false);
  assert.equal(feed(detector, 1160, 1320, .02), false);
  assert.equal(detector.lastVoiceAt, 1320);
});

test('one short click does not trigger a request', () => {
  const detector = new VoiceActivityDetector(0, .001);
  feed(detector, 0, 300, .001);
  feed(detector, 320, 340, .1);
  feed(detector, 360, 2000, .001);
  assert.equal(detector.heardSpeech, false);
});

test('speech beginning during calibration is reconsidered', () => {
  const detector = new VoiceActivityDetector(0);
  feed(detector, 0, 80, .001);
  assert.equal(detector.ready, false);
  feed(detector, 100, 400, .008);
  assert.equal(detector.ready, true);
  assert.equal(detector.heardSpeech, true);
  assert.equal(detector.lastVoiceAt, 400);
});

test('long speech does not become the background; quieter endings are retained', () => {
  const detector = new VoiceActivityDetector(0, .002);
  feed(detector, 0, 5000, .05);
  assert.equal(detector.noiseFloor, .002);
  feed(detector, 5020, 5300, .004);
  assert.equal(detector.lastVoiceAt, 5300);
});

test('the ambient estimate follows gradual noise and gain changes', () => {
  const detector = new VoiceActivityDetector(0, .002);
  feed(detector, 0, 3000, .003);
  assert.ok(detector.noiseFloor > .0029);
  feed(detector, 3020, 6500, .001);
  assert.ok(detector.noiseFloor < .0011);
  assert.equal(detector.heardSpeech, false);
});

test('retaining the noise estimate avoids recalibration on the next turn', () => {
  const next = new VoiceActivityDetector(0, .004);
  assert.equal(next.ready, true);
  feed(next, 0, 100, .025);
  assert.equal(next.heardSpeech, true);
});
