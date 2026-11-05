import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClipCache, memoryBackend } from "../lib/clipCache.js";
import { setListenParts, useListenStore } from "./listen.js";

class FakePlayer {
  constructor() {
    this.arrived = [];
    this.resets = 0;
  }
  arrive(id) {
    this.arrived.push(id);
  }
  reset() {
    this.resets++;
  }
}

class FakeSocket {
  constructor() {
    this.sent = [];
  }
  sendJson(message) {
    this.sent.push(message);
  }
}

const sentence = (id, bubble = 1) => ({
  type: "sentence",
  id,
  bubble_id: bubble,
  zh: `中文${id}`,
  yue: `廣東話${id}`,
  status: "ok",
});
const mp3 = () => new ArrayBuffer(8);

let listen, player, socket, cache;

beforeEach(() => {
  setActivePinia(createPinia());
  player = new FakePlayer();
  socket = new FakeSocket();
  cache = new ClipCache(memoryBackend());
  setListenParts({ player, socket, cache });
  listen = useListenStore();
  listen.day = "2026-12-19";
});

afterEach(() => vi.unstubAllGlobals());

describe("listener store: joining and catching up", () => {
  it("joining fresh: today's earlier sentences are history, never auto-played", () => {
    listen.ready({ day: "2026-12-19", latest_id: 2 });
    [1, 2].forEach((id) => listen.receive(sentence(id)));
    [1, 2].forEach((id) => listen.receiveClip(id, mp3()));
    listen.receive(sentence(3));
    listen.receiveClip(3, mp3());
    expect(player.arrived).toEqual([3]);
    expect(listen.sentences[1].played).toBe(true); // no unplayed marker on history
    expect(listen.sentences[3].played).toBe(false);
  });

  it("after a reconnect, the sentences missed meanwhile play as new", () => {
    listen.ready({ day: "2026-12-19", latest_id: 0 });
    listen.receive(sentence(1));
    listen.receiveClip(1, mp3());
    expect(listen.hello().last_id).toBe(1);
    listen.ready({ day: "2026-12-19", latest_id: 3 });
    [2, 3].forEach((id) => listen.receive(sentence(id)));
    [2, 3].forEach((id) => listen.receiveClip(id, mp3()));
    expect(player.arrived).toEqual([1, 2, 3]);
  });

  it("asks again for a clip lost between its sentence and the drop", () => {
    listen.ready({ day: "2026-12-19", latest_id: 0 });
    listen.receive(sentence(1));
    listen.hello();
    listen.ready({ day: "2026-12-19", latest_id: 1 });
    expect(socket.sent).toEqual([{ type: "clip_request", sentence_id: 1 }]);
    listen.receiveClip(1, mp3());
    expect(player.arrived).toEqual([1]); // still unplayed, so it plays
  });

  it("a ready for another day clears the bubbles", () => {
    listen.receive(sentence(1));
    listen.ready({ day: "2026-12-20", latest_id: 0 });
    expect([listen.day, listen.bubbles, player.resets]).toEqual(["2026-12-20", [], 1]);
  });

  it("a day change mid-session clears the bubbles, and the new day's sentences play", () => {
    listen.ready({ day: "2026-12-19", latest_id: 5 });
    listen.receive(sentence(5));
    listen.receive({ type: "day", day: "2026-12-20" });
    expect(listen.bubbles).toEqual([]);
    listen.receive(sentence(1));
    listen.receiveClip(1, mp3());
    expect(player.arrived).toEqual([1]);
  });

  it("a reloaded page shows its own bubbles and catches up from its last sentence", async () => {
    await cache.putSentence("2026-12-19", { id: 4, bubbleId: 2, yue: "四", clip: "ready", played: true });
    for (const s of await cache.loadDay("2026-12-19")) listen.addSentence(s);
    expect(listen.hello()).toEqual({
      role: "listener", room: "", device: listen.device, day: "2026-12-19", last_id: 4,
    });
  });
});

