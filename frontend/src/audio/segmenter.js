// Turns Silero VAD events into the hub's segment messages (hard rule 9). No browser APIs, so it
// can be unit-tested.
//
// - A segment starts when the VAD hears speech. The audio just before it (the pre-roll) goes
//   first, so the first syllable isn't clipped.
// - Every frame inside a segment is sent as 16-bit PCM, including the VAD's own pause detection
//   (`redemptionMs`, about 0.7 s of silence) before it decides the speech has ended.
// - A segment ends when the VAD says so, or at the 15 s cap, where a new one starts at once.
// - `pause_s` is the silence before a segment; the server starts a new bubble after 2 s.

import { floatTo16BitPcm } from "./pcm.js";

export const SAMPLE_RATE = 16000;

export class Segmenter {
  constructor({ send, sendAudio, preRollMs = 300, capS = 15, redemptionMs = 700, now }) {
    this.send = send; // (message object) => void
    this.sendAudio = sendAudio; // (ArrayBuffer of 16-bit PCM) => void
    this.preRollMs = preRollMs;
    this.capSamples = capS * SAMPLE_RATE;
    this.redemptionS = redemptionMs / 1000;
    this.now = now || (() => performance.now() / 1000);
    this.inSegment = false;
    this.segmentSamples = 0;
    this.preRoll = [];
    this.preRollSamples = 0;
    this.lastSpeechEndAt = null; // when the last segment's speech ended
  }

  onFrame(frame) {
    if (!this.inSegment) {
      this.preRoll.push(frame);
      this.preRollSamples += frame.length;
      const keep = (this.preRollMs / 1000) * SAMPLE_RATE;
      while (this.preRoll.length > 1 && this.preRollSamples - this.preRoll[0].length >= keep) {
        this.preRollSamples -= this.preRoll.shift().length;
      }
      return;
    }
    this.#send(frame);
    if (this.segmentSamples >= this.capSamples) {
      this.send({ type: "segment_end" });
      this.send({ type: "segment_start", pause_s: 0 });
      this.segmentSamples = 0;
    }
  }

  onSpeechStart() {
    if (this.inSegment) return;
    const pause = this.lastSpeechEndAt === null ? 99 : Math.max(0, this.now() - this.lastSpeechEndAt);
    this.send({ type: "segment_start", pause_s: Math.round(pause * 100) / 100 });
    this.inSegment = true;
    this.segmentSamples = 0;
    for (const frame of this.preRoll) this.#send(frame);
    this.preRoll = [];
    this.preRollSamples = 0;
  }

  // The VAD heard `redemptionMs` of silence (onSpeechEnd), or the speech was too short to count
  // (onVADMisfire): either way the segment is over.
  onSpeechEnd() {
    if (!this.inSegment) return;
    this.send({ type: "segment_end" });
    this.inSegment = false;
    this.lastSpeechEndAt = this.now() - this.redemptionS;
  }

  // Capture is pausing (half-duplex playback, or Guide switched off) mid-segment.
  stop() {
    if (this.inSegment) this.onSpeechEnd();
    this.preRoll = [];
    this.preRollSamples = 0;
  }

  #send(frame) {
    this.sendAudio(floatTo16BitPcm(frame).buffer);
    this.segmentSamples += frame.length;
  }
}
