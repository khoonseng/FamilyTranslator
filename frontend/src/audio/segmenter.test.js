import { describe, expect, it } from "vitest";
import { SAMPLE_RATE, Segmenter } from "./segmenter.js";

const FRAME = 512; // Silero v5: 32 ms at 16 kHz

function setup(options = {}) {
  const messages = [];
  const audio = [];
  let clock = 100;
  const seg = new Segmenter({
    send: (m) => messages.push(m),
    sendAudio: (buffer) => audio.push(buffer.byteLength / 2),
    now: () => clock,
    ...options,
  });
  const frames = (n, value = 0.1) => {
    for (let i = 0; i < n; i++) seg.onFrame(new Float32Array(FRAME).fill(value));
  };
  return { seg, messages, audio, frames, advance: (s) => (clock += s) };
}

describe("Segmenter", () => {
  it("sends nothing before speech", () => {
    const { messages, audio, frames } = setup();
    frames(50);
    expect(messages).toEqual([]);
    expect(audio).toEqual([]);
  });

  it("starts a segment with the pre-roll, streams frames, then ends it", () => {
    const { seg, messages, audio, frames } = setup({ preRollMs: 100 });
    frames(20); // silence before speech: only ~100 ms of it is kept
    seg.onSpeechStart();
    frames(3);
    seg.onSpeechEnd();
    expect(messages).toEqual([{ type: "segment_start", pause_s: 99 }, { type: "segment_end" }]);
    const preRollFrames = Math.ceil((0.1 * SAMPLE_RATE) / FRAME);
    expect(audio.length).toBe(preRollFrames + 3);
    expect(audio.every((samples) => samples === FRAME)).toBe(true);
  });

  it("reports the pause before each segment, counting the VAD's pause detection", () => {
    const { seg, messages, advance } = setup({ redemptionMs: 700 });
    seg.onSpeechStart();
    seg.onSpeechEnd(); // fired 0.7 s after the speech really ended
    advance(1.8);
    seg.onSpeechStart();
    expect(messages.at(-1)).toEqual({ type: "segment_start", pause_s: 2.5 });
  });

  it("cuts a segment at the 15 s cap and carries on in a new one", () => {
    const { seg, messages, frames } = setup({ capS: 1 });
    seg.onSpeechStart();
    frames(Math.ceil(SAMPLE_RATE / FRAME) + 1);
    expect(messages.slice(1, 3)).toEqual([
      { type: "segment_end" },
      { type: "segment_start", pause_s: 0 },
    ]);
  });

  it("ends an open segment when capture stops", () => {
    const { seg, messages } = setup();
    seg.onSpeechStart();
    seg.stop();
    seg.stop();
    expect(messages.map((m) => m.type)).toEqual(["segment_start", "segment_end"]);
  });

  it("ignores a second speech start inside a segment", () => {
    const { seg, messages } = setup();
    seg.onSpeechStart();
    seg.onSpeechStart();
    expect(messages.length).toBe(1);
  });
});
