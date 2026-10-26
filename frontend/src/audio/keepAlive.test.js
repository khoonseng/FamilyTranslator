import { describe, expect, it } from "vitest";
import { KeepAlive } from "./keepAlive.js";

class FakeAudio {
  constructor() {
    this.listeners = {};
    this.paused = true;
    this.refuse = false;
    this.plays = 0;
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  play() {
    this.plays++;
    if (this.refuse) return Promise.reject(new Error("NotAllowedError"));
    this.paused = false;
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
    this.listeners.pause?.();
  }
}

function setup() {
  const audio = new FakeAudio();
  const blocked = [];
  const keeper = new KeepAlive({ element: audio, url: () => "blob:silence", onBlocked: (b) => blocked.push(b) });
  return { audio, blocked, keeper };
}

describe("KeepAlive", () => {
  it("loops silence from the start tap", async () => {
    const { audio, keeper } = setup();
    await keeper.start();
    expect([audio.loop, audio.src, audio.paused]).toEqual([true, "blob:silence", false]);
  });

  it("restarts itself when iOS pauses it", async () => {
    const { audio, keeper } = setup();
    await keeper.start();
    audio.pause();
    await Promise.resolve();
    expect(audio.plays).toBe(2);
    expect(audio.paused).toBe(false);
  });

  it("asks for a tap when the restart is refused, and clears it after the tap", async () => {
    const { audio, blocked, keeper } = setup();
    await keeper.start();
    audio.refuse = true;
    audio.pause();
    await new Promise((r) => setTimeout(r));
    expect(blocked).toEqual([true]);
    audio.refuse = false;
    await keeper.resume();
    expect(blocked).toEqual([true, false]);
  });

  it("check() restarts it only if it stopped", async () => {
    const { audio, keeper } = setup();
    await keeper.start();
    await keeper.check();
    expect(audio.plays).toBe(1);
    audio.paused = true; // stopped without an event while the page was frozen
    await keeper.check();
    expect(audio.plays).toBe(2);
  });

  it("stop() is not undone by its own pause event", async () => {
    const { audio, keeper } = setup();
    await keeper.start();
    keeper.stop();
    expect(audio.plays).toBe(1);
    expect(audio.paused).toBe(true);
  });
});
