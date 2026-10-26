// The hub's state (single-device MVP): credentials, connection, the Guide latch, bubbles and
// clips. The socket, microphone and player live outside Vue's reactivity, in this module.

import { defineStore } from "pinia";
import { ClipPlayer } from "../audio/player.js";
import { keepScreenOn, store, stored } from "../lib/device.js";
import { RoomSocket } from "../lib/roomSocket.js";

let socket = null;
let capture = null;
let player = null;

export const useHubStore = defineStore("hub", {
  state: () => ({
    pin: stored("hubPin"),
    token: stored("apiToken"),
    screen: stored("hubPin") && stored("apiToken") ? "start" : "credentials",
    refused: false,
    connection: "offline", // connecting | connected | offline
    listening: false, // the Guide latch (hard rule 8)
    micError: "",
    earphones: stored("earphones") === "1", // MVP-only exception to hard rule 13
    playing: false,
    bubbles: [], // [{ id, sentenceIds: [] }]
    sentences: {}, // id -> { id, bubbleId, zh, yue, en, status, clip, played }
  }),

  getters: {
    // Capture runs while Guide is latched, except during playback unless earphones are in.
    captureWanted: (s) => s.listening && (s.earphones || !s.playing),
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

    // Runs inside the start tap, which unlocks audio on iOS (hard rule 12).
    start() {
      player = new ClipPlayer({
        onPlaying: (playing) => {
          this.playing = playing;
          this.syncCapture();
        },
        onPlayed: (id) => {
          if (this.sentences[id]) this.sentences[id].played = true;
        },
      });
      player.unlock();
      socket = new RoomSocket({
        hello: () => ({ role: "hub", pin: this.pin, token: this.token }),
        onStatus: (status) => (this.connection = status),
        onReady: () => {
          if (this.listening) socket.sendJson({ type: "mode", mode: "guide" }); // after a reconnect
        },
        onRefused: () => {
          this.refused = true;
          this.screen = "credentials";
        },
        onMessage: (message) => this.receive(message),
        onClip: (id, data) => this.receiveClip(id, data),
      });
      socket.connect();
      keepScreenOn();
      this.screen = "hub";
    },

    async toggleGuide() {
      this.micError = "";
      if (this.listening) {
        this.listening = false;
        socket.sendJson({ type: "mode", mode: "off" });
        await this.syncCapture();
        return;
      }
      try {
        // Loaded on first use: the VAD's runtime is large, and the first screens needn't wait.
        const { createCapture } = await import("../audio/capture.js");
        capture ||= await createCapture({
          send: (message) => socket.sendJson(message),
          sendAudio: (buffer) => socket.sendAudio(buffer),
        });
      } catch (error) {
        this.micError = error?.name === "NotAllowedError" ? "mic-denied" : "mic-failed";
        return;
      }
      this.listening = true;
      socket.sendJson({ type: "mode", mode: "guide" });
      await this.syncCapture();
    },

    setEarphones(on) {
      this.earphones = on;
      store("earphones", on ? "1" : "");
      this.syncCapture();
    },

    async syncCapture() {
      if (!capture) return;
      if (this.captureWanted) await capture.start();
      else await capture.pause();
    },

    sendText(text) {
      const trimmed = text.trim();
      if (!trimmed) return false;
      socket.sendJson({ type: "text", text: trimmed });
      return true;
    },

    receive(message) {
      if (message.type === "sentence") {
        this.sentences[message.id] = {
          id: message.id,
          bubbleId: message.bubble_id,
          zh: message.zh,
          yue: message.yue,
          en: "",
          status: message.status,
          clip: message.status === "ok" ? "pending" : "none",
          played: false,
        };
        let bubble = this.bubbles.find((b) => b.id === message.bubble_id);
        if (!bubble) {
          bubble = { id: message.bubble_id, sentenceIds: [] };
          this.bubbles.push(bubble);
        }
        bubble.sentenceIds.push(message.id);
      } else if (message.type === "no_clip" && this.sentences[message.sentence_id]) {
        this.sentences[message.sentence_id].clip = "none";
      } else if (message.type === "english" && this.sentences[message.sentence_id]) {
        this.sentences[message.sentence_id].en = message.en;
      }
    },

    receiveClip(id, data) {
      if (this.sentences[id]) this.sentences[id].clip = "ready";
      player.enqueue(id, URL.createObjectURL(new Blob([data], { type: "audio/mpeg" })));
    },
  },
});
