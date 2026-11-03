import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { setHubParts, useHubStore } from "./hub.js";

class FakeSocket {
  constructor() {
    this.sent = [];
    this.closed = false;
  }
  sendJson(message) {
    this.sent.push(message);
  }
  close() {
    this.closed = true;
  }
}

class FakeCapture {
  constructor(options = {}) {
    this.options = options;
    this.running = false;
    this.destroyed = false;
  }
  get input() {
    return { label: this.options.deviceId === "dji" ? "DJI Mic Mini 2" : "iPhone Microphone" };
  }
  async start() {
    if (this.options.deviceId === "gone") {
      throw Object.assign(new Error("no such input"), { name: "OverconstrainedError" });
    }
    this.running = true;
  }
  async pause() {
    this.running = false;
  }
  async destroy() {
    this.destroyed = true;
  }
}

const sentence = (id, bubble = 1) => ({
  type: "sentence", id, bubble_id: bubble, zh: `中文${id}`, yue: `廣東話${id}`, status: "ok",
});

let hub, socket, capture;

beforeEach(() => {
  setActivePinia(createPinia());
  socket = new FakeSocket();
  capture = new FakeCapture();
  setHubParts({ socket, capture, makeCapture: null });
  hub = useHubStore();
  hub.screen = "hub";
});

describe("hub store", () => {
  it("a reconnect after another phone took over stops this hub", () => {
    hub.listening = true;
    capture.running = true;
    hub.ready({ role: "listener", day: "2026-12-19", latest_id: 0 });
    expect([hub.screen, hub.listening, capture.running, socket.closed]).toEqual([
      "replaced", false, false, true,
    ]);
  });

  it("being replaced while connected stops it too", () => {
    hub.listening = true;
    hub.receive({ type: "role", role: "listener", reason: "replaced" });
    expect(hub.screen).toBe("replaced");
  });

  it("a reconnect as hub turns Guide back on at the server", () => {
    hub.listening = true;
    hub.ready({ role: "hub", day: "2026-12-19", latest_id: 0 });
    expect(socket.sent).toEqual([{ type: "mode", mode: "guide" }]);
  });

  it("remote pause switches Guide off, and resume switches it back on", async () => {
    await hub.setGuide(true);
    await hub.remote(true);
    expect([hub.listening, hub.remotePaused, capture.running]).toEqual([false, true, false]);
    await hub.remote(false);
    expect([hub.listening, hub.remotePaused, capture.running]).toEqual([true, false, true]);
    expect(socket.sent.map((m) => m.mode)).toEqual(["guide", "off", "guide"]);
  });

  it("tapping Guide clears the remote-pause notice", async () => {
    await hub.remote(true);
    await hub.toggleGuide();
    expect([hub.listening, hub.remotePaused]).toEqual([true, false]);
  });

  it("catch-up after a reconnect doesn't duplicate bubbles", () => {
    hub.receive(sentence(1));
    hub.receive(sentence(1));
    hub.receive(sentence(2));
    expect(hub.bubbles).toEqual([{ id: 1, sentenceIds: [1, 2] }]);
  });

  it("shows the input actually in use once listening", async () => {
    await hub.setGuide(true);
    expect(hub.micLabel).toBe("iPhone Microphone");
  });

  it("choosing another mic re-opens capture with it, and keeps listening", async () => {
    let made;
    setHubParts({ capture: null, makeCapture: async (o) => (made = new FakeCapture(o)) });
    await hub.setGuide(true);
    const first = made;
    await hub.setMic("dji");
    expect([first.destroyed, made.options.deviceId, hub.listening, hub.micLabel]).toEqual([
      true, "dji", true, "DJI Mic Mini 2",
    ]);
  });

  it("the voice-processing switch reaches the capture settings", async () => {
    let made;
    setHubParts({ capture: null, makeCapture: async (o) => (made = new FakeCapture(o)) });
    await hub.setGuide(true);
    await hub.setProcessing(false);
    expect([made.options.processing, hub.processing]).toEqual([false, false]);
  });

  it("a remembered mic that is unplugged falls back to the phone's default", async () => {
    setHubParts({ capture: null, makeCapture: async (o) => new FakeCapture(o) });
    hub.micId = "gone";
    await hub.setGuide(true);
    expect([hub.micId, hub.listening, hub.micError]).toEqual(["", true, ""]);
  });

  it("says which sentence it has, so catch-up starts after it", () => {
    hub.ready({ role: "hub", day: "2026-12-19", latest_id: 0 });
    hub.receive(sentence(3));
    expect(hub.lastId).toBe(3);
    hub.receive({ type: "day", day: "2026-12-20" });
    expect([hub.day, hub.lastId, hub.bubbles]).toEqual(["2026-12-20", 0, []]);
  });
});
