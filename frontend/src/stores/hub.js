// The hub's state: credentials, connection, the Guide latch and today's bubbles (text only:
// from weeks 4–5 the hub never plays Cantonese, so capture never pauses in phase 1, hard rule
// 13). The socket and microphone live outside Vue's reactivity, in this module.
//
// One active hub (architecture doc): Start on this page (or Become hub on a host phone, which
// opens it) takes over from any other hub. An automatic reconnect never does: if another phone
// took over meanwhile, this one stops and says so.

import { defineStore } from "pinia";
import { microphones } from "../audio/micSettings.js";
import { keepScreenOn, store, stored } from "../lib/device.js";
import { RoomSocket } from "../lib/roomSocket.js";

let socket = null;
let capture = null;
let takeover = false; // true until the first ready after Start
let audioContext = null;

// The VAD's audio engine. iOS starts an AudioContext suspended unless it is created or resumed
// inside a tap; the VAD would make its own only after its model loads, long after the Guide
// tap, and hear nothing (weeks 2–3 got away with it because Start also unlocked the clip
// player). So Start and Guide make or resume it here, before anything is awaited.
function wakeAudio() {
  if (typeof AudioContext === "undefined") return; // tests
  audioContext ||= new AudioContext();
  if (audioContext.state !== "running") audioContext.resume().catch(() => {});
}

// Tests swap in fakes for the socket and the microphone (and its factory).
let makeCapture = null;
export function setHubParts(parts) {
  if ("socket" in parts) socket = parts.socket;
  if ("capture" in parts) capture = parts.capture;
  if ("makeCapture" in parts) makeCapture = parts.makeCapture;
}

