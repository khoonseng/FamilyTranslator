<script setup>
// The listener's voice-note thread (architecture doc, "Listener experience"): the Cantonese
// large, the guide's Mandarin small, English if switched on. ▶ replays a bubble; tapping a
// sentence replays just that sentence (hard rule 11). Unplayed sentences carry a blue marker.
// Host phones also see which speech-to-text and translator produced each sentence.
// Phones and tablets alike: one centred column, with larger text on an iPad.
// Family replies to the guide (phase 2) look like WhatsApp (owner decision 2026-11-05): the
// guide on the left in white, replies on the right in green, "You" on the asker's own phone.
import { computed, nextTick, onMounted, watch } from "vue";
import { text } from "../lib/profile.js";
import { useListenStore } from "../stores/listen.js";
import ConversationBubble from "./ConversationBubble.vue";
import HostPanel from "./HostPanel.vue";
import TalkBar from "./TalkBar.vue";

const listen = useListenStore();

const showPlayer = computed(
  () => listen.player.showJump || (listen.player.state !== "live" && listen.player.waiting),
);

const atBottom = () => window.innerHeight + window.scrollY >= document.body.scrollHeight - 300;
const toBottom = (behavior) => window.scrollTo({ top: document.body.scrollHeight, behavior });

// Keep the newest bubble in view, unless the listener scrolled up to read.
watch(
  () => listen.lastId,
  async () => {
    const follow = atBottom(); // measured before the new bubble is drawn
    await nextTick();
    if (follow) toBottom("smooth");
  },
);
onMounted(() => toBottom("instant"));

const pill = (on) =>
  on ? "bg-blue-600 text-white border-blue-600" : "bg-white text-slate-700 border-slate-300";
</script>

<template>
  <main class="min-h-dvh bg-slate-100">
    <header class="sticky top-0 z-10 bg-slate-100/95 p-3 pt-[max(0.75rem,env(safe-area-inset-top))] backdrop-blur">
      <div class="mx-auto flex max-w-3xl flex-col gap-2">
        <p v-if="listen.connection !== 'connected'"
          class="rounded-lg bg-amber-200 px-3 py-2 text-xl text-amber-950 md:text-2xl">
          {{ text.reconnecting }}
        </p>
        <p v-else-if="!listen.hub.online"
          class="rounded-lg bg-slate-300 px-3 py-2 text-xl text-slate-900 md:text-2xl">
          {{ text.hubOffline }}
        </p>
        <p v-else-if="listen.hub.remotePaused"
          class="rounded-lg bg-slate-200 px-3 py-2 text-lg text-slate-800 md:text-xl">
          {{ text.guidePaused }}
        </p>

        <HostPanel v-if="listen.host" />

        <div class="flex flex-wrap gap-2 text-base md:text-lg">
          <button class="rounded-full border px-4 py-2 disabled:opacity-40"
            :class="pill(listen.sound && listen.player.state === 'live')" :disabled="!listen.sound"
            @click="listen.setAutoPlay(listen.player.state !== 'live')">
            {{ text.autoPlay }}
          </button>
          <button class="rounded-full border px-4 py-2" :class="pill(listen.english)"
            @click="listen.setEnglish(!listen.english)">
            {{ text.english }}
          </button>
          <button class="rounded-full border px-4 py-2" :class="pill(!listen.sound)"
            @click="listen.setSound(!listen.sound)">
            {{ text.soundOff }}
          </button>
          <button class="rounded-full border border-slate-300 bg-white px-4 py-2 text-slate-700 disabled:opacity-40"
            :disabled="listen.talking" @click="listen.openHistory()">
            {{ text.history }}
          </button>
        </div>
      </div>
    </header>

    <section class="mx-auto flex max-w-3xl flex-col gap-3 p-3"
      :class="listen.canTalk ? 'pb-64' : 'pb-36'">
      <p v-if="!listen.bubbles.length" class="py-16 text-center text-2xl text-slate-500 md:text-3xl">
        {{ text.waitingForGuide }}
      </p>

      <ConversationBubble v-for="bubble in listen.bubbles" :key="bubble.id"
        :bubble="bubble" :sentences="listen.sentences" :playing-id="listen.player.playingId"
        :device="listen.device" :sound="listen.sound" :english="listen.english" :host="listen.host"
        @play-bubble="listen.replayBubble" @play-sentence="listen.replaySentence" />
    </section>

    <footer class="fixed inset-x-0 bottom-0 bg-slate-100/95 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <div class="mx-auto flex max-w-3xl flex-col gap-2">
        <template v-if="showPlayer">
          <button v-if="listen.player.showJump"
            class="w-full rounded-2xl bg-amber-500 p-5 text-3xl font-bold text-white shadow-lg active:bg-amber-600"
            @click="listen.jumpToLatest()">
            {{ text.jumpToLatest }}
          </button>
          <button v-else
            class="w-full rounded-2xl bg-blue-600 p-5 text-3xl font-bold text-white shadow-lg active:bg-blue-700"
            @click="listen.playNew()">
            {{ text.playNew(listen.player.waiting) }}
          </button>
        </template>
        <TalkBar />
      </div>
    </footer>

    <div v-if="listen.audioBlocked" class="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-6">
      <button class="w-full max-w-md rounded-2xl bg-emerald-600 p-8 text-3xl font-bold text-white shadow-xl"
        @click="listen.resumeAudio()">
        {{ text.tapToResume }}
      </button>
    </div>
  </main>
</template>
