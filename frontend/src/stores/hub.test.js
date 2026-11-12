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

// The audio element the hub plays Mandarin replies on.
class FakeReplyOutput {
  constructor() {
    this.played = [];
    this.stops = 0;
  }
  play(id) {
    this.played.push(id);
  }
  stop() {
    this.stops++;
  }
}

let replyOutput;

beforeEach(() => {
  setActivePinia(createPinia());
  socket = new FakeSocket();
  capture = new FakeCapture();
  replyOutput = new FakeReplyOutput();
  setHubParts({ socket, capture, makeCapture: null, replyOutput });
  hub = useHubStore();
  hub.screen = "hub";
});

describe("hub store", () => {
  it("a reconnect after another phone took over stops this hub", () => {
    hub.listening = true;
    capture.running = true;
    hub.ready({ role: "listener", day: "2026-12-19", latest_id: 0 });
    expect([hub.screen, hub.listening, capture.destroyed, socket.closed]).toEqual([
      "replaced", false, true, true,
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
    let made;
    setHubParts({ capture: null, makeCapture: async (o) => (made = new FakeCapture(o)) });
    await hub.setGuide(true);
    const first = made;
    await hub.remote(true);
    expect([hub.listening, hub.remotePaused, first.destroyed]).toEqual([false, true, true]);
    await hub.remote(false);
    expect([hub.listening, hub.remotePaused, made.running]).toEqual([true, false, true]);
    const modes = socket.sent.filter((m) => m.type === "mode").map((m) => m.mode);
    expect(modes).toEqual(["guide", "off", "guide"]);
  });

  it("Guide off closes the mic completely; Guide on opens a fresh one", async () => {
    let made;
    setHubParts({ capture: null, makeCapture: async (o) => (made = new FakeCapture(o)) });
    await hub.setGuide(true);
    const first = made;
    await hub.setGuide(false);
    expect([first.destroyed, hub.level]).toEqual([true, 0]);
    await hub.setGuide(true);
    expect([made === first, made.running, hub.listening]).toEqual([false, true, true]);
  });

  it("Guide switched on twice at once opens only one mic", async () => {
    const made = [];
    setHubParts({ capture: null, makeCapture: async (o) => made.push(new FakeCapture(o)) && made.at(-1) });
    await Promise.all([hub.setGuide(true), hub.setGuide(true)]);
    expect(made.map((m) => m.destroyed)).toEqual([false, true]);
    await hub.setGuide(false);
    expect(made.every((m) => m.destroyed)).toBe(true);
  });

  it("Guide off while the mic is still opening: it is closed as soon as it opens", async () => {
    let open;
    const mic = new FakeCapture();
    setHubParts({ capture: null, makeCapture: () => new Promise((r) => (open = () => r(mic))) });
    const on = hub.setGuide(true);
    await new Promise((r) => setTimeout(r));
    await hub.setGuide(false);
    open();
    await on;
    expect([mic.destroyed, hub.listening]).toEqual([true, false]);
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

describe("hub store: family replies (phase 2)", () => {
  const reply = (id) => ({
    type: "sentence", id, bubble_id: id, kind: "reply", zh: "幾點集合？", yue: "",
    mandarin: "几点集合？", status: "ok",
  });

  it("shows a reply with its Mandarin, and a Cantonese clip is never played", () => {
    hub.receive(reply(5));
    hub.receiveClip(4, new ArrayBuffer(4), { for_hub: false }); // a guide sentence's clip
    expect([hub.sentences[5].kind, hub.sentences[5].mandarin]).toEqual(["reply", "几点集合？"]);
    expect(replyOutput.played).toEqual([]);
  });

  it("with Guide off, a reply's Mandarin plays at once", async () => {
    hub.receive(reply(5));
    hub.receiveClip(5, new ArrayBuffer(4), { for_hub: true });
    await new Promise((r) => setTimeout(r));
    expect([replyOutput.played, hub.replyPlaying]).toEqual([[5], 5]);
  });

  it("while listening, the mic is fully released to play, and reopened after", async () => {
    let made;
    setHubParts({ capture: null, makeCapture: async (o) => (made = new FakeCapture(o)) });
    await hub.setGuide(true);
    const before = made;
    const player = hub.replyPlayer();
    player.quietSince = -Infinity; // the guide has been quiet long enough
    hub.receive(reply(5));
    hub.receiveClip(5, new ArrayBuffer(4), { for_hub: true });
    await new Promise((r) => setTimeout(r));
    expect([before.destroyed, replyOutput.played]).toEqual([true, [5]]);
    await player.ended(5);
    expect([hub.listening, made === before, hub.replyPlaying]).toEqual([true, false, null]);
  });

  it("with Guide off, the paused mic is fully released before a reply, and stays closed after", async () => {
    let made;
    setHubParts({ capture: null, makeCapture: async (o) => (made = new FakeCapture(o)) });
    await hub.setGuide(true);
    await hub.setGuide(false); // pauses: the clip-on stays open
    const before = made;
    hub.receive(reply(5));
    hub.receiveClip(5, new ArrayBuffer(4), { for_hub: true });
    await new Promise((r) => setTimeout(r));
    expect([before.destroyed, replyOutput.played]).toEqual([true, [5]]);
    await hub.replyPlayer().ended(5);
    expect([hub.listening, made === before, hub.replyPlaying]).toEqual([false, true, null]);
  });

  it("a tap stops the reply", async () => {
    hub.receive(reply(5));
    hub.receiveClip(5, new ArrayBuffer(4), { for_hub: true });
    await new Promise((r) => setTimeout(r));
    await hub.stopReply();
    expect([replyOutput.stops, hub.replyPlaying]).toEqual([1, null]);
  });
});
