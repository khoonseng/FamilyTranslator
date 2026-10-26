import { describe, expect, it } from "vitest";
import { ClipOutput } from "./clipOutput.js";

// Events are dispatched like the browser's: queued, after the current microtasks.
class FakeAudio {
  constructor() {
    this.listeners = {};
    this.paused = true;
    this.ended = false;
    this.played = [];
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  fire(name) {
    setTimeout(() => this.listeners[name]());
  }
  play() {
    this.paused = false;
    this.ended = false;
    this.played.push(this.src);
    return Promise.resolve();
  }
  pause() {
    if (this.paused) return;
    this.paused = true;
    this.fire("pause");
  }
  end() {
    this.paused = this.ended = true;
    this.fire("pause"); // the spec fires pause, then ended
    this.fire("ended");
  }
}

const tick = () => new Promise((r) => setTimeout(r));

function setup(clips = { 1: new ArrayBuffer(4), 2: new ArrayBuffer(4) }) {
  const audio = new FakeAudio();
  const ended = [];
  const interrupted = [];
  const output = new ClipOutput({
    element: audio,
    load: async (id) => clips[id],
    onEnded: (id, ok) => ended.push([id, ok]),
    onInterrupted: (id) => interrupted.push(id),
  });
  return { audio, ended, interrupted, output };
}

describe("ClipOutput", () => {
  it("reports a clip that played to the end, once", async () => {
    const { audio, ended, interrupted, output } = setup();
    await output.play(1);
    audio.end();
    await tick();
    expect(ended).toEqual([[1, true]]);
    expect(interrupted).toEqual([]);
  });

  it("a missing clip ends at once, not ok", async () => {
    const { audio, ended, output } = setup();
    await output.play(7);
    expect(ended).toEqual([[7, false]]);
    expect(audio.played).toEqual([]);
  });

  it("iOS pausing the clip is an interruption", async () => {
    const { audio, ended, interrupted, output } = setup();
    await output.play(1);
    audio.pause();
    await tick();
    expect(interrupted).toEqual([1]);
    expect(ended).toEqual([]);
  });

  it("our own stop, then the next clip: the late pause event is not an interruption", async () => {
    const { audio, ended, interrupted, output } = setup();
    await output.play(1);
    output.stop();
    await output.play(2);
    await tick();
    expect(interrupted).toEqual([]);
    audio.end();
    await tick();
    expect(ended).toEqual([[2, true]]);
  });

  it("a stop while a clip is loading cancels it", async () => {
    const { audio, ended, output } = setup();
    const playing = output.play(1);
    output.stop();
    await playing;
    expect(audio.played).toEqual([]);
    expect(ended).toEqual([]);
  });
});