export const useHubStore = defineStore("hub", {
  state: () => ({
    pin: stored("hubPin"),
    token: stored("apiToken"),
    screen: stored("hubPin") && stored("apiToken") ? "start" : "credentials", // … | hub | replaced
    refused: false,
    connection: "offline", // connecting | connected | offline
    listening: false, // the Guide latch (hard rule 8)
    remotePaused: false, // a host phone paused Guide listening
    micError: "",
    // Mic settings, remembered per phone (owner decision 2026-11-03; see audio/micSettings.js).
    micId: stored("micId"), // "" = the phone's default input
    processing: stored("micProcessing") !== "off", // the phone's voice processing
    mics: [], // [{ id, label }] the inputs Safari lists
    micLabel: "", // the input actually in use
    level: 0, // 0..1, for the level bar
    day: "",
    bubbles: [], // [{ id, sentenceIds: [] }]
    sentences: {}, // id -> { id, bubbleId, zh, yue, en, status, clip }
  }),

  getters: {
    lastId: (s) => Math.max(0, ...Object.keys(s.sentences).map(Number)),
  },

  actions: {
    saveCredentials(pin, token) {
      this.pin = pin.trim();
      this.token = token.trim();
      store("hubPin", this.pin);
      store("apiToken", this.token);
      this.refused = false;
      this.screen = "start";
    },

    forgetCredentials() {
      socket?.close();
      store("hubPin", "");
      store("apiToken", "");
      this.pin = this.token = "";
      this.screen = "credentials";
    },

    // Start, or Become hub on a host phone: this phone takes over as the hub.
    start() {
      wakeAudio();
      socket?.close();
      takeover = true;
      socket = new RoomSocket({
        hello: () => ({
          role: "hub",
          pin: this.pin,
          token: this.token,
          day: this.day,
          last_id: this.lastId,
          takeover,
        }),
        onStatus: (status) => (this.connection = status),
        onReady: (message) => this.ready(message),
        onRefused: () => {
          this.refused = true;
          this.screen = "credentials";
        },
        onMessage: (message) => this.receive(message),
        onClip: (id) => {
          // Shown as text only: the hub never plays Cantonese.
          if (this.sentences[id]) this.sentences[id].clip = "ready";
        },
      });
      socket.connect();
      keepScreenOn();
      this.micError = "";
      this.screen = "hub";
    },

    ready(message) {
      takeover = false; // from now on, reconnects are automatic
      if (message.role !== "hub") {
        this.replaced(); // another phone took over while this one was cut off
        return;
      }
      if (message.day !== this.day) this.newDay(message.day);
      if (this.listening) socket.sendJson({ type: "mode", mode: "guide" }); // after a reconnect
    },

    // Another phone is the hub now: stop listening and let go of the room.
    replaced() {
      this.listening = false;
      this.remotePaused = false;
      capture?.pause();
      socket?.close();
      this.screen = "replaced";
    },

    async toggleGuide() {
      this.remotePaused = false;
      await this.setGuide(!this.listening);
    },

    // A tap on Guide reaches here without an await first, so wakeAudio() still counts as a tap.
    async setGuide(on) {
      this.micError = "";
      if (on) wakeAudio();
      if (!on) {
        this.listening = false;
        socket.sendJson({ type: "mode", mode: "off" });
        await capture?.pause();
        return;
      }
      try {
        if (!capture) {
          // Loaded on first use: the VAD's runtime is large, and the first screens needn't wait.
          const createCapture = makeCapture ?? (await import("../audio/capture.js")).createCapture;
          capture = await createCapture({
            send: (message) => socket.sendJson(message),
            sendAudio: (buffer) => socket.sendAudio(buffer),
            audioContext,
            deviceId: this.micId,
            processing: this.processing,
            onLevel: (level) => (this.level = level),
          });
        }
        await capture.start();
      } catch (error) {
        // A remembered input that is no longer plugged in: fall back to the phone's default.
        if (error?.name === "OverconstrainedError" && this.micId) {
          capture = null;
          this.setStoredMic("");
          return this.setGuide(true);
        }
        this.micError = error?.name === "NotAllowedError" ? "mic-denied" : "mic-failed";
        return;
      }
      this.listening = true;
      this.micLabel = capture.input.label;
      socket.sendJson({ type: "mode", mode: "guide" });
      await this.listMics(); // names are only known once the mic is allowed
    },

    async listMics() {
      try {
        this.mics = microphones(await navigator.mediaDevices.enumerateDevices());
      } catch {
        this.mics = [];
      }
    },

    setStoredMic(id) {
      this.micId = id;
      store("micId", id);
    },

    // Inside the tap on the mic list or the switch: the mic is re-opened with the new setting.
    async setMic(id) {
      wakeAudio();
      this.setStoredMic(id);
      await this.restartCapture();
    },

    async setProcessing(on) {
      wakeAudio();
      this.processing = on;
      store("micProcessing", on ? "" : "off");
      await this.restartCapture();
    },

    async restartCapture() {
      if (capture) {
        const old = capture;
        capture = null;
        await old.destroy();
      }
      this.micLabel = "";
      if (this.listening) {
        this.listening = false;
        await this.setGuide(true);
      }
    },

    // Remote pause from a host phone: Guide off, or back on.
    async remote(paused) {
      this.remotePaused = paused;
      if (paused === this.listening) await this.setGuide(!paused);
    },

    sendText(text) {
      const trimmed = text.trim();
      if (!trimmed) return false;
      socket.sendJson({ type: "text", text: trimmed });
      return true;
    },

    newDay(day) {
      this.day = day;
      this.bubbles = [];
      this.sentences = {};
    },

    receive(message) {
      const sentence = this.sentences[message.sentence_id];
      if (message.type === "sentence") {
        const known = message.id in this.sentences;
        this.sentences[message.id] = {
          id: message.id,
          bubbleId: message.bubble_id,
          zh: message.zh,
          yue: message.yue,
          en: "",
          status: message.status,
          clip: message.status === "ok" ? "pending" : "none",
        };
        if (known) return;
        let bubble = this.bubbles.find((b) => b.id === message.bubble_id);
        if (!bubble) {
          bubble = { id: message.bubble_id, sentenceIds: [] };
          this.bubbles.push(bubble);
        }
        bubble.sentenceIds.push(message.id);
      } else if (message.type === "no_clip" && sentence) {
        sentence.clip = "none";
      } else if (message.type === "english" && sentence) {
        sentence.en = message.en;
      } else if (message.type === "guide_remote") {
        this.remote(message.paused);
      } else if (message.type === "role") {
        this.replaced();
      } else if (message.type === "day") {
        this.newDay(message.day);
      }
    },
  },
});
