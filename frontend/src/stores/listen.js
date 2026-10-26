// A listener phone's state (weeks 4–5): the join link's token, the connection, the hub's
// status, today's bubbles and the player. The socket, audio elements and cache live outside
// Vue's reactivity, in this module.
//
// Host phones (the owner's and wife's, page /host) are listeners that sign in with the hub PIN
// and API token instead of the join link (hard rule 1). Only they get the day's spend, the join
// link (Share link, Make a new link) and remote pause; the server refuses these to anyone else.
//
// Which clips auto-play (hard rule 11):
// - joining fresh (nothing from today on the phone): earlier sentences are history; they show
//   without unplayed markers and never play by themselves;
// - after a reconnect: the sentences missed meanwhile are new, so live plays them in order
//   (with Jump to latest if they pile up);
// - a clip asked for again for a replay is only cached.

import { defineStore } from "pinia";
import { ClipOutput } from "../audio/clipOutput.js";
import { KeepAlive } from "../audio/keepAlive.js";
import { ListenerPlayer } from "../audio/listenerPlayer.js";
import { ClipCache } from "../lib/clipCache.js";
import { keepScreenOn, store, stored } from "../lib/device.js";
import { RoomSocket } from "../lib/roomSocket.js";

const RECENT_CLIPS = 50; // kept in memory too, so live clips never wait on IndexedDB

let socket = null;
let player = null;
let keeper = null;
let cache = null;
let watching = false; // the page's wake-up listeners, added once
let historyUpTo = 0; // sentences up to here were said before this phone joined today
let helloLastId = 0; // what this phone said it had in its last hello
const recent = new Map(); // sentence id -> MP3 bytes
const refetching = new Set(); // clips asked for again for a replay

let linkToken = ""; // from the link just opened, in case the phone can't store it (private mode)

// The join link (/join#<token>) stores its token here, then the page moves to /listen.
export function rememberJoinToken(token) {
  linkToken = token;
  store("roomToken", token);
}

// Tests swap in fakes for the socket, player and cache.
export function setListenParts(parts) {
  socket = parts.socket ?? socket;
  player = parts.player ?? player;
  cache = parts.cache ?? cache;
  historyUpTo = helloLastId = 0;
  recent.clear();
  refetching.clear();
}

// iOS's lock-screen pause would stop the keep-alive; the app has its own controls.
function holdLockScreen() {
  if (!("mediaSession" in navigator)) return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({ title: "重慶翻譯", artist: "廣東話 Cantonese" });
  } catch {
    // not supported: the lock screen just shows the page's title
  }
  for (const action of ["pause", "stop"]) {
    try {
      navigator.mediaSession.setActionHandler(action, () => {});
    } catch {
      // an action this iOS doesn't know
    }
  }
}

