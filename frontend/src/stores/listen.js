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
//
// Family replies (phase 2): a family phone unlocks Talk with the hub PIN ("Ask the guide"); host
// phones have it already. Hold to talk records the phone's own mic only while held, after the
// guide has been quiet for 2 s and while no other phone is talking; it pauses the phone's own
// playback and keep-alive meanwhile (hard rules 12 and 13). Typing works any time. Replies show
// as text (their Mandarin is for the guide, played by the hub); the asker's phone says "You".

import { defineStore } from "pinia";
import { ClipOutput } from "../audio/clipOutput.js";
import { KeepAlive } from "../audio/keepAlive.js";
import { ListenerPlayer } from "../audio/listenerPlayer.js";
import { MAX_TALK_S, startRecorder, talkBlock } from "../audio/talk.js";
import { ClipCache } from "../lib/clipCache.js";
import { keepScreenOn, store, stored } from "../lib/device.js";
import { availableHistoryDays, historyBubbles, HistoryRequests } from "../lib/history.js";
import { text } from "../lib/profile.js";
import { RoomSocket } from "../lib/roomSocket.js";

const RECENT_CLIPS = 50; // kept in memory too, so live clips never wait on IndexedDB

let socket = null;
let player = null;
let keeper = null;
let cache = null;
let archive = null;
let historyListTurn = 0;
let historyDayTurn = 0;
let historyAudioTurn = 0;
let watching = false; // the page's wake-up listeners, added once
let historyUpTo = 0; // sentences up to here were said before this phone joined today
let helloLastId = 0; // what this phone said it had in its last hello
const recent = new Map(); // sentence id -> MP3 bytes
const refetching = new Set(); // clips asked for again for a replay
let makeRecorder = startRecorder;
let recorder = null; // the phone's mic while Talk is held
let talkTurn = 0; // each press (and each release) moves it on: a late mic from an old press is stopped
let talkTimers = [];
let resumeLive = false; // auto-play was on before Talk: switch it back on afterwards

// An anonymous id this phone keeps, so its own replies can say "You" (no names).
function deviceId() {
  let id = stored("deviceId");
  if (!id) {
    id = globalThis.crypto?.randomUUID?.() ?? String(Math.random()).slice(2);
    store("deviceId", id);
  }
  return id;
}

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
  keeper = parts.keeper ?? keeper;
  archive = parts.archive ?? archive;
  makeRecorder = parts.makeRecorder ?? makeRecorder;
  historyUpTo = helloLastId = 0;
  recent.clear();
  refetching.clear();
}