describe("listener store: sentences and clips", () => {
  it("groups sentences into bubbles and keeps them in the phone's cache", async () => {
    listen.receive(sentence(1, 1));
    listen.receive(sentence(2, 1));
    listen.receive(sentence(3, 2));
    listen.receive({ type: "english", sentence_id: 2, en: "Two" });
    expect(listen.bubbles).toEqual([
      { id: 1, sentenceIds: [1, 2] },
      { id: 2, sentenceIds: [3] },
    ]);
    await Promise.resolve();
    const stored = await cache.loadDay("2026-12-19");
    expect(stored.map((s) => [s.id, s.en])).toEqual([[1, ""], [2, "Two"], [3, ""]]);
  });

  it("a clip missing from memory and cache is asked for again, and only cached when it comes", async () => {
    listen.ready({ day: "2026-12-19", latest_id: 1 });
    listen.receive(sentence(1));
    expect(await listen.loadClip(1)).toBe(undefined);
    expect(socket.sent).toEqual([{ type: "clip_request", sentence_id: 1 }]);
    listen.receiveClip(1, mp3());
    expect(player.arrived).toEqual([]);
    expect(await listen.loadClip(1)).toBeInstanceOf(ArrayBuffer);
  });

  it("a played sentence's clip arriving again doesn't play", () => {
    listen.ready({ day: "2026-12-19", latest_id: 0 });
    listen.receive(sentence(1));
    listen.receiveClip(1, mp3());
    listen.markPlayed(1);
    listen.receiveClip(1, mp3());
    expect(player.arrived).toEqual([1]);
  });

  it("keeps each sentence's sources, for the host screen", () => {
    listen.receive({ ...sentence(1), stt: "chirp_3", provider: "gemini" });
    listen.receiveClip(1, mp3(), "yue-HK-Standard-A");
    const { stt, provider, voice } = listen.sentences[1];
    expect([stt, provider, voice]).toEqual(["chirp_3", "gemini", "yue-HK-Standard-A"]);
  });

  it("no translation: text only, no clip expected", () => {
    listen.receive({ ...sentence(1), yue: "", status: "no_translation" });
    expect(listen.sentences[1].clip).toBe("none");
  });

  it("a host phone signs in with the PIN and token, never the join link", () => {
    listen.setHost(true);
    Object.assign(listen, { pin: "11112222", apiToken: "33334444", token: "family-link" });
    expect(listen.hello()).toEqual({
      role: "listener", pin: "11112222", token: "33334444", device: listen.device,
      day: "2026-12-19", last_id: 0,
    });
    listen.ready({ day: "2026-12-19", latest_id: 0, host: true });
    expect(socket.sent).toEqual([{ type: "link" }]); // for Share link
  });

  it("a host phone without the PIN and token asks for them first", () => {
    listen.pin = "";
    listen.setHost(true);
    expect(listen.screen).toBe("credentials");
  });

  it("a family phone never asks for the join link or sends a PIN", () => {
    listen.token = "family-link";
    expect(listen.hello()).toEqual({
      role: "listener", room: "family-link", device: listen.device, day: "2026-12-19", last_id: 0,
    });
    listen.ready({ day: "2026-12-19", latest_id: 0, host: false });
    expect(socket.sent).toEqual([]);
  });

  it("a host phone shows the spend and builds the join link with #", () => {
    vi.stubGlobal("location", { origin: "https://translator.example" });
    listen.receive({ type: "spend", usd: 13.4, warn: true, warn_usd: 12 });
    listen.receive({ type: "join_link", token: "abc123" });
    expect(listen.spend).toEqual({ usd: 13.4, warn: true, warnUsd: 12 });
    expect(listen.joinUrl).toBe("https://translator.example/join#abc123");
  });

  it("hub status is shown as sent", () => {
    listen.receive({ type: "hub_status", online: false, listening: false, remote_paused: true });
    expect(listen.hub).toEqual({
      online: false, listening: false, remotePaused: true, mic: "", micLost: false, interrupted: false,
      guideTalking: false, familyTalking: false,
    });
    listen.receive({
      type: "hub_status", online: true, listening: true, remote_paused: false,
      mic: "phone", mic_lost: true, interrupted: false,
    });
    expect([listen.hub.mic, listen.hub.micLost]).toEqual(["phone", true]);
  });
});