export const useListenStore = defineStore("listen", {
  state: () => ({
    token: linkToken || stored("roomToken"),
    host: false, // the /host page
    pin: stored("hubPin"), // host phones: the same PIN and token as the hub page
    apiToken: stored("apiToken"),
    screen: "start", // credentials (host phones) | start | room
    refused: "", // bad_credentials | link_changed: the link (or the host's PIN) no longer works
    spend: null, // host phones: { usd, warn, warnUsd }
    joinToken: "", // host phones: the family's join link
    connection: "offline", // connecting | connected | offline
    hub: { online: true, listening: false, remotePaused: false },
    day: stored("listenDay"),
    bubbles: [], // [{ id, sentenceIds: [] }], oldest first
    sentences: {}, // id -> { id, bubbleId, zh, yue, en, status, clip, played }
    player: { state: "live", waiting: 0, showJump: false, playingId: null },
    sound: stored("soundOff") !== "1",
    english: stored("english") === "1",
    audioBlocked: false, // the keep-alive was stopped and couldn't restart: "Tap to resume audio"
  }),

  getters: {
    lastId: (s) => Math.max(0, ...Object.keys(s.sentences).map(Number)),
    joinUrl: (s) => (s.joinToken ? `${location.origin}/join#${s.joinToken}` : ""),
  },

  actions: {
    // Called by the page before anything else: /host signs in with the PIN and token.
    setHost(host) {
      this.host = host;
      if (host && !(this.pin && this.apiToken)) this.screen = "credentials";
    },

    saveHostCredentials(pin, token) {
      this.pin = pin.trim();
      this.apiToken = token.trim();
      store("hubPin", this.pin);
      store("apiToken", this.apiToken);
      this.refused = "";
      this.screen = "start";
    },

    // Inside the Start tap: unlocks audio on iOS, starts the keep-alive and keeps the screen
    // on (hard rule 12), then shows the phone's own bubbles and connects.
    async start() {
      const output = new ClipOutput({
        load: (id) => this.loadClip(id),
        onEnded: (id, ok) => player.ended(id, ok),
        onInterrupted: () => this.setAutoPlay(false),
      });
      output.unlock();
      keeper = new KeepAlive({ onBlocked: (blocked) => (this.audioBlocked = blocked) });
      keeper.start();
      player = new ListenerPlayer({
        output,
        onChange: () => this.syncPlayer(),
        onPlayed: (id) => this.markPlayed(id),
      });
      player.setSound(this.sound);
      keepScreenOn();
      holdLockScreen();
      if (!watching) {
        watching = true;
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState !== "visible") return;
          keeper.check();
          socket?.wake();
        });
        window.addEventListener("online", () => socket?.wake());
      }
      this.screen = "room";

      cache = await ClipCache.open();
      for (const sentence of await cache.loadDay(this.day)) this.addSentence(sentence);
      socket = new RoomSocket({
        hello: () => this.hello(),
        onStatus: (status) => (this.connection = status),
        onReady: (message) => this.ready(message),
        onRefused: (code) => this.refuse(code),
        onMessage: (message) => this.receive(message),
        onClip: (id, data) => this.receiveClip(id, data),
      });
      socket.connect();
    },

    hello() {
      helloLastId = this.lastId;
      const access = this.host ? { pin: this.pin, token: this.apiToken } : { room: this.token };
      return { role: "listener", ...access, day: this.day, last_id: helloLastId };
    },

    ready(message) {
      if (this.host) socket.sendJson({ type: "link" }); // for Share link
      if (message.day !== this.day) this.newDay(message.day);
      historyUpTo = this.lastId ? 0 : message.latest_id;
      // Clips this phone missed when its connection dropped between a sentence and its clip.
      for (const sentence of Object.values(this.sentences)) {
        if (sentence.clip === "pending" && sentence.id <= helloLastId) {
          socket.sendJson({ type: "clip_request", sentence_id: sentence.id });
        }
      }
    },

    refuse(code) {
      this.refused = code;
      this.screen = this.host ? "credentials" : "start";
      keeper?.stop();
      player?.setSound(false);
    },

    // Become hub: this page lets go of the room before the hub page takes over.
    leave() {
      socket?.close();
      keeper?.stop();
      player?.reset();
      this.screen = "start";
    },

    receive(message) {
      const sentence = this.sentences[message.sentence_id];
      if (message.type === "sentence") {
        const old = this.sentences[message.id];
        this.addSentence({
          id: message.id,
          bubbleId: message.bubble_id,
          zh: message.zh,
          yue: message.yue,
          en: old?.en ?? "",
          status: message.status,
          clip: old?.clip === "ready" ? "ready" : message.status === "ok" ? "pending" : "none",
          played: old?.played ?? message.id <= historyUpTo,
        });
        this.persist(message.id);
      } else if (message.type === "english" && sentence) {
        sentence.en = message.en;
        this.persist(sentence.id);
      } else if (message.type === "no_clip" && sentence) {
        sentence.clip = "none";
        this.persist(sentence.id);
      } else if (message.type === "hub_status") {
        this.hub = {
          online: message.online,
          listening: message.listening,
          remotePaused: message.remote_paused,
        };
      } else if (message.type === "day") {
        this.newDay(message.day);
      } else if (message.type === "spend") {
        this.spend = { usd: message.usd, warn: message.warn, warnUsd: message.warn_usd };
      } else if (message.type === "join_link") {
        this.joinToken = message.token;
      }
    },

    receiveClip(id, data) {
      recent.set(id, data);
      if (recent.size > RECENT_CLIPS) recent.delete(recent.keys().next().value);
      cache?.putClip(this.day, id, data);
      const sentence = this.sentences[id];
      if (!sentence) return;
      sentence.clip = "ready";
      this.persist(id);
      if (refetching.delete(id)) return;
      if (!sentence.played && id > historyUpTo) player.arrive(id);
    },

    addSentence(sentence) {
      const old = this.sentences[sentence.id];
      if (old) {
        Object.assign(old, sentence);
        return;
      }
      this.sentences[sentence.id] = sentence;
      let bubble = this.bubbles.find((b) => b.id === sentence.bubbleId);
      if (!bubble) {
        bubble = { id: sentence.bubbleId, sentenceIds: [] };
        this.bubbles.push(bubble);
      }
      bubble.sentenceIds.push(sentence.id);
    },

    persist(id) {
      const sentence = this.sentences[id];
      if (cache && sentence) cache.putSentence(this.day, { ...sentence });
    },

    // For the player: memory first, then the phone's cache; a clip missing from both is asked
    // for again (the server has it in memory or in Cloud Storage), for the next tap.
    async loadClip(id) {
      const data = recent.get(id) ?? (await cache?.getClip(this.day, id));
      if (!data && this.sentences[id]) {
        refetching.add(id);
        this.sentences[id].clip = "pending";
        socket?.sendJson({ type: "clip_request", sentence_id: id });
      }
      return data;
    },

    markPlayed(id) {
      if (!this.sentences[id]) return;
      this.sentences[id].played = true;
      this.persist(id);
    },

    syncPlayer() {
      this.player = {
        state: player.state,
        waiting: player.waiting,
        showJump: player.showJump,
        playingId: player.playingId,
      };
    },

    // Bubbles start fresh each trip-local morning; earlier days stay in the phone's cache.
    newDay(day) {
      this.day = day;
      store("listenDay", day);
      this.bubbles = [];
      this.sentences = {};
      recent.clear();
      refetching.clear();
      historyUpTo = 0;
      player?.reset();
    },

    // --- taps -----------------------------------------------------------------------------

    replayBubble(bubble) {
      player.replay(bubble.sentenceIds.filter((id) => this.sentences[id].clip === "ready"));
    },

    replaySentence(id) {
      if (this.sentences[id]?.clip === "ready") player.replay([id]);
    },

    playNew() {
      player.playNew();
    },

    jumpToLatest() {
      player.jumpToLatest();
    },

    setAutoPlay(on) {
      if (on) player.playNew();
      else player.pause();
    },

    setSound(on) {
      this.sound = on;
      store("soundOff", on ? "" : "1");
      player.setSound(on);
    },

    setEnglish(on) {
      this.english = on;
      store("english", on ? "1" : "");
    },

    resumeAudio() {
      keeper.resume();
    },

    // --- host phones ----------------------------------------------------------------------

    setGuidePaused(paused) {
      socket.sendJson({ type: "guide_control", paused });
    },

    // The old link stops working at once; family phones on it are disconnected.
    newJoinLink() {
      this.joinToken = "";
      socket.sendJson({ type: "link", new: true });
    },
  },
});
