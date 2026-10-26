// The hub's state: credentials, connection, the Guide latch and today's bubbles (text only:
// from weeks 4–5 the hub never plays Cantonese, so capture never pauses in phase 1, hard rule
// 13). The socket and microphone live outside Vue's reactivity, in this module.
//
// One active hub (architecture doc): Start on this page (or Become hub on a host phone, which
// opens it) takes over from any other hub. An automatic reconnect never does: if another phone
// took over meanwhile, this one stops and says so.

import { defineStore } from "pinia";
import { keepScreenOn, store, stored } from "../lib/device.js";
import { RoomSocket } from "../lib/roomSocket.js";

let socket = null;
let capture = null;
let takeover = false; // true until the first ready after Start

// Tests swap in fakes for the socket and the microphone.
export function setHubParts(parts) {
  socket = parts.socket ?? socket;
  capture = parts.capture ?? capture;
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

    async setGuide(on) {
      this.micError = "";
      if (!on) {
        this.listening = false;
        socket.sendJson({ type: "mode", mode: "off" });
        await capture?.pause();
        return;
      }
      try {
        if (!capture) {
          // Loaded on first use: the VAD's runtime is large, and the first screens needn't wait.
          const { createCapture } = await import("../audio/capture.js");
          capture = await createCapture({
            send: (message) => socket.sendJson(message),
            sendAudio: (buffer) => socket.sendAudio(buffer),
          });
        }
        await capture.start();
      } catch (error) {
        this.micError = error?.name === "NotAllowedError" ? "mic-denied" : "mic-failed";
        return;
      }
      this.listening = true;
      socket.sendJson({ type: "mode", mode: "guide" });
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