describe("listener store: replies to the guide (phase 2)", () => {
  class TalkSocket extends FakeSocket {
    constructor() {
      super();
      this.audio = [];
      this.restarts = 0;
    }
    sendAudio(buffer) {
      this.audio.push(buffer);
    }
    restart() {
      this.restarts++;
    }
  }
  class TalkPlayer extends FakePlayer {
    constructor() {
      super();
      this.state = "live";
      this.pauses = 0;
      this.resumed = 0;
    }
    pause() {
      this.pauses++;
      this.state = "paused";
    }
    playNew() {
      this.resumed++;
      this.state = "live";
    }
  }
  const keeper = { stops: 0, starts: 0, stop() { this.stops++; }, start() { this.starts++; } };
  let mic, talkSocket, talkPlayer;

  beforeEach(() => {
    talkSocket = new TalkSocket();
    talkPlayer = new TalkPlayer();
    keeper.stops = keeper.starts = 0;
    mic = { stopped: false, stop() { this.stopped = true; } };
    setListenParts({
      socket: talkSocket,
      player: talkPlayer,
      keeper,
      makeRecorder: async ({ onPcm }) => {
        mic.onPcm = onPcm;
        return mic;
      },
    });
    listen.canTalk = true;
  });

  it("the hub PIN unlocks Talk; a wrong one is forgotten and the phone keeps listening", () => {
    listen.canTalk = false;
    listen.unlockTalk(" 12345678 ");
    expect([listen.pin, talkSocket.restarts]).toEqual(["12345678", 1]);
    expect(listen.hello().pin).toBe("12345678");
    listen.ready({ day: "2026-12-19", latest_id: 0, talk: false });
    expect([listen.canTalk, listen.pinWrong, listen.pin]).toEqual([false, true, ""]);
    listen.unlockTalk("87654321");
    listen.ready({ day: "2026-12-19", latest_id: 0, talk: true });
    expect([listen.canTalk, listen.pinWrong]).toEqual([true, false]);
  });

  it("holding Talk pauses playback and the keep-alive, streams the mic, and release sends it", async () => {
    await listen.startTalk();
    expect(talkSocket.sent).toEqual([{ type: "talk_start" }]);
    expect([talkPlayer.pauses, keeper.stops, listen.talkLive]).toEqual([1, 1, true]);
    mic.onPcm(new ArrayBuffer(8));
    expect(talkSocket.audio.length).toBe(1);
    listen.stopTalk();
    expect(talkSocket.sent.at(-1)).toEqual({ type: "talk_end" });
    expect([mic.stopped, keeper.starts, talkPlayer.resumed]).toEqual([true, 1, 1]);
  });

  it("Talk waits while the guide speaks or another phone talks", async () => {
    listen.hub.guideTalking = true;
    await listen.startTalk();
    listen.hub.guideTalking = false;
    listen.hub.familyTalking = true;
    await listen.startTalk();
    expect(talkSocket.sent).toEqual([]);
  });

  it("a refusal from the server ends Talk without sending it", async () => {
    await listen.startTalk();
    listen.receive({ type: "error", code: "someone_talking" });
    expect([listen.talking, listen.talkError, mic.stopped]).toEqual([false, "someone_talking", true]);
    expect(talkSocket.sent).toEqual([{ type: "talk_start" }]);
  });

  it("a reply shows as text, without audio, and the asker's own phone knows it", () => {
    listen.receive({
      type: "sentence", id: 7, bubble_id: 4, kind: "reply", zh: "幾點集合？", yue: "",
      mandarin: "几点集合？", asker: listen.device, status: "ok",
    });
    const reply = listen.sentences[7];
    expect([reply.kind, reply.clip, reply.played, reply.asker === listen.device]).toEqual([
      "reply", "none", true, true,
    ]);
  });

  it("typing a reply needs Talk to be unlocked", () => {
    expect(listen.sendReply("  幾點走？ ")).toBe(true);
    expect(talkSocket.sent).toEqual([{ type: "reply_text", text: "幾點走？" }]);
    listen.canTalk = false;
    expect(listen.sendReply("再問")).toBe(false);
  });
});
