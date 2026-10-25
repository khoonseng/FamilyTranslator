import { describe, expect, it } from "vitest";
import { ClipPlayer } from "./player.js";

class FakeAudio {
  constructor() {
    this.listeners = {};
    this.played = [];
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  play() {
    this.played.push(this.src);
    return Promise.resolve();
  }
  end() {
    this.listeners.ended();
  }
}

describe("ClipPlayer", () => {
  it("plays clips one after another, in order", () => {
    const audio = new FakeAudio();
    const states = [];
    const played = [];
    const player = new ClipPlayer({
      element: audio,
      onPlaying: (p) => states.push(p),
      onPlayed: (id) => played.push(id),
    });
    player.enqueue(1, "blob:1");
    player.enqueue(2, "blob:2");
    expect(audio.played).toEqual(["blob:1"]);
    expect(player.waiting).toBe(1);
    audio.end();
    expect(audio.played).toEqual(["blob:1", "blob:2"]);
    audio.end();
    expect(played).toEqual([1, 2]);
    expect(states).toEqual([true, true, false]);
  });

  it("an extra ended event doesn't skip a clip", () => {
    const audio = new FakeAudio();
    const played = [];
    const player = new ClipPlayer({ element: audio, onPlayed: (id) => played.push(id) });
    player.enqueue(1, "blob:1");
    audio.end();
    audio.end();
    expect(played).toEqual([1]);
  });
});
