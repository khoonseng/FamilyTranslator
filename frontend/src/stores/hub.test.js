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
  get track() {
    return { state: this.ended ? "ended" : "live", muted: false };
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
    expect(socket.sent.filter((m) => m.type === "mode")).toEqual([{ type: "mode", mode: "guide" }]);
  });

  it("remote pause switches Guide off, and resume switches it back on", async () => {
    await hub.setGuide(true);
    await hub.remote(true);
    expect([hub.listening, hub.remotePaused, capture.running]).toEqual([false, true, false]);
    await hub.remote(false);
    expect([hub.listening, hub.remotePaused, capture.running]).toEqual([true, false, true]);
    const modes = socket.sent.filter((m) => m.type === "mode").map((m) => m.mode);
    expect(modes).toEqual(["guide", "off", "guide"]);
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

  it("a remembered mic that is missing: the phone's mic, the choice kept, and say it's lost", async () => {
    setHubParts({ capture: null, makeCapture: async (o) => new FakeCapture(o) });
    hub.micId = "gone";
    await hub.setGuide(true);
    expect([hub.micId, hub.listening, hub.micError, hub.micLost]).toEqual(["gone", true, "", true]);
  });
});

describe("hub store: never deaf without saying so", () => {
  const IPHONE = { id: "iphone", label: "iPhone Microphone" };
  const DJI = { id: "dji", label: "DJI Mic Mini 2" };
  let made, inputs;

  beforeEach(async () => {
    inputs = [IPHONE, DJI];
    setHubParts({
      capture: null,
      makeCapture: async (o) => (made = new FakeCapture(o)),
      listInputs: async () => inputs,
      audioContext: null,
    });
    hub.micId = "dji";
    await hub.setGuide(true);
    socket.sent = [];
  });

  const reports = () => socket.sent.filter((m) => m.type === "hub_mic");

  it("the clip-on drops out: the phone's mic listens, the hub says so, host phones are told", async () => {
    inputs = [IPHONE];
    await hub.checkMic();
    expect([made.options.deviceId, hub.micLost, hub.listening]).toEqual(["", true, true]);
    expect(reports().at(-1)).toEqual({ type: "hub_mic", mic: "phone", lost: true, interrupted: false });
  });

  it("the clip-on comes back: the hub switches back by itself", async () => {
    inputs = [IPHONE];
    await hub.checkMic();
    inputs = [IPHONE, DJI];
    await hub.checkMic();
    expect([made.options.deviceId, hub.micLost, hub.micLabel]).toEqual(["dji", false, "DJI Mic Mini 2"]);
    expect(reports().at(-1)).toEqual({ type: "hub_mic", mic: "external", lost: false, interrupted: false });
  });

  it("nothing changed: no restart and no repeated report", async () => {
    const before = made;
    await hub.checkMic();
    expect(made).toBe(before);
    expect(reports()).toEqual([]);
  });

  it("the microphone was ended by another app: it is opened again", async () => {
    const before = made;
    made.ended = true;
    await hub.checkMic();
    expect(made).not.toBe(before);
    expect(hub.listening).toBe(true);
  });

  it("back from another app with the engine stuck: ask for a tap, which brings it back", async () => {
    const engine = { state: "suspended", resume: async () => {} }; // iOS won't resume it
    setHubParts({ audioContext: engine });
    await hub.checkMic({ resume: true });
    expect(hub.needTap).toBe(true);
    expect(reports().at(-1).interrupted).toBe(true);
    engine.state = "running"; // the tap resumes it
    await hub.tapResume();
    expect([hub.needTap, hub.listening]).toEqual([false, true]);
  });

  it("not listening: no checks", async () => {
    await hub.setGuide(false);
    inputs = [IPHONE];
    await hub.checkMic();
    expect(hub.micLost).toBe(false);
  });

  it("says which sentence it has, so catch-up starts after it", () => {
    hub.ready({ role: "hub", day: "2026-12-19", latest_id: 0 });
    hub.receive(sentence(3));
    expect(hub.lastId).toBe(3);
    hub.receive({ type: "day", day: "2026-12-20" });
    expect([hub.day, hub.lastId, hub.bubbles]).toEqual(["2026-12-20", 0, []]);
  });
});