// iOS's lock-screen pause would stop the keep-alive; the app has its own controls.
function holdLockScreen() {
  if (!("mediaSession" in navigator)) return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({ title: text.appName, artist: text.mediaArtist });
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
    pin: stored("hubPin"), // host phones, and family phones that unlocked Talk
    apiToken: stored("apiToken"),
    screen: "start", // credentials (host phones) | start | room
    refused: "", // bad_credentials | link_changed: the link (or the host's PIN) no longer works
    spend: null, // host phones: { usd, warn, warnUsd }
    joinToken: "", // host phones: the family's join link
    connection: "offline", // connecting | connected | offline
    hub: {
      online: true,
      listening: false,
      remotePaused: false,
      mic: "",
      micLost: false,
      interrupted: false,
      guideTalking: false, // Talk can't start (the guide has priority)
      familyTalking: false, // another phone holds Talk
    },
    device: deviceId(),
    canTalk: false, // the server accepted the hub PIN: Talk and typing to the guide
    pinWrong: false,
    talking: false, // Talk is held
    talkLive: false, // ...and the mic is open: speak now
    talkSeconds: 0,
    talkError: "", // guide_talking | someone_talking | mic-denied | mic-failed
    day: stored("listenDay"),
    bubbles: [], // [{ id, sentenceIds: [] }], oldest first
    // id -> { id, bubbleId, kind, zh, yue, mandarin, en, asker, status, stt, provider, voice,
    //         clip, played }; for a reply, `zh` is what was said and `en` its other language
    sentences: {},
    player: { state: "live", waiting: 0, showJump: false, playingId: null },
    sound: stored("soundOff") !== "1",
    english: stored("english") === "1",
    audioBlocked: false, // the keep-alive was stopped and couldn't restart: "Tap to resume audio"
    historyOpen: false,
    historyDates: [],
    historyDate: "",
    historyDatesLoading: false,
    historyDatesError: false,
    historySentences: {},
    historyAfter: 0, // 0 starts the day, null means the last page arrived
    historyLoading: false,
    historyError: false,
    historyAudioMissing: false,
  }),

  getters: {
    lastId: (s) => Math.max(0, ...Object.keys(s.sentences).map(Number)),
    joinUrl: (s) => (s.joinToken ? `${location.origin}/join#${s.joinToken}` : ""),
    historyBubbles: (s) => historyBubbles(s.historySentences),
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
        load: (id) => typeof id === "string" ? this.loadHistoryClip(id) : this.loadClip(id),
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
        onStatus: (status) => {
          this.connection = status;
          if (status !== "connected") archive.disconnect();
        },
        onReady: (message) => this.ready(message),
        onRefused: (code) => this.refuse(code),
        onMessage: (message) => this.receive(message),
        onClip: (id, data, header) => {
          if (header.type === "history_clip") archive.receive(header, data);
          else this.receiveClip(id, data, header.voice);
        },
      });
      archive = new HistoryRequests(socket);
      socket.connect();
    },

    hello() {
      helloLastId = this.lastId;
      const access = this.host
        ? { pin: this.pin, token: this.apiToken }
        : { room: this.token, ...(this.pin ? { pin: this.pin } : {}) };
      return { role: "listener", ...access, device: this.device, day: this.day, last_id: helloLastId };
    },

    ready(message) {
      if (this.host) socket.sendJson({ type: "link" }); // for Share link
      this.canTalk = !!message.talk;
      if (!this.host && this.pin && !message.talk) {
        this.pinWrong = true; // a wrong hub PIN: the phone still listens, just can't talk
        this.pin = "";
        store("hubPin", "");
      }
      if (message.day !== this.day) this.newDay(message.day);
      historyUpTo = this.lastId ? 0 : message.latest_id;
      // Clips this phone missed when its connection dropped between a sentence and its clip.
      for (const sentence of Object.values(this.sentences)) {
        if (sentence.clip === "pending" && sentence.id <= helloLastId) {
          socket.sendJson({ type: "clip_request", sentence_id: sentence.id });
        }
      }
      if (this.historyOpen) {
        this.refreshHistoryDates();
        this.loadHistoryPage();
      }
    },

    refuse(code) {
      this.closeHistory();
      archive?.disconnect();
      this.refused = code;
      this.screen = this.host ? "credentials" : "start";
      keeper?.stop();
      player?.setSound(false);
    },

    // Become hub: this page lets go of the room before the hub page takes over.
    leave() {
      this.closeHistory();
      archive?.disconnect();
      socket?.close();
      keeper?.stop();
      player?.reset();
      this.screen = "start";
    },

    receive(message) {
      if (message.type.startsWith("history_")) {
        archive?.receive(message);
        return;
      }
      const sentence = this.sentences[message.sentence_id];
      if (message.type === "sentence") {
        const old = this.sentences[message.id];
        const reply = message.kind === "reply"; // text only here: its Mandarin is for the guide
        this.addSentence({
          id: message.id,
          bubbleId: message.bubble_id,
          kind: message.kind ?? "guide",
          zh: message.zh,
          yue: message.yue,
          mandarin: message.mandarin ?? "",
          asker: message.asker ?? "",
          en: old?.en ?? "",
          status: message.status,
          stt: message.stt ?? "", // shown on host phones only
          provider: message.provider ?? "",
          clip: reply ? "none"
            : old?.clip === "ready" ? "ready" : message.status === "ok" ? "pending" : "none",
          played: reply || (old?.played ?? message.id <= historyUpTo),
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
          mic: message.mic ?? "", // external (the clip-on) | phone | "" (not reported)
          micLost: !!message.mic_lost,
          interrupted: !!message.interrupted,
          guideTalking: !!message.guide_talking,
          familyTalking: !!message.family_talking,
        };
      } else if (message.type === "day") {
        this.newDay(message.day);
      } else if (message.type === "spend") {
        this.spend = { usd: message.usd, warn: message.warn, warnUsd: message.warn_usd };
      } else if (message.type === "join_link") {
        this.joinToken = message.token;
      } else if (message.type === "error" && ["guide_talking", "someone_talking"].includes(message.code)) {
        this.talkError = message.code; // the server refused Talk: the guide or someone else first
        this.stopTalk({ refused: true });
      }
    },

    receiveClip(id, data, voice = "") {
      recent.set(id, data);
      if (recent.size > RECENT_CLIPS) recent.delete(recent.keys().next().value);
      cache?.putClip(this.day, id, data);
      const sentence = this.sentences[id];
      if (!sentence) return;
      sentence.clip = "ready";
      if (voice) sentence.voice = voice; // shown on host phones only
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
      player?.reset({ browsingHistory: this.historyOpen });
      if (this.historyOpen) this.refreshHistoryDates();
    },

    // --- History --------------------------------------------------------------------------

    openHistory() {
      if (this.talking) return;
      player.pause();
      this.historyOpen = true;
      this.refreshHistoryDates();
    },

    closeHistory() {
      if (!this.historyOpen) return;
      this.backToHistoryDates();
      historyListTurn++;
      this.historyOpen = false;
    },

    backToHistoryDates() {
      this.stopHistoryReplay();
      historyDayTurn++;
      this.historyDate = "";
      this.historySentences = {};
      this.historyAfter = 0;
      this.historyLoading = this.historyError = false;
    },

    async refreshHistoryDates() {
      const turn = ++historyListTurn;
      this.historyDatesLoading = true;
      this.historyDatesError = false;
      const cached = await cache?.listDays() ?? [];
      if (turn !== historyListTurn) return;
      this.historyDates = availableHistoryDays([...this.historyDates, ...cached]);
      try {
        if (this.connection === "connected") {
          const { days } = await archive.send("history_days_request");
          if (turn === historyListTurn) this.historyDates = availableHistoryDays([...days, ...cached]);
        }
      } catch {
        if (turn === historyListTurn) this.historyDatesError = true;
      } finally {
        if (turn === historyListTurn) this.historyDatesLoading = false;
      }
    },

    async openHistoryDay(day) {
      this.backToHistoryDates();
      const turn = historyDayTurn;
      this.historyDate = day;
      this.historyLoading = true;
      const sentences = await cache?.loadDay(day) ?? [];
      if (turn !== historyDayTurn) return;
      for (const sentence of sentences) this.historySentences[sentence.id] = sentence;
      this.historyLoading = false;
      await this.loadHistoryPage();
    },

    async loadHistoryPage() {
      const day = this.historyDate;
      if (!day || this.historyLoading || this.historyAfter === null || this.connection !== "connected") return;
      const turn = historyDayTurn;
      this.historyLoading = true;
      this.historyError = false;
      try {
        const page = await archive.send("history_page_request", { day, after: this.historyAfter });
        if (turn !== historyDayTurn) return;
        for (const { bubble_id, ...record } of page.sentences) {
          const cached = this.historySentences[record.id];
          const sentence = { ...cached, ...record, bubbleId: bubble_id };
          if (cached?.clip === "ready") sentence.clip = "ready";
          this.historySentences[record.id] = sentence;
          if (day !== this.day) cache?.putSentence(day, sentence);
        }
        this.historyAfter = page.next_after;
      } catch {
        if (turn === historyDayTurn) this.historyError = true;
      } finally {
        if (turn === historyDayTurn) this.historyLoading = false;
      }
    },

    replayHistory(ids) {
      if (!this.historyDate || !this.sound) return;
      historyAudioTurn++;
      this.historyAudioMissing = false;
      player.replay(ids
        .filter((id) => this.historySentences[id]?.kind !== "reply"
          && this.historySentences[id]?.clip === "ready")
        .map((id) => `${this.historyDate}/${id}`));
    },

    stopHistoryReplay() {
      historyAudioTurn++;
      this.historyAudioMissing = false;
      player?.pause();
    },

    async loadHistoryClip(key) {
      const turn = historyAudioTurn;
      const [day, id] = key.split("/");
      const sentence_id = Number(id);
      const cached = await cache?.getClip(day, sentence_id);
      if (cached) return cached;
      if (turn !== historyAudioTurn) return;
      try {
        const { audio } = await archive.send("history_clip_request", { day, sentence_id });
        if (audio) {
          cache?.putClip(day, sentence_id, audio);
          return audio;
        }
      } catch {
        // Keep the text and allow another tap when the connection returns.
      }
      if (turn === historyAudioTurn) this.historyAudioMissing = true;
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

    // --- family replies (phase 2) -----------------------------------------------------------

    // "Ask the guide": the hub PIN, once per phone. The server checks it on the next hello.
    unlockTalk(pin) {
      this.pin = pin.trim();
      this.pinWrong = false;
      store("hubPin", this.pin);
      socket?.restart();
    },

    // Inside the press on Hold to talk: iOS only lets the mic's audio engine start in a tap.
    async startTalk() {
      const block = talkBlock({ ...this.hub, canTalk: this.canTalk, talking: this.talking });
      if (block || this.talking) return;
      this.talkError = "";
      this.talking = true;
      this.talkLive = false;
      this.talkSeconds = 0;
      resumeLive = player?.state === "live";
      player?.pause(); // the phone's own playback stops while Talk records (hard rule 13)
      keeper?.stop(); // and the keep-alive (hard rule 12)
      socket.sendJson({ type: "talk_start" });
      // Opening the mic takes a moment. Released and pressed again meanwhile (12 Nov), the
      // first press's mic used to be kept running unseen, and every later Talk sent each word
      // twice. Now only the current press's mic may send, and a late one is stopped at once.
      const turn = ++talkTurn;
      let opened;
      try {
        opened = await makeRecorder({
          onPcm: (buffer) => {
            if (turn === talkTurn) socket.sendAudio(buffer);
          },
        });
      } catch (error) {
        if (turn !== talkTurn) return; // an old press: the current one carries on
        this.talkError = error?.name === "NotAllowedError" ? "mic-denied" : "mic-failed";
        this.stopTalk();
        return;
      }
      if (turn !== talkTurn || !this.talking) {
        opened.stop(); // let go before the mic was even open
        return;
      }
      recorder = opened;
      this.talkLive = true;
      talkTimers = [
        setTimeout(() => this.stopTalk(), MAX_TALK_S * 1000), // the 30 s cap
        setInterval(() => (this.talkSeconds += 1), 1000),
      ];
    },

    // Release (or the cap, or a refusal): the mic is fully stopped and playback comes back.
    stopTalk({ refused = false } = {}) {
      if (!this.talking) return;
      talkTurn++; // a mic still opening for this press is stopped when it arrives
      this.talking = false;
      this.talkLive = false;
      talkTimers.forEach((t) => (clearTimeout(t), clearInterval(t)));
      talkTimers = [];
      recorder?.stop();
      recorder = null;
      if (!refused) socket.sendJson({ type: "talk_end" });
      keeper?.start();
      if (resumeLive) player?.playNew();
    },

    sendReply(text) {
      const trimmed = text.trim();
      if (!trimmed || !this.canTalk) return false;
      socket.sendJson({ type: "reply_text", text: trimmed });
      return true;
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
